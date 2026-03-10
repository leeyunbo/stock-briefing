"""Google Search Console 데이터 수집 — 기회 키워드 발굴.

기존 google_indexing.py의 서비스 계정 패턴을 재사용한다.
"""

import logging
from datetime import date, timedelta

from google.auth.transport.requests import Request
from google.oauth2 import service_account
import httpx
from sqlalchemy import select, func
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.core.config import get_settings
from app.core.database import async_session
from app.core.models import GscDailyData, SeoTopic

logger = logging.getLogger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
_API_BASE = "https://www.googleapis.com/webmasters/v3"


def _get_credentials():
    """서비스 계정 자격 증명을 로드한다."""
    sa_path = get_settings().google_service_account_json
    if not sa_path:
        return None
    credentials = service_account.Credentials.from_service_account_file(
        sa_path, scopes=_SCOPES,
    )
    credentials.refresh(Request())
    return credentials


async def fetch_gsc_data(days: int = 28) -> list[dict]:
    """GSC Search Analytics API로 최근 N일 검색 데이터를 조회한다.

    Returns:
        각 행은 {"date", "query", "page", "impressions", "clicks", "position", "ctr"}.
    """
    credentials = _get_credentials()
    if not credentials:
        logger.info("GSC: 서비스 계정 미설정 — 수집 건너뜀")
        return []

    site_url = get_settings().gsc_site_url
    if not site_url:
        logger.info("GSC: gsc_site_url 미설정 — 수집 건너뜀")
        return []

    end_date = date.today() - timedelta(days=3)  # GSC 데이터는 2~3일 지연
    start_date = end_date - timedelta(days=days)

    payload = {
        "startDate": start_date.isoformat(),
        "endDate": end_date.isoformat(),
        "dimensions": ["date", "query", "page"],
        "rowLimit": 5000,
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{_API_BASE}/sites/{site_url}/searchAnalytics/query",
                headers={
                    "Authorization": f"Bearer {credentials.token}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )

        if resp.status_code != 200:
            logger.error("GSC API 실패: status=%s, body=%s", resp.status_code, resp.text[:300])
            return []

        data = resp.json()
        rows = data.get("rows", [])
        result = []
        for row in rows:
            keys = row.get("keys", [])
            if len(keys) < 3:
                continue
            result.append({
                "date": keys[0],
                "query": keys[1],
                "page": keys[2],
                "impressions": row.get("impressions", 0),
                "clicks": row.get("clicks", 0),
                "position": round(row.get("position", 0.0), 1),
                "ctr": round(row.get("ctr", 0.0), 4),
            })

        logger.info("GSC 데이터 조회: %d건 (%s ~ %s)", len(result), start_date, end_date)
        return result

    except Exception as e:
        logger.error("GSC 데이터 수집 오류: %s", e)
        return []


async def save_gsc_data(data: list[dict]) -> int:
    """GSC 데이터를 DB에 저장한다 (중복 무시).

    Returns:
        삽입된 행 수.
    """
    if not data:
        return 0

    inserted = 0
    async with async_session() as db:
        for row in data:
            stmt = sqlite_insert(GscDailyData).values(
                date=row["date"],
                query=row["query"],
                page=row["page"],
                impressions=row["impressions"],
                clicks=row["clicks"],
                position=row["position"],
                ctr=row["ctr"],
            ).on_conflict_do_nothing(
                index_elements=["date", "query", "page"],
            )
            result = await db.execute(stmt)
            inserted += result.rowcount
        await db.commit()

    logger.info("GSC 데이터 저장: %d건 삽입", inserted)
    return inserted


async def find_opportunity_keywords(
    min_impressions: int = 50,
    min_position: float = 5.0,
    max_position: float = 30.0,
) -> list[dict]:
    """기회 키워드를 발굴한다.

    조건: 노출 >= min_impressions, 순위 5~30 (개선 여지 있는 키워드).

    Returns:
        [{"query", "total_impressions", "avg_position", "total_clicks"}]
    """
    async with async_session() as db:
        result = await db.execute(
            select(
                GscDailyData.query,
                func.sum(GscDailyData.impressions).label("total_impressions"),
                func.avg(GscDailyData.position).label("avg_position"),
                func.sum(GscDailyData.clicks).label("total_clicks"),
            )
            .group_by(GscDailyData.query)
            .having(
                func.sum(GscDailyData.impressions) >= min_impressions,
                func.avg(GscDailyData.position) >= min_position,
                func.avg(GscDailyData.position) <= max_position,
            )
            .order_by(func.sum(GscDailyData.impressions).desc())
        )

        opportunities = []
        for row in result.all():
            opportunities.append({
                "query": row.query,
                "total_impressions": row.total_impressions,
                "avg_position": round(row.avg_position, 1),
                "total_clicks": row.total_clicks,
            })

    logger.info("GSC 기회 키워드: %d건 발견", len(opportunities))
    return opportunities


async def create_gsc_topics(opportunities: list[dict]) -> int:
    """기회 키워드를 토픽 큐에 추가한다 (priority=15).

    Returns:
        삽입된 토픽 수.
    """
    if not opportunities:
        return 0

    inserted = 0
    async with async_session() as db:
        for opp in opportunities:
            query = opp["query"]
            stmt = sqlite_insert(SeoTopic).values(
                pattern_type="gsc_opportunity",
                keyword=query,
                title_template=query,
                focus_keyword=query,
                priority=15,
                source="gsc",
                gsc_impressions=opp["total_impressions"],
                gsc_position=opp["avg_position"],
            ).on_conflict_do_nothing(
                index_elements=["pattern_type", "keyword"],
            )
            result = await db.execute(stmt)
            inserted += result.rowcount
        await db.commit()

    logger.info("GSC 토픽 추가: %d건", inserted)
    return inserted

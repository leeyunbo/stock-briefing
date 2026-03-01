"""부동산 데이터 수집기 — 청약Home API + 네이버 뉴스.

청약Home 공공데이터포털 API로 아파트 분양 정보를 수집하고,
네이버 뉴스 API로 부동산 관련 뉴스를 수집한다.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta

import httpx

from app.collector.news import NewsArticle, fetch_news
from app.core.config import get_settings

logger = logging.getLogger(__name__)

APPLYHOME_BASE_URL = "https://api.odcloud.kr/api/ApplyhomeInfoDetailSvc/v1"

# 주택 유형 코드 → 한글 매핑
HOUSE_SECD_MAP = {
    "01": "민영APT",
    "09": "민간사전청약",
    "10": "공공분양",
}

# 수도권 지역 코드
METRO_AREA_CODES = {"서울", "경기", "인천"}


@dataclass(frozen=True)
class SubscriptionInfo:
    """청약 공고 정보."""

    house_manage_no: str       # HOUSE_MANAGE_NO
    pblanc_no: str             # PBLANC_NO
    house_name: str            # HOUSE_NM
    area: str                  # SUBSCRPT_AREA_CODE_NM (서울, 경기 등)
    address: str               # HSSPLY_ADRES
    house_type: str            # 민영APT, 민간사전청약 등
    total_supply_count: int    # TOT_SUPLY_HSHLDCO
    status: str                # "접수중" | "접수예정"
    receipt_start: str         # RCEPT_BGNDE (YYYY-MM-DD)
    receipt_end: str           # RCEPT_ENDDE
    winner_announce: str       # PRZWNER_PRESNATN_DE
    detail_url: str            # PBLANC_URL


@dataclass(frozen=True)
class SubscriptionPrice:
    """청약 분양가 상세."""

    house_manage_no: str
    house_type_area: str       # HOUSE_TY (예: "084A")
    supply_area: float         # SUPLY_AR (m²)
    supply_count: int          # SUPLY_HSHLDCO
    top_amount: int            # LTTOT_TOP_AMOUNT (만원)


@dataclass(frozen=True)
class RealEstateNews:
    """부동산 뉴스 기사."""

    title: str
    summary: str
    link: str
    pub_date: str


@dataclass
class RealEstateData:
    """부동산 브리핑 입력 데이터."""

    news: list[RealEstateNews] = field(default_factory=list)
    subscriptions: list[SubscriptionInfo] = field(default_factory=list)
    prices: dict[str, list[SubscriptionPrice]] = field(default_factory=dict)
    scan_date: str = ""


# ── 네이버 뉴스 수집 ──


_REAL_ESTATE_KEYWORDS = [
    "부동산 시장",
    "아파트 가격",
    "청약 분양",
    "전월세 시장",
    "부동산 정책",
]


async def fetch_real_estate_news() -> list[RealEstateNews]:
    """부동산 관련 뉴스를 여러 키워드로 병렬 수집한다."""
    tasks = [fetch_news(query=kw, count=5) for kw in _REAL_ESTATE_KEYWORDS]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    seen_links: set[str] = set()
    all_news: list[RealEstateNews] = []

    for result in results:
        if isinstance(result, Exception):
            logger.warning("부동산 뉴스 수집 실패: %s", result)
            continue
        for article in result:
            if article.link not in seen_links:
                seen_links.add(article.link)
                all_news.append(
                    RealEstateNews(
                        title=article.title,
                        summary=article.description,
                        link=article.link,
                        pub_date=article.pub_date,
                    )
                )

    return all_news[:15]


# ── 청약Home API ──


async def _fetch_apt_list(
    client: httpx.AsyncClient,
    house_secd: str,
) -> list[dict]:
    """청약Home API에서 APT 분양 공고 목록을 조회한다."""
    params = {
        "page": 1,
        "perPage": 100,
        "serviceKey": get_settings().applyhome_api_key,
    }

    try:
        resp = await client.get(
            f"{APPLYHOME_BASE_URL}/getAPTLttotPblancDetail",
            params=params,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", [])
    except httpx.HTTPStatusError as e:
        logger.warning("청약Home API HTTP 에러 (HOUSE_SECD=%s): %d", house_secd, e.response.status_code)
        return []
    except httpx.RequestError as e:
        logger.warning("청약Home API 네트워크 에러 (HOUSE_SECD=%s): %s", house_secd, e)
        return []


def _parse_date(date_str: str | None) -> str:
    """API 날짜 문자열을 YYYY-MM-DD 형식으로 정규화한다."""
    if not date_str:
        return ""
    # API가 YYYY-MM-DD 또는 YYYYMMDD 형식으로 내려올 수 있음
    cleaned = date_str.strip().replace(".", "-").replace("/", "-")
    if len(cleaned) == 8 and cleaned.isdigit():
        return f"{cleaned[:4]}-{cleaned[4:6]}-{cleaned[6:8]}"
    return cleaned


def _is_within_range(date_str: str, start: date, end: date) -> bool:
    """날짜 문자열이 범위 내에 있는지 확인한다."""
    if not date_str:
        return False
    try:
        d = date.fromisoformat(date_str)
        return start <= d <= end
    except ValueError:
        return False


def _classify_status(receipt_start: str, receipt_end: str, today: date) -> str | None:
    """접수 시작/종료일 기준으로 상태를 분류한다."""
    try:
        start = date.fromisoformat(receipt_start)
        end = date.fromisoformat(receipt_end)
    except ValueError:
        return None

    if start <= today <= end:
        return "접수중"
    elif today < start <= today + timedelta(days=14):
        return "접수예정"
    return None


async def fetch_subscriptions() -> list[SubscriptionInfo]:
    """청약Home API에서 수도권 접수중/접수예정 청약을 조회한다."""
    today = date.today()

    from app.core.http import get_http_client
    client = get_http_client()
    tasks = [_fetch_apt_list(client, secd) for secd in HOUSE_SECD_MAP]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    subscriptions: list[SubscriptionInfo] = []
    seen: set[str] = set()

    for house_secd, result in zip(HOUSE_SECD_MAP, results):
        if isinstance(result, Exception):
            logger.warning("청약 목록 조회 실패 (HOUSE_SECD=%s): %s", house_secd, result)
            continue

        for item in result:
            manage_no = str(item.get("HOUSE_MANAGE_NO", ""))
            if not manage_no or manage_no in seen:
                continue

            area = item.get("SUBSCRPT_AREA_CODE_NM", "")
            if area not in METRO_AREA_CODES:
                continue

            receipt_start = _parse_date(item.get("RCEPT_BGNDE"))
            receipt_end = _parse_date(item.get("RCEPT_ENDDE"))
            status = _classify_status(receipt_start, receipt_end, today)
            if not status:
                continue

            seen.add(manage_no)
            subscriptions.append(
                SubscriptionInfo(
                    house_manage_no=manage_no,
                    pblanc_no=str(item.get("PBLANC_NO", "")),
                    house_name=item.get("HOUSE_NM", ""),
                    area=area,
                    address=item.get("HSSPLY_ADRES", ""),
                    house_type=HOUSE_SECD_MAP.get(house_secd, house_secd),
                    total_supply_count=int(item.get("TOT_SUPLY_HSHLDCO", 0)),
                    status=status,
                    receipt_start=receipt_start,
                    receipt_end=receipt_end,
                    winner_announce=_parse_date(item.get("PRZWNER_PRESNATN_DE")),
                    detail_url=item.get("PBLANC_URL", ""),
                )
            )

    return subscriptions


async def fetch_subscription_prices(
    house_manage_no: str,
    pblanc_no: str,
) -> list[SubscriptionPrice]:
    """청약Home API에서 분양가 상세를 조회한다."""
    params = {
        "page": 1,
        "perPage": 100,
        "cond[HOUSE_MANAGE_NO::EQ]": house_manage_no,
        "cond[PBLANC_NO::EQ]": pblanc_no,
        "serviceKey": get_settings().applyhome_api_key,
    }

    try:
        client = get_http_client()
        resp = await client.get(
            f"{APPLYHOME_BASE_URL}/getAPTLttotPblancMdl",
            params=params,
        )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as e:
        logger.warning("분양가 조회 HTTP 에러 (manage_no=%s): %d", house_manage_no, e.response.status_code)
        return []
    except httpx.RequestError as e:
        logger.warning("분양가 조회 네트워크 에러 (manage_no=%s): %s", house_manage_no, e)
        return []

    prices: list[SubscriptionPrice] = []
    for item in data.get("data", []):
        top_amount = item.get("LTTOT_TOP_AMOUNT")
        if top_amount is None:
            continue
        prices.append(
            SubscriptionPrice(
                house_manage_no=house_manage_no,
                house_type_area=item.get("HOUSE_TY", ""),
                supply_area=float(item.get("SUPLY_AR", 0)),
                supply_count=int(item.get("SUPLY_HSHLDCO", 0)),
                top_amount=int(top_amount),
            )
        )

    return prices


async def fetch_all_subscription_data() -> tuple[list[SubscriptionInfo], dict[str, list[SubscriptionPrice]]]:
    """청약 목록 조회 → 각 청약별 분양가 병렬 조회."""
    subscriptions = await fetch_subscriptions()
    logger.info("청약 %d건 조회 완료", len(subscriptions))

    if not subscriptions:
        return subscriptions, {}

    # 각 청약별 분양가 병렬 조회
    tasks = [
        fetch_subscription_prices(s.house_manage_no, s.pblanc_no)
        for s in subscriptions
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    prices: dict[str, list[SubscriptionPrice]] = {}
    for sub, result in zip(subscriptions, results):
        if isinstance(result, Exception):
            logger.warning("분양가 조회 실패 (%s): %s", sub.house_name, result)
            continue
        if result:
            prices[sub.house_manage_no] = result

    logger.info("분양가 조회 완료: %d건 중 %d건 성공", len(subscriptions), len(prices))
    return subscriptions, prices

"""DART 공시 수집기 - 전일 주요 공시를 수집한다."""

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, timedelta

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

DART_LIST_URL = "https://opendart.fss.or.kr/api/list.json"

# 수집 대상 공시 유형: 정기(A), 주요사항(B), 발행(C), 지분(D)
DISCLOSURE_TYPES = ["A", "B", "C", "D"]


@dataclass(frozen=True)
class Disclosure:
    """공시 DTO."""

    corp_name: str
    report_nm: str
    rcept_dt: str
    rcept_no: str
    flr_nm: str


async def _fetch_by_type(
    client: httpx.AsyncClient,
    base_params: dict,
    pblntf_ty: str,
) -> list[dict]:
    """단일 공시 유형을 조회한다."""
    params = {**base_params, "pblntf_ty": pblntf_ty}
    try:
        resp = await client.get(DART_LIST_URL, params=params)
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as e:
        logger.warning("DART API HTTP 에러 (type=%s): %d", pblntf_ty, e.response.status_code)
        return []
    except httpx.RequestError as e:
        logger.warning("DART API 네트워크 에러 (type=%s): %s", pblntf_ty, e)
        return []

    if data.get("status") == "000" and data.get("list"):
        return data["list"]
    return []

async def fetch_disclosures(target_date: date | None = None) -> list[Disclosure]:
    """전일(또는 지정일) 주요 공시 목록을 가져온다."""
    if target_date is None:
        target_date = date.today() - timedelta(days=1)

    date_str = target_date.strftime("%Y%m%d")
    base_params = {
        "crtfc_key": settings.dart_api_key,
        "bgn_de": date_str,
        "end_de": date_str,
        "page_count": 30,
    }

    async with httpx.AsyncClient(timeout=15) as client:
        # 4개 카테고리 동시 호출 — 스프링 WebFlux의 Mono.zip()과 동일
        results = await asyncio.gather(
            *[_fetch_by_type(client, base_params, ty) for ty in DISCLOSURE_TYPES],
            return_exceptions=True,
        )

    # 결과 병합 (예외가 섞여 있을 수 있으므로 필터링)
    all_disclosures: list[dict] = []
    for result in results:
        if isinstance(result, list):
            all_disclosures.extend(result)
        elif isinstance(result, Exception):
            logger.error("DART 병렬 호출 중 예외: %s", result)

    # 중복 제거 (rcept_no 기준)
    seen: set[str] = set()
    unique: list[Disclosure] = []
    for d in all_disclosures:
        rcept_no = d.get("rcept_no", "")
        if rcept_no not in seen:
            seen.add(rcept_no)
            unique.append(Disclosure(
                corp_name=d.get("corp_name", ""),
                report_nm=d.get("report_nm", ""),
                rcept_dt=d.get("rcept_dt", ""),
                rcept_no=rcept_no,
                flr_nm=d.get("flr_nm", ""),
            ))

    return unique[:20]

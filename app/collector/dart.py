"""DART 공시 수집기 - 전일 주요 공시를 수집한다."""

from datetime import date, timedelta

import httpx

from app.config import settings

DART_LIST_URL = "https://opendart.fss.or.kr/api/list.json"


async def fetch_disclosures(target_date: date | None = None) -> list[dict]:
    """전일(또는 지정일) 주요 공시 목록을 가져온다.

    Returns:
        [{"corp_name": "삼성전자", "report_nm": "주요사항보고서", "rcept_dt": "20250209", ...}, ...]
    """
    if target_date is None:
        target_date = date.today() - timedelta(days=1)

    date_str = target_date.strftime("%Y%m%d")

    params = {
        "crtfc_key": settings.dart_api_key,
        "bgn_de": date_str,
        "end_de": date_str,
        "page_count": 30,
        "type_detail": "A",  # 정기공시: A, 주요사항: B, 발행공시: C, 지분공시: D, 기타: E, 외부감사: F, 펀드: G, 자산유동화: H, 거래소: I, 공정위: J
    }

    async with httpx.AsyncClient(timeout=15) as client:
        # 여러 카테고리의 공시를 수집
        all_disclosures = []
        for pblntf_ty in ["A", "B", "C", "D"]:
            params["pblntf_ty"] = pblntf_ty
            resp = await client.get(DART_LIST_URL, params=params)
            data = resp.json()
            if data.get("status") == "000" and data.get("list"):
                all_disclosures.extend(data["list"])

    # 중복 제거 (rcept_no 기준)
    seen = set()
    unique = []
    for d in all_disclosures:
        if d["rcept_no"] not in seen:
            seen.add(d["rcept_no"])
            unique.append({
                "corp_name": d.get("corp_name", ""),
                "report_nm": d.get("report_nm", ""),
                "rcept_dt": d.get("rcept_dt", ""),
                "rcept_no": d.get("rcept_no", ""),
                "flr_nm": d.get("flr_nm", ""),  # 공시 제출인
            })

    return unique[:20]  # 최대 20건

"""시장 데이터 수집기 - 네이버 금융 API로 코스피/코스닥 지수 및 주요 종목 데이터를 수집한다."""

import httpx

NAVER_STOCK_API = "https://m.stock.naver.com/api"
HEADERS = {"User-Agent": "Mozilla/5.0"}


async def fetch_market_summary() -> dict:
    """시장 요약 데이터를 가져온다."""
    result = {}

    async with httpx.AsyncClient(timeout=15, headers=HEADERS) as client:
        # 코스피/코스닥 지수
        for code, name in [("KOSPI", "kospi"), ("KOSDAQ", "kosdaq")]:
            try:
                resp = await client.get(f"{NAVER_STOCK_API}/index/{code}/basic")
                if resp.status_code == 200:
                    data = resp.json()
                    result[name] = {
                        "name": data.get("stockName", code),
                        "close": data.get("closePrice", ""),
                        "change": data.get("compareToPreviousClosePrice", ""),
                        "change_pct": data.get("fluctuationsRatio", ""),
                        "direction": data.get("compareToPreviousPrice", {}).get("text", ""),
                    }
                    result["date"] = data.get("localTradedAt", "")[:10]
            except Exception:
                result[name] = None

        # 코스피 시총 TOP10
        try:
            resp = await client.get(f"{NAVER_STOCK_API}/stocks/marketValue", params={"market": "KOSPI", "page": 1, "pageSize": 10})
            if resp.status_code == 200:
                result["kospi_top10"] = _parse_stocks(resp.json())
        except Exception:
            result["kospi_top10"] = []

        # 급등 상위 5 (간단히)
        try:
            resp = await client.get(f"{NAVER_STOCK_API}/stocks/up", params={"market": "KOSPI", "page": 1, "pageSize": 5})
            if resp.status_code == 200:
                result["top_rising"] = _parse_stocks(resp.json())
        except Exception:
            result["top_rising"] = []

        # 급락 상위 5 (간단히)
        try:
            resp = await client.get(f"{NAVER_STOCK_API}/stocks/down", params={"market": "KOSPI", "page": 1, "pageSize": 5})
            if resp.status_code == 200:
                result["top_falling"] = _parse_stocks(resp.json())
        except Exception:
            result["top_falling"] = []

    return result


def _parse_stocks(data: dict) -> list[dict]:
    """네이버 금융 API 응답에서 종목 리스트를 파싱한다."""
    return [
        {
            "name": s.get("stockName", ""),
            "close": s.get("closePrice", ""),
            "change_pct": s.get("fluctuationsRatio", ""),
            "direction": s.get("compareToPreviousPrice", {}).get("text", ""),
            "volume": s.get("accumulatedTradingVolume", ""),
        }
        for s in data.get("stocks", [])
    ]

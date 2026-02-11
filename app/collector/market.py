"""시장 데이터 수집기 - 네이버 금융 API로 코스피/코스닥 지수 및 주요 종목 데이터를 수집한다."""

import httpx

NAVER_STOCK_API = "https://m.stock.naver.com/api"
NAVER_POLLING_API = "https://polling.finance.naver.com/api/realtime/domestic/stock"
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

        # 코스피 시총 TOP10 (종목코드 수집 → polling API로 시간외 반영 가격)
        try:
            resp = await client.get(
                f"{NAVER_STOCK_API}/stocks/marketValue",
                params={"market": "KOSPI", "page": 1, "pageSize": 10},
            )
            if resp.status_code == 200:
                stocks = resp.json().get("stocks", [])
                top10 = []
                for s in stocks:
                    item_code = s.get("itemCode", "")
                    stock_data = await _fetch_stock_with_afterhours(client, item_code)
                    if stock_data:
                        top10.append(stock_data)
                    else:
                        # polling 실패 시 기본 데이터 사용
                        top10.append({
                            "name": s.get("stockName", ""),
                            "close": s.get("closePrice", ""),
                            "change_pct": s.get("fluctuationsRatio", ""),
                            "direction": s.get("compareToPreviousPrice", {}).get("text", ""),
                            "volume": s.get("accumulatedTradingVolume", ""),
                        })
                result["kospi_top10"] = top10
        except Exception:
            result["kospi_top10"] = []

        # 투자자별 매매동향 (외인/기관/개인)
        for code, name in [("KOSPI", "kospi"), ("KOSDAQ", "kosdaq")]:
            try:
                resp = await client.get(f"{NAVER_STOCK_API}/index/{code}/trend")
                if resp.status_code == 200:
                    data = resp.json()
                    result[f"{name}_investor"] = {
                        "personal": data.get("personalValue", ""),
                        "foreign": data.get("foreignValue", ""),
                        "institutional": data.get("institutionalValue", ""),
                    }
            except Exception:
                result[f"{name}_investor"] = None

    return result


async def _fetch_stock_with_afterhours(client: httpx.AsyncClient, item_code: str) -> dict | None:
    """polling API로 시간외 반영 가격을 가져온다. 시간외 데이터가 있으면 시간외 가격 사용."""
    try:
        resp = await client.get(f"{NAVER_POLLING_API}/{item_code}")
        if resp.status_code != 200:
            return None

        d = resp.json()["datas"][0]
        over = d.get("overMarketPriceInfo") or {}

        # 시간외 데이터가 있으면 시간외 가격/등락률 사용
        if over.get("overPrice"):
            return {
                "name": d.get("stockName", ""),
                "close": over["overPrice"],
                "change_pct": over.get("fluctuationsRatio", d.get("fluctuationsRatio", "")),
                "direction": over.get("compareToPreviousPrice", {}).get("text",
                             d.get("compareToPreviousPrice", {}).get("text", "")),
                "volume": d.get("accumulatedTradingVolume", ""),
            }

        # 시간외 없으면 정규장 데이터
        return {
            "name": d.get("stockName", ""),
            "close": d.get("closePrice", ""),
            "change_pct": d.get("fluctuationsRatio", ""),
            "direction": d.get("compareToPreviousPrice", {}).get("text", ""),
            "volume": d.get("accumulatedTradingVolume", ""),
        }
    except Exception:
        return None

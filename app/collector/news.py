"""뉴스 수집기 - 네이버 뉴스 검색 API로 주요 경제/주식 뉴스를 수집한다."""

import logging
import re
from dataclasses import dataclass

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

NAVER_SEARCH_URL = "https://openapi.naver.com/v1/search/news.json"


@dataclass(frozen=True)
class NewsArticle:
    """뉴스 기사 DTO — 자바의 record와 동일한 불변 객체."""

    title: str
    description: str
    link: str
    pub_date: str


def _strip_html(text: str) -> str:
    """HTML 태그 제거."""
    return re.sub(r"<[^>]+>", "", text).replace("&quot;", '"').replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")


async def fetch_news(query: str = "주식 증시", count: int = 5) -> list[NewsArticle]:
    """네이버 뉴스 검색으로 최신 뉴스를 가져온다."""
    headers = {
        "X-Naver-Client-Id": settings.naver_client_id,
        "X-Naver-Client-Secret": settings.naver_client_secret,
    }
    params = {
        "query": query,
        "display": count,
        "sort": "date",
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(NAVER_SEARCH_URL, headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as e:
        logger.warning("뉴스 API HTTP 에러 (query=%s): %d", query, e.response.status_code)
        return []
    except httpx.RequestError as e:
        logger.warning("뉴스 API 네트워크 에러 (query=%s): %s", query, e)
        return []

    return [
        NewsArticle(
            title=_strip_html(item["title"]),
            description=_strip_html(item["description"]),
            link=item["originallink"],
            pub_date=item["pubDate"],
        )
        for item in data.get("items", [])
    ]


async def fetch_stock_news() -> list[NewsArticle]:
    """주식/경제 관련 뉴스를 여러 키워드로 수집한다."""
    queries = ["코스피 증시", "주식시장 전망", "경제 금리"]
    all_news: list[NewsArticle] = []
    seen_titles: set[str] = set()

    for query in queries:
        news = await fetch_news(query=query, count=5)
        for article in news:
            if article.title not in seen_titles:
                seen_titles.add(article.title)
                all_news.append(article)

    return all_news[:10]


async def fetch_news_for_stocks(stock_names: list[str]) -> dict[str, list[NewsArticle]]:
    """개별 종목별 뉴스를 수집한다. {종목명: [뉴스]} 형태로 반환."""
    result: dict[str, list[NewsArticle]] = {}
    for name in stock_names:
        news = await fetch_news(query=f"{name} 주가", count=3)
        if news:
            result[name] = news
    return result

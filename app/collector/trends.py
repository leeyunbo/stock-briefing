"""트렌드 키워드 수집 — 투자 특화 소스.

소스:
1. Google Trends RSS (한국)
2. 네이버 증권 뉴스 제목 (인기 키워드는 AI가 추출)
3. 구글 서제스트 (투자 시드 키워드 기반 연관 검색어)
"""

import logging
import re

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


# ── Google Trends RSS ──


async def fetch_google_trends_kr() -> list[str]:
    """구글 트렌드 한국 급상승 검색어를 수집한다."""
    keywords: list[str] = []

    try:
        async with httpx.AsyncClient(timeout=15, headers={"User-Agent": _UA}) as client:
            resp = await client.get(
                "https://trends.google.co.kr/trending/rss?geo=KR"
            )
            if resp.status_code != 200:
                logger.warning("Google Trends RSS 실패: status=%s", resp.status_code)
                return []

        titles = re.findall(
            r'<title>(?:<!\[CDATA\[)?(.+?)(?:\]\]>)?</title>',
            resp.text,
        )
        for title in titles[1:]:
            kw = title.strip()
            if kw and len(kw) < 50 and kw not in keywords:
                keywords.append(kw)

        logger.info("Google Trends 수집: %d건", len(keywords))
    except Exception as e:
        logger.error("Google Trends 수집 오류: %s", e)

    return keywords


# ── 네이버 증권 뉴스 제목 수집 ──


async def fetch_naver_finance_headlines() -> list[str]:
    """네이버 뉴스 검색으로 투자 관련 최신 뉴스 제목을 수집한다.

    키워드 추출은 하지 않고, 뉴스 제목 원본을 반환.
    AI 필터가 제목에서 투자 키워드를 추출한다.
    """
    settings = get_settings()
    headers = {
        "X-Naver-Client-Id": settings.naver_client_id,
        "X-Naver-Client-Secret": settings.naver_client_secret,
    }

    queries = [
        "테마주 관련주",
        "목표주가",
        "실적 서프라이즈",
        "배당주",
        "공모주 IPO",
        "주가 급등",
        "주가 전망",
        "ETF 추천",
    ]

    titles: list[str] = []
    seen: set[str] = set()

    from datetime import datetime, timedelta
    cutoff = datetime.now() - timedelta(days=7)

    try:
        async with httpx.AsyncClient(timeout=15, headers=headers) as client:
            for query in queries:
                resp = await client.get(
                    "https://openapi.naver.com/v1/search/news.json",
                    params={"query": query, "display": 10, "sort": "date"},
                )
                if resp.status_code != 200:
                    continue
                for item in resp.json().get("items", []):
                    # 3일 이내 뉴스만
                    pub_date = item.get("pubDate", "")
                    if pub_date:
                        try:
                            from email.utils import parsedate_to_datetime
                            dt = parsedate_to_datetime(pub_date)
                            if dt.replace(tzinfo=None) < cutoff:
                                continue
                        except (ValueError, TypeError):
                            pass
                    title = re.sub(r'<[^>]+>', '', item.get("title", "")).strip()
                    if title and title not in seen:
                        seen.add(title)
                        titles.append(title)
    except Exception as e:
        logger.error("네이버 뉴스 수집 오류: %s", e)

    logger.info("네이버 뉴스 제목 수집: %d건", len(titles))
    return titles


# ── 구글 서제스트 (자동완성) ──


async def fetch_google_suggest(seeds: list[str] | None = None) -> list[str]:
    """구글 자동완성 API로 투자 관련 연관 검색어를 수집한다."""
    if seeds is None:
        seeds = [
            "주식 전망", "ETF 추천", "배당주 추천",
            "테마주", "관련주 2026", "목표주가",
            "주가 전망 2026", "실적 분석",
        ]

    keywords: list[str] = []
    seen: set[str] = set()

    try:
        async with httpx.AsyncClient(
            timeout=10,
            headers={"User-Agent": _UA},
        ) as client:
            for seed in seeds:
                resp = await client.get(
                    "https://suggestqueries.google.com/complete/search",
                    params={"client": "firefox", "q": seed, "hl": "ko"},
                )
                if resp.status_code != 200:
                    continue
                try:
                    data = resp.json()
                    suggestions = data[1] if len(data) > 1 else []
                    for s in suggestions:
                        kw = s.strip()
                        if kw and kw != seed and kw not in seen:
                            seen.add(kw)
                            keywords.append(kw)
                except (ValueError, IndexError):
                    continue
    except Exception as e:
        logger.error("구글 서제스트 오류: %s", e)

    logger.info("구글 서제스트 수집: %d건", len(keywords))
    return keywords


# ── 통합 수집 ──


async def collect_all_trends() -> tuple[list[str], list[str]]:
    """모든 소스에서 수집한다.

    Returns:
        (키워드 리스트, 뉴스 제목 리스트)
        키워드는 트렌드+서제스트에서, 뉴스 제목은 별도로 반환하여
        AI 필터에서 함께 처리한다.
    """
    google_trends = await fetch_google_trends_kr()
    naver_headlines = await fetch_naver_finance_headlines()
    suggest_kws = await fetch_google_suggest()

    # 트렌드 + 서제스트 합치기 (중복 제거)
    seen: set[str] = set()
    keywords: list[str] = []
    for kw in google_trends + suggest_kws:
        if kw not in seen:
            seen.add(kw)
            keywords.append(kw)

    logger.info(
        "트렌드 수집 완료: keywords=%d (Trends=%d, Suggest=%d), headlines=%d",
        len(keywords), len(google_trends), len(suggest_kws), len(naver_headlines),
    )
    return keywords, naver_headlines

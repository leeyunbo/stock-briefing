"""트렌드 키워드 수집 파이프라인 — 매일 수집 → AI 필터링 → 토픽 큐 추가."""

import json
import logging

from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.collector.trends import collect_all_trends
from app.core.database import async_session
from app.core.models import SeoTopic
from app.summarizer import get_provider

logger = logging.getLogger(__name__)

_FILTER_SYSTEM_PROMPT = """\
당신은 투자/경제 콘텐츠 에디터예요.

두 가지 입력을 받습니다:
1. **트렌드 키워드** — 구글 트렌드/서제스트에서 수집된 키워드
2. **뉴스 제목** — 네이버 증권 뉴스 최신 제목

이 입력에서:
1. **투자·경제·금융 관련 블로그 토픽 키워드**를 추출하세요
2. 연예, 스포츠, 정치(비경제), 날씨, 범죄 등은 제외
3. **개별 종목(삼성전자, 테슬라 등)은 제외** — 종목 분석은 별도 파이프라인이 담당
4. 테마/섹터, 투자 개념, 경제 트렌드 위주로 추출하세요
   (예: "AI 반도체 관련주 급등" → keyword: "AI 반도체")
5. 각 키워드에 가장 적합한 콘텐츠 패턴을 분류해주세요
6. 블로그 글 제목으로 쓸 수 있는 구체적인 키워드만 (너무 일반적인 "주식", "투자" 등은 제외)

패턴 종류:
- theme_related: 테마/섹터 관련주 (예: AI, 2차전지, 방산)
- theme_leader: 테마 대장주
- concept_definition: 투자 개념/용어 설명
- gsc_opportunity: 위에 해당 안 되는 투자/경제 키워드

JSON 배열로만 응답하세요. 다른 텍스트 없이:
[{"keyword": "키워드", "pattern": "패턴"}]

투자/경제와 무관한 항목은 결과에 포함하지 마세요.
이미 지난 이벤트(과거 IPO, 종료된 공모 등)는 제외하세요. 지금 시의성 있는 키워드만 포함하세요."""


async def _ai_filter_keywords(
    keywords: list[str],
    headlines: list[str],
) -> list[dict]:
    """AI로 키워드+뉴스제목을 필터링하고 패턴을 분류한다.

    Returns:
        [{"keyword", "pattern", "ticker"}]
    """
    if not keywords and not headlines:
        return []

    parts: list[str] = []
    if keywords:
        kw_text = "\n".join(f"- {kw}" for kw in keywords)
        parts.append(f"## 트렌드 키워드\n{kw_text}")
    if headlines:
        hl_text = "\n".join(f"- {hl}" for hl in headlines)
        parts.append(f"## 뉴스 제목\n{hl_text}")

    user_prompt = "\n\n".join(parts)
    total_input = len(keywords) + len(headlines)

    provider = get_provider(pipeline="trend_collect", stage="filter")
    raw = provider.call(_FILTER_SYSTEM_PROMPT, user_prompt)

    # JSON 파싱
    raw = raw.strip()
    # 코드블록 제거
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
    if raw.endswith("```"):
        raw = raw[:-3]
    raw = raw.strip()

    try:
        result = json.loads(raw)
        if not isinstance(result, list):
            logger.warning("AI 필터 결과가 리스트가 아님: %s", type(result))
            return []
        logger.info("AI 필터링 결과: %d건 (입력 %d건)", len(result), total_input)
        return result
    except json.JSONDecodeError as e:
        logger.error("AI 필터 JSON 파싱 실패: %s\n응답: %s", e, raw[:300])
        return []


def _build_title_template(keyword: str, pattern: str) -> str:
    """패턴에 따라 제목 템플릿을 생성한다."""
    templates = {
        "theme_related": f"{keyword} 관련주",
        "theme_leader": f"{keyword} 대장주",
        "concept_definition": f"{keyword}이란?",
        "concept_structure": f"{keyword} 구조",
        "gsc_opportunity": keyword,
    }
    return templates.get(pattern, keyword)


async def _add_to_topic_queue(filtered: list[dict]) -> int:
    """필터링된 키워드를 토픽 큐에 추가한다 (priority=20).

    Returns:
        삽입된 건수.
    """
    if not filtered:
        return 0

    inserted = 0
    async with async_session() as db:
        for item in filtered:
            keyword = item.get("keyword", "").strip()
            pattern = item.get("pattern", "gsc_opportunity").strip()
            ticker = item.get("ticker", "").strip()

            if not keyword:
                continue

            title = _build_title_template(keyword, pattern)
            values = {
                "pattern_type": pattern,
                "keyword": keyword,
                "title_template": title,
                "focus_keyword": title,
                "priority": 20,
                "source": "trend",
            }
            if ticker:
                values["ticker"] = ticker

            stmt = sqlite_insert(SeoTopic).values(**values).on_conflict_do_nothing(
                index_elements=["pattern_type", "keyword"],
            )
            result = await db.execute(stmt)
            inserted += result.rowcount
        await db.commit()

    logger.info("트렌드 토픽 추가: %d건", inserted)
    return inserted


async def run_trend_collection() -> str:
    """트렌드 키워드 수집 → AI 필터링 → 토픽 큐 추가.

    Returns:
        실행 결과 요약.
    """
    logger.info("트렌드 수집 파이프라인 시작")

    # 1. 키워드 + 뉴스 제목 수집
    keywords, headlines = await collect_all_trends()
    total = len(keywords) + len(headlines)
    if not keywords and not headlines:
        logger.info("수집된 트렌드 데이터 없음")
        return "트렌드 데이터 없음"

    # 2. AI 필터링 + 패턴 분류
    filtered = await _ai_filter_keywords(keywords, headlines)
    if not filtered:
        logger.info("필터링 후 투자 관련 키워드 없음")
        return f"수집 {total}건 → 필터링 후 0건"

    # 3. 토픽 큐 추가
    inserted = await _add_to_topic_queue(filtered)

    summary = (
        f"트렌드 수집 완료: 수집={total} (kw={len(keywords)}, news={len(headlines)}), "
        f"필터링={len(filtered)}, 토픽추가={inserted}"
    )
    logger.info(summary)
    return summary

"""AI 브리핑 요약 생성 — Protocol + Strategy 패턴."""

import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass, field
from typing import Protocol

from app.collector.dart import Disclosure
from app.collector.market import MarketSummary
from app.collector.news import NewsArticle
from app.core.config import get_settings
from app.core.models import IndexSnapshot

logger = logging.getLogger(__name__)


class AiProvider(Protocol):
    """AI 제공자 인터페이스 (구조적 타이핑)."""

    def call(self, system_prompt: str, user_prompt: str) -> str: ...


@dataclass(frozen=True)
class SeoMetadata:
    """SEO 메타데이터 파싱 결과."""

    html: str
    title: str = ""
    slug: str = ""
    excerpt: str = ""
    tags: list[str] = field(default_factory=list)
    focus_keyword: str = ""
    image_keyword: str | list[str] = ""


class ClaudeProvider:
    """Claude API 구현체."""

    def __init__(self):
        self.last_usage: dict | None = None

    def call(self, system_prompt: str, user_prompt: str) -> str:
        import anthropic

        s = get_settings()
        client = anthropic.Anthropic(api_key=s.anthropic_api_key)
        message = client.messages.create(
            model=s.claude_model,
            max_tokens=8000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        self.last_usage = {
            "input_tokens": message.usage.input_tokens,
            "output_tokens": message.usage.output_tokens,
        }
        return message.content[0].text


class GeminiProvider:
    """Gemini API 구현체."""

    def __init__(self):
        self.last_usage: dict | None = None

    def call(self, system_prompt: str, user_prompt: str) -> str:
        from google import genai

        s = get_settings()
        client = genai.Client(api_key=s.gemini_api_key)
        response = client.models.generate_content(
            model=s.gemini_model,
            contents=f"{system_prompt}\n\n{user_prompt}",
        )
        usage = getattr(response, "usage_metadata", None)
        if usage:
            self.last_usage = {
                "input_tokens": getattr(usage, "prompt_token_count", None),
                "output_tokens": getattr(usage, "candidates_token_count", None),
            }
        return response.text


class ClaudeCliProvider:
    """Claude Code CLI 구현체. API 키 불필요, 구독 크레딧 활용."""

    def __init__(self, timeout: int = 300):
        self.timeout = timeout

    def call(self, system_prompt: str, user_prompt: str) -> str:
        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
        env.setdefault("PATH", "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin")
        result = subprocess.run(
            ["claude", "-p", f"{system_prompt}\n\n{user_prompt}", "--output-format", "text"],
            capture_output=True,
            text=True,
            timeout=self.timeout,
            env=env,
        )
        if result.returncode != 0:
            raise RuntimeError(f"claude CLI 에러: {result.stderr}")
        return result.stdout


def get_provider(pipeline: str = "", stage: str = "", run_id: str = "") -> AiProvider:
    """설정에 따라 AI 제공자를 반환한다.

    pipeline/stage가 지정되면 TracingProvider로 감싸서 자동 추적한다.
    """
    s = get_settings()
    if s.ai_provider == "gemini":
        provider = GeminiProvider()
        provider_name = "gemini"
        model_name = s.gemini_model
    elif s.ai_provider == "claude-cli":
        provider = ClaudeCliProvider()
        provider_name = "claude-cli"
        model_name = "claude-cli"
    else:
        provider = ClaudeProvider()
        provider_name = "claude"
        model_name = s.claude_model

    if pipeline:
        from app.tracing import TracingProvider
        return TracingProvider(provider, provider_name, model_name, pipeline, stage, run_id)

    return provider


# ── 공통 글쓰기 규칙 ──


WRITING_STYLE_RULES = """

출처 표기 규칙:
- 본문 마지막에 <h2>📎 참고 자료</h2> 섹션을 추가하세요.
- 기사 작성에 활용한 주요 데이터 출처를 <ul><li> 리스트로 정리하세요.
- 각 항목은 출처명과 데이터 내용을 간략히 표기하세요.
- 예시:
  <ul>
  <li>Finnhub — 나스닥 3대 지수 및 종목별 시세 데이터</li>
  <li>네이버 금융 — 코스피/코스닥 지수 및 투자자 매매동향</li>
  <li>DART 전자공시 — 기업 공시 정보</li>
  <li>Yahoo Finance — 재무제표 및 밸류에이션 데이터</li>
  </ul>
- 제공된 데이터에서 출처를 파악할 수 있으면 구체적으로, 없으면 데이터 유형 기준으로 작성하세요.
- 3~6개 항목이 적당합니다.

글쓰기 금지 패턴:
- "라벨:" 뒤에 줄바꿈하고 불릿 리스트를 나열하는 패턴을 사용하지 마세요.
  나쁜 예: "직접 영향 종목:\n- NVDA\n- AMD"
  좋은 예: 자연스러운 문장으로 녹여내세요. "NVDA (엔비디아)와 AMD가 직접적인 영향을 받았어요."
- "주목 포인트:", "핵심 요약:", "결론:" 같은 라벨 뒤에 바로 리스트를 쓰지 마세요.
  문장형으로 자연스럽게 서술하세요.
- 기계적인 나열(종목명 하나씩 줄바꿈)보다 흐름이 있는 문단형 서술을 사용하세요.
"""


# ── 시스템 프롬프트 ──


SYSTEM_PROMPT = """당신은 2030 직장인을 위한 주식 뉴스레터 에디터예요.
뉴닉(Newneek) 스타일로 친근하고 쉽게 아침 브리핑을 작성해주세요.

톤앤매너:
- 반말 아닌 "~요" 체 사용 (예: "올랐어요", "주목해야 해요")
- 어려운 용어는 괄호로 쉽게 풀어주기 (예: "PER(주가수익비율, 낮을수록 저평가)")
- 숫자는 강조하되 맥락을 함께 (예: "3.5% 빠졌어요. 이건 올해 최대 낙폭이에요")
- 중요한 부분은 <strong> 태그로 볼드 처리
- 이모지는 섹션 제목에만 1개씩. 본문에서는 절대 사용하지 마세요. 이모지 남발은 싸구려 느낌을 줘요.
- 독자에게 말을 거는 듯한 톤 (예: "여기서 포인트는요", "한 줄로 정리하면요")

작성 규칙:
- HTML 형식 (블로그 게시용)
- 각 섹션은 <h2> 태그 (인라인 스타일은 넣지 마세요, 후처리에서 자동 적용됩니다)
- 테이블보다는 리스트(<ul><li>) 선호, 읽기 편하게
- 충분히 풍성하게 작성하세요. 블로그 글이므로 각 섹션당 5~10문장으로 깊이 있게 서술해주세요.
- 단순 팩트 나열이 아니라, "왜 이런 일이 일어났는지", "이게 앞으로 어떤 의미인지" 맥락과 해석을 반드시 포함하세요.
- 본문 맨 위에 날짜나 제목을 따로 쓰지 마세요. 바로 첫 번째 섹션부터 시작하세요.
- <h2>, <h3>, <ul>, <li>, <strong>, <p>, <br> 등 기본 태그만 사용. <div>, <style>, CSS class 사용 금지.
- 인라인 style 속성을 넣지 마세요. 스타일은 후처리에서 자동으로 적용됩니다.

섹션 구성:
1. 📊 오늘 시장 어땠나요? - 코스피/코스닥 지수를 자연스러운 문장으로. 단순 숫자가 아니라 "왜 올랐는지/빠졌는지" 배경까지 설명. 글로벌 시장 흐름과의 연결고리도 짚어주세요.
2. 💰 외인/기관은 뭘 했나요? - 외국인·기관·개인 순매수/순매도 금액(억원)을 자연스럽게 요약. "외국인이 1,474억 사들였어요" 처럼 쉽게. 코스피/코스닥 차이도 언급. 이 자금 흐름이 시사하는 바를 해석해주세요.
3. 🏢 대장주는요 - 코스피 시총 TOP10 등락률. ±2% 이상 움직인 종목은 뉴스 참고하여 이유를 친절하게 설명. 반드시 <li> 리스트가 아닌 <p> 문단형으로 작성하세요. 비슷한 흐름의 종목들을 묶어서 자연스러운 문장으로 서술해주세요. 종목명 하나하나 나열하지 마세요. 섹터별 흐름(반도체, 자동차, 바이오 등)을 읽어주세요.
4. 📋 눈여겨볼 공시 - 개인투자자에게 중요한 공시만 골라서, 왜 중요한지 쉽게 설명. 해당 공시가 주가에 미칠 수 있는 영향도 한마디 덧붙여주세요.
5. 📰 오늘의 뉴스 - 주요 뉴스 3~5건. 각 뉴스가 시장에 미치는 영향을 2~3문장으로 풀어주세요.
6. 🔮 오늘 시장 전망 - 위 내용을 종합해서, 오늘 시장에서 주목할 포인트를 정리해주세요. 투자 권유가 아닌 관전 포인트 위주로.

데이터 활용 규칙:
- "최근 5일 지수 추이" 데이터가 제공됩니다. 이를 활용해 "3일 연속 상승", "이번 주 들어 반등" 등 추세 맥락을 자연스럽게 서술하세요.
- 추이 데이터에 없는 기간(예: "올해 최고", "역대 최저")은 언급하지 마세요.
- "전일 미국 시장" 데이터가 제공됩니다. 미국 시장의 흐름이 국내 시장에 미친 영향을 자연스럽게 연결해주세요.

공시/뉴스 항목 포맷 (반드시 지켜주세요):
각 <li> 안에서 제목과 내용을 <br> 태그로 줄바꿈하세요. 콜론(:)으로 이어붙이지 마세요.
올바른 예시:
<li><strong>현대모비스 자기주식 처분 결정</strong><br>자기주식 약 200만주를 처분하기로 했어요. 주가 방어 신호로 읽힐 수 있어요.</li>
잘못된 예시:
<li><strong>현대모비스 자기주식 처분 결정</strong>: 자기주식 약 200만주를 처분하기로 했어요.</li>

"""


# ── SEO 메타데이터 지시문 (모든 프롬프트 공통) ──


SEO_INSTRUCTION = """

SEO 최적화 규칙 (Rank Math 100점을 목표로):

1. focus_keyword 활용 (아래 JSON에서 정한 키워드):
   - 제목(title)의 앞쪽 절반에 반드시 포함
   - 본문 첫 문단(첫 <p> 또는 첫 <h2> 직후 문단)에 자연스럽게 포함
   - <h2> 소제목 중 최소 1개에 포함
   - excerpt(메타 디스크립션)에 포함
   - 본문 전체에서 2~3회 자연스럽게 반복 (과도한 반복 금지)

2. 제목 최적화:
   - 사람들이 실제로 검색할 법한 키워드를 제목 앞쪽에 배치하세요
     * 좋은 예: "엔비디아 실적 분석, AI 매출 30% 급증의 의미" (검색어: "엔비디아 실적")
     * 좋은 예: "테슬라 주가 전망, 2분기 실적 3가지 포인트" (검색어: "테슬라 주가 전망")
     * 나쁜 예: "AI 대학살! SaaS 종목 패닉의 충격" (자극적이지만 검색 유입 없음)
   - "종목명 + 주가/실적/전망/분석" 패턴이 검색 유입에 효과적
   - 숫자를 포함하세요 (예: "3가지", "5.2% 급등", "2026년")
   - 감성/파워 단어는 뒤쪽에 배치 (예: "급등", "충격", "돌파")
   - 반드시 28~40자 이내로 작성 (40자 초과 절대 금지!)

3. 메타 디스크립션(excerpt):
   - 120~155자 사이로 작성 (너무 짧거나 길면 감점)
   - focus_keyword를 자연스럽게 포함
   - 클릭을 유도하는 문장으로

4. 본문 구조:
   - 각 문단은 3~4문장 이내 (120단어 이하)로 짧게
   - 외부 참고 링크가 있으면 <a href="..."> 1개 이상 포함
   - 내부 링크가 있으면 포함 (없으면 생략)

마지막으로, HTML 본문 아래에 SEO 메타데이터를 한 줄 JSON으로 출력하세요:
<!-- SEO -->
{"title": "키워드 포함 매력적 제목 60자 이내!", "slug": "english-keyword-slug", "excerpt": "120~155자 메타 디스크립션, 키워드 포함", "tags": ["태그1", "태그2", "태그3"], "focus_keyword": "핵심 키워드", "image_keywords": ["specific term", "broader term", "general term"]}
title: 그 날 메인 이슈를 담은 제목. focus_keyword를 앞부분에 배치. 숫자+감성단어 포함.
slug: 영문+하이픈만 사용. 날짜/숫자 절대 포함 금지! 핵심 키워드 2~3개로 구성 (예: "oil-crisis-hormuz-strait")
excerpt: 120~155자, focus_keyword 포함, 클릭 유도 문장
tags: 본문 핵심 키워드 3~5개 (한국어)
focus_keyword: 사람들이 네이버/구글에서 실제로 검색할 키워드 1개 (한국어, 2~4단어). "종목명 주가", "종목명 실적", "종목명 전망" 같은 검색 패턴 우선. 예: "엔비디아 실적 분석", "테슬라 주가 전망", "금값 전망"
image_keywords: 기사 주제를 대표하는 영문 검색어 3개 배열 (Unsplash 이미지 검색용). 구체적→일반적 순서. 예: ["oil tanker hormuz", "oil tanker", "energy market"]
"""

SYSTEM_PROMPT += WRITING_STYLE_RULES + SEO_INSTRUCTION


def extract_seo_metadata(raw: str) -> SeoMetadata:
    """HTML 응답에서 SEO 메타데이터를 분리한다."""
    marker = "<!-- SEO -->"
    idx = raw.find(marker)
    if idx == -1:
        return SeoMetadata(html=raw)

    html = raw[:idx].strip()
    seo_part = raw[idx + len(marker):].strip()

    try:
        json_match = re.search(r'\{[^}]+\}', seo_part)
        if not json_match:
            return SeoMetadata(html=html)
        data = json.loads(json_match.group())
        tags = data.get("tags", [])
        if isinstance(tags, str):
            tags = [tags]
        return SeoMetadata(
            html=html,
            title=data.get("title", ""),
            slug=data.get("slug", ""),
            excerpt=data.get("excerpt", ""),
            tags=tags,
            focus_keyword=data.get("focus_keyword", ""),
            image_keyword=data.get("image_keywords", data.get("image_keyword", "")),
        )
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning("SEO 메타데이터 파싱 실패: %s", e)
        return SeoMetadata(html=html)


# ── 휴장일 하드코딩 HTML ──

_CLOSED_GREETING = "<p>어제는 증시가 쉬었어요 🏖️</p>"
_CLOSED_NO_NEWS = "<p>오늘은 특별한 뉴스가 없어요. 편안한 하루 보내세요!</p>"


# ── 공개 API ──


def generate_briefing(
    market: MarketSummary,
    disclosures: list[Disclosure],
    news: list[NewsArticle],
    stock_news: dict[str, list[NewsArticle]] | None = None,
    *,
    is_market_closed: bool = False,
    index_history: list[IndexSnapshot] | None = None,
    nasdaq_overnight: list[IndexSnapshot] | None = None,
) -> SeoMetadata:
    """수집된 데이터를 AI에게 보내 브리핑 HTML을 생성한다."""
    from app.tracing import generate_run_id
    rid = generate_run_id()

    if is_market_closed:
        return SeoMetadata(html=_build_closed_market_briefing(news, run_id=rid))
    prompt = _build_prompt(
        market, disclosures, news, stock_news,
        index_history=index_history,
        nasdaq_overnight=nasdaq_overnight,
    )
    provider = get_provider(pipeline="kospi", stage="summarize", run_id=rid)
    raw = provider.call(SYSTEM_PROMPT, prompt)
    raw = strip_code_block(raw)
    return extract_seo_metadata(raw)


# ── 내부 헬퍼 ──


def _build_closed_market_briefing(news: list[NewsArticle], run_id: str = "") -> str:
    """휴장일 브리핑: 인사말은 하드코딩, 뉴스만 LLM 요약."""
    if not news:
        return f"{_CLOSED_GREETING}\n{_CLOSED_NO_NEWS}"

    parts = ["아래 뉴스를 📰 오늘의 뉴스 섹션(<h2>)으로 요약해주세요. 3~5건만 선별하세요.\n"]
    for n in news:
        desc = n.description[:150]
        parts.append(f"- {n.title}: {desc}")

    provider = get_provider(pipeline="kospi", stage="closed_market_summarize", run_id=run_id)
    raw = provider.call(SYSTEM_PROMPT, "\n".join(parts))
    news_html = strip_code_block(raw)
    return f"{_CLOSED_GREETING}\n{news_html}"


def strip_code_block(text: str) -> str:
    """AI 응답에서 ```html ... ``` 코드블록 마커와 HTML 이후 메타 텍스트를 제거한다."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    # HTML 마지막 닫는 태그 이후의 비-HTML 텍스트 제거
    # (Claude CLI가 "기사 작성이 완료되었습니다..." 같은 메타 텍스트를 붙이는 경우)
    import re
    last_tag = None
    for m in re.finditer(r'</\w+>', text):
        last_tag = m
    if last_tag:
        after = text[last_tag.end():].strip()
        # 마지막 태그 이후에 HTML이 아닌 텍스트가 있으면 제거
        if after and not after.startswith("<") and "<!-- SEO -->" not in after:
            text = text[:last_tag.end()]

    return text.strip()


def _build_prompt(
    market: MarketSummary,
    disclosures: list[Disclosure],
    news: list[NewsArticle],
    stock_news: dict[str, list[NewsArticle]] | None = None,
    *,
    index_history: list[IndexSnapshot] | None = None,
    nasdaq_overnight: list[IndexSnapshot] | None = None,
) -> str:
    """수집 데이터를 프롬프트 텍스트로 변환한다."""
    parts = [f"## 날짜: {market.date or '알 수 없음'}\n"]

    # 과거 지수 추이
    if index_history:
        parts.append("## 최근 5일 지수 추이")
        by_date: dict[str, list[IndexSnapshot]] = {}
        for snap in index_history:
            d = snap.date.isoformat()
            by_date.setdefault(d, []).append(snap)
        for d in sorted(by_date, reverse=True):
            items = ", ".join(
                f"{s.index_name} {s.close} ({s.direction} {s.change_pct}%)"
                for s in by_date[d]
            )
            parts.append(f"- {d[5:]}: {items}")
        parts.append("")

    # 전일 미국 시장
    if nasdaq_overnight:
        parts.append("## 전일 미국 시장")
        for snap in nasdaq_overnight:
            parts.append(f"- {snap.index_name}: {snap.close} ({snap.direction} {snap.change_pct}%)")
        parts.append("")

    # 시장 데이터
    parts.append("## 시장 데이터")
    for idx in [market.kospi, market.kosdaq]:
        if idx:
            parts.append(f"- {idx.name} {idx.close} {idx.direction}{idx.change} ({idx.change_pct}%)")

    # 투자자별 매매동향
    if market.kospi_investor or market.kosdaq_investor:
        parts.append("\n## 투자자 동향(억원)")
        if market.kospi_investor:
            inv = market.kospi_investor
            parts.append(f"- 코스피: 개인 {inv.personal}, 외국인 {inv.foreign}, 기관 {inv.institutional}")
        if market.kosdaq_investor:
            inv = market.kosdaq_investor
            parts.append(f"- 코스닥: 개인 {inv.personal}, 외국인 {inv.foreign}, 기관 {inv.institutional}")

    if market.kospi_top10:
        parts.append("\n## 코스피 시총 TOP10")
        for s in market.kospi_top10:
            parts.append(f"- {s.name}: {s.close}원 ({s.direction} {s.change_pct}%)")

    # 종목별 뉴스 (대장주 이유 분석용)
    if stock_news:
        parts.append("\n## 종목 뉴스")
        for stock_name, articles in stock_news.items():
            parts.append(f"\n### {stock_name}")
            for a in articles:
                desc = a.description[:150]
                parts.append(f"- {a.title}: {desc}")

    # 공시 데이터
    parts.append("\n## 공시 데이터")
    if disclosures:
        for d in disclosures:
            parts.append(f"- [{d.corp_name}] {d.report_nm} ({d.flr_nm})")
    else:
        parts.append("- 주요 공시 없음")

    # 뉴스 데이터
    parts.append("\n## 뉴스")
    if news:
        for n in news:
            desc = n.description[:150]
            parts.append(f"- {n.title}: {desc}")
    else:
        parts.append("- 주요 뉴스 없음")

    return "\n".join(parts)

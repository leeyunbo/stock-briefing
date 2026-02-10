"""AI 브리핑 요약 생성 - Claude / Gemini 전환 가능."""

from app.config import AI_PROVIDER, ANTHROPIC_API_KEY, GEMINI_API_KEY

SYSTEM_PROMPT = """당신은 개인투자자를 위한 주식 시장 브리핑 전문가입니다.
아래 데이터를 바탕으로 바쁜 직장인이 출근 전 3분 안에 읽을 수 있는 간결한 아침 브리핑을 작성하세요.

규칙:
- 핵심만 간결하게 (불필요한 인사말/마무리 없이)
- 숫자와 팩트 중심
- HTML 형식으로 작성 (이메일 발송용)
- 각 섹션은 <h2> 태그 사용
- 깔끔한 테이블이나 리스트 형태로 정리

섹션 구성:
1. 📊 시장 요약 - 코스피/코스닥 지수 동향
2. 🏢 코스피 TOP10 - 시총 상위 10종목 테이블 (종목명, 종가, 등락률). 등락률이 ±2% 이상이면 종목 뉴스 데이터를 참고하여 이유를 반드시 한 줄로 설명.
3. 📈 급등/급락 - 상승/하락 상위 5종목을 간단히 이름과 등락률만 나열 (한 줄씩)
4. 📋 주요 공시 - 중요한 공시는 왜 중요한지 한 줄 코멘트
5. 📰 오늘의 뉴스 - 주요 경제/주식 뉴스 요약
"""


def _call_claude(prompt: str) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    message = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=3000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def _call_gemini(prompt: str) -> str:
    from google import genai
    client = genai.Client(api_key=GEMINI_API_KEY)
    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=f"{SYSTEM_PROMPT}\n\n{prompt}",
    )
    return response.text


def generate_briefing(
    market_data: dict,
    disclosures: list[dict],
    news: list[dict],
    stock_news: dict[str, list[dict]] | None = None,
) -> str:
    """수집된 데이터를 AI에게 보내 브리핑 HTML을 생성한다."""
    prompt = _build_prompt(market_data, disclosures, news, stock_news)

    if AI_PROVIDER == "gemini":
        return _call_gemini(prompt)
    return _call_claude(prompt)


def _build_prompt(
    market_data: dict,
    disclosures: list[dict],
    news: list[dict],
    stock_news: dict[str, list[dict]] | None = None,
) -> str:
    """수집 데이터를 프롬프트 텍스트로 변환한다."""
    parts = [f"## 날짜: {market_data.get('date', '알 수 없음')}\n"]

    # 시장 데이터
    parts.append("## 시장 데이터")
    for index_name in ["kospi", "kosdaq"]:
        idx = market_data.get(index_name)
        if idx:
            parts.append(f"- {idx['name']}: 종가 {idx['close']}, 전일대비 {idx['change']} ({idx['direction']}), 등락률 {idx['change_pct']}%")

    kospi_top = market_data.get("kospi_top10", [])
    if kospi_top:
        parts.append("\n## 코스피 시총 TOP10")
        for s in kospi_top:
            parts.append(f"- {s['name']}: {s['close']}원 ({s['direction']} {s['change_pct']}%)")

    top_rising = market_data.get("top_rising", [])
    if top_rising:
        parts.append("\n## 급등 상위 (간단히)")
        for s in top_rising:
            parts.append(f"- {s['name']}: {s['change_pct']}%")

    top_falling = market_data.get("top_falling", [])
    if top_falling:
        parts.append("\n## 급락 상위 (간단히)")
        for s in top_falling:
            parts.append(f"- {s['name']}: {s['change_pct']}%")

    # 종목별 뉴스 (급등/급락 이유 분석용)
    if stock_news:
        parts.append("\n## 종목별 관련 뉴스 (급등/급락 이유 분석에 활용)")
        for stock_name, articles in stock_news.items():
            parts.append(f"\n### {stock_name}")
            for a in articles:
                parts.append(f"- {a['title']}: {a['description']}")

    # 공시 데이터
    parts.append("\n## 공시 데이터")
    if disclosures:
        for d in disclosures:
            parts.append(f"- [{d['corp_name']}] {d['report_nm']} (제출인: {d['flr_nm']})")
    else:
        parts.append("- 주요 공시 없음")

    # 뉴스 데이터
    parts.append("\n## 뉴스 데이터")
    if news:
        for n in news:
            parts.append(f"- {n['title']}: {n['description']}")
    else:
        parts.append("- 주요 뉴스 없음")

    return "\n".join(parts)

"""AI 브리핑 요약 생성 - Claude / Gemini 전환 가능."""

from app.collector.news import NewsArticle
from app.config import settings

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
- HTML 형식 (이메일 발송용)
- 각 섹션은 <h2> 태그 (인라인 스타일은 넣지 마세요, 후처리에서 자동 적용됩니다)
- 테이블보다는 리스트(<ul><li>) 선호, 읽기 편하게
- 핵심만 간결하게, 한 섹션당 3~5문장 이내
- "왜 중요한지" 맥락을 반드시 포함
- 본문 맨 위에 날짜나 제목을 따로 쓰지 마세요. 이메일 헤더에 이미 있어요. 바로 첫 번째 섹션부터 시작하세요.
- <h2>, <ul>, <li>, <strong>, <p>, <br> 등 기본 태그만 사용. <div>, <style>, CSS class 사용 금지.
- 인라인 style 속성을 넣지 마세요. 스타일은 후처리에서 자동으로 적용됩니다.

섹션 구성:
1. 📊 어제 시장 어땠나요? - 코스피/코스닥 지수를 자연스러운 문장으로. 한 줄 요약 포함.
2. 💰 외인/기관은 뭘 했나요? - 외국인·기관·개인 순매수/순매도 금액(억원)을 자연스럽게 요약. "외국인이 1,474억 사들였어요" 처럼 쉽게. 코스피/코스닥 차이도 언급.
3. 🏢 대장주는요 - 코스피 시총 TOP10 등락률. ±2% 이상 움직인 종목은 뉴스 참고하여 이유를 친절하게 설명. 반드시 <li> 리스트가 아닌 <p> 문단형으로 작성하세요. 비슷한 흐름의 종목들을 묶어서 자연스러운 문장으로 서술해주세요. 종목명 하나하나 나열하지 마세요.
4. 📋 눈여겨볼 공시 - 개인투자자에게 중요한 공시만 골라서, 왜 중요한지 쉽게 설명.
5. 📰 오늘의 뉴스 - 주요 뉴스 3~5건.

공시/뉴스 항목 포맷 (반드시 지켜주세요):
각 <li> 안에서 제목과 내용을 <br> 태그로 줄바꿈하세요. 콜론(:)으로 이어붙이지 마세요.
올바른 예시:
<li><strong>현대모비스 자기주식 처분 결정</strong><br>자기주식 약 200만주를 처분하기로 했어요. 주가 방어 신호로 읽힐 수 있어요.</li>
잘못된 예시:
<li><strong>현대모비스 자기주식 처분 결정</strong>: 자기주식 약 200만주를 처분하기로 했어요.</li>
"""


def _call_claude(prompt: str) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    message = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=3000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def _call_gemini(prompt: str) -> str:
    from google import genai
    client = genai.Client(api_key=settings.gemini_api_key)
    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=f"{SYSTEM_PROMPT}\n\n{prompt}",
    )
    return response.text


def _strip_code_block(text: str) -> str:
    """AI 응답에서 ```html ... ``` 코드블록 마커를 제거한다."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def generate_briefing(
    market_data: dict,
    disclosures: list[dict],
    news: list[NewsArticle],
    stock_news: dict[str, list[NewsArticle]] | None = None,
) -> str:
    """수집된 데이터를 AI에게 보내 브리핑 HTML을 생성한다."""
    prompt = _build_prompt(market_data, disclosures, news, stock_news)

    if settings.ai_provider == "gemini":
        return _strip_code_block(_call_gemini(prompt))
    return _strip_code_block(_call_claude(prompt))


def _build_prompt(
    market_data: dict,
    disclosures: list[dict],
    news: list[NewsArticle],
    stock_news: dict[str, list[NewsArticle]] | None = None,
) -> str:
    """수집 데이터를 프롬프트 텍스트로 변환한다."""
    parts = [f"## 날짜: {market_data.get('date', '알 수 없음')}\n"]

    # 시장 데이터
    parts.append("## 시장 데이터")
    for index_name in ["kospi", "kosdaq"]:
        idx = market_data.get(index_name)
        if idx:
            parts.append(f"- {idx['name']}: 종가 {idx['close']}, 전일대비 {idx['change']} ({idx['direction']}), 등락률 {idx['change_pct']}%")

    # 투자자별 매매동향
    kospi_inv = market_data.get("kospi_investor")
    kosdaq_inv = market_data.get("kosdaq_investor")
    if kospi_inv or kosdaq_inv:
        parts.append("\n## 투자자별 매매동향 (단위: 억원)")
        if kospi_inv:
            parts.append(f"- 코스피: 개인 {kospi_inv['personal']}, 외국인 {kospi_inv['foreign']}, 기관 {kospi_inv['institutional']}")
        if kosdaq_inv:
            parts.append(f"- 코스닥: 개인 {kosdaq_inv['personal']}, 외국인 {kosdaq_inv['foreign']}, 기관 {kosdaq_inv['institutional']}")

    kospi_top = market_data.get("kospi_top10", [])
    if kospi_top:
        parts.append("\n## 코스피 시총 TOP10")
        for s in kospi_top:
            parts.append(f"- {s['name']}: {s['close']}원 ({s['direction']} {s['change_pct']}%)")

    # 종목별 뉴스 (대장주 이유 분석용)
    if stock_news:
        parts.append("\n## 종목별 관련 뉴스 (급등/급락 이유 분석에 활용)")
        for stock_name, articles in stock_news.items():
            parts.append(f"\n### {stock_name}")
            for a in articles:
                parts.append(f"- {a.title}: {a.description}")

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
            parts.append(f"- {n.title}: {n.description}")
    else:
        parts.append("- 주요 뉴스 없음")

    return "\n".join(parts)

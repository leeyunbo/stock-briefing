"""콘텐츠 검수 — 팩트체크(WebSearch) + 출처 섹션 + 톤 일관성."""

import json
import logging
import os
import re
import subprocess
import time

from app.core.config import get_settings
from app.summarizer import strip_code_block
from app.tracing import _save_trace_sync

logger = logging.getLogger(__name__)

REVIEW_SYSTEM_PROMPT = """당신은 금융 콘텐츠 에디터 겸 팩트체커예요.
아래 기사를 검수하고, 문제가 있으면 직접 수정한 전체 HTML을 반환하세요.

## 검수 항목

### 1. 팩트 오류 검증
- 본문에서 핵심 수치(주가, 등락률, 시가총액, PER 등), 날짜, 이벤트를 추출하세요.
- 반드시 웹 검색으로 각 수치/사실을 검증하세요. 검색 없이 넘어가지 마세요.
- 틀린 부분은 올바른 수치로 수정하세요.
- 미발표 실적을 발표된 것처럼 쓴 경우, "발표 예정" 또는 "컨센서스 추정치"로 수정하세요.
- 과거 이벤트를 "예정"이라고 쓴 경우 수정하세요.
- 투자 판단(매수/관망/매도)과 수치가 모순되는지 확인하세요. 예: 목표주가가 현재가보다 낮은데 "매수" 판단이면, 판단을 수치에 맞게 수정하거나, 그에 따른 확실한 이유를 덧붙이세요.

### 2. 출처 섹션 확인
- 본문 마지막에 <h2>📎 참고 자료</h2> 섹션이 있는지 확인하세요.
- 없으면 본문 끝에 추가하세요. 기사에서 활용한 데이터 출처를 3~6개 <ul><li> 형태로 정리하세요.
- 이미 있으면 그대로 두세요.

### 3. 톤 일관성
- "~요" 체가 일관되게 사용되는지 확인하세요. 반말이나 "~습니다" 체가 섞여 있으면 "~요" 체로 통일하세요.
- 투자 권유성 표현("꼭 매수하세요", "지금이 기회", "목표가 XX원")이 있으면 중립적 톤으로 수정하세요.

## 출력 규칙 (매우 중요!)
- 최종 응답에는 수정된 HTML만 출력하세요. 분석 과정, 검수 결과 설명, 코멘트 등을 절대 포함하지 마세요.
- 수정할 것이 없으면 원본 HTML을 그대로 출력하세요.
- HTML 태그 구조를 변경하지 마세요. 텍스트 내용만 수정하세요.
- <figure>, <img>, 차트 관련 태그는 절대 수정하지 마세요.
- "검수를 진행하겠습니다", "확인하겠습니다" 같은 메타 코멘트를 절대 출력하지 마세요.
- HTML 출력 후, 맨 마지막 줄에 아래 형식만 덧붙이세요:

<!-- REVIEW -->
{"corrections": 수정_건수, "details": ["수정1 요약", "수정2 요약"]}
"""


def run_review(html: str, run_id: str = "", pipeline: str = "") -> str:
    """기사 HTML을 검수하고 수정된 HTML을 반환한다."""
    logger.info("[검수] 시작: pipeline=%s, run_id=%s", pipeline, run_id)

    prompt = f"{REVIEW_SYSTEM_PROMPT}\n\n다음 기사를 검수해주세요:\n\n{html}"

    start = time.monotonic()
    input_tokens = None
    output_tokens = None
    success = True
    error_message = None
    reviewed_html = ""

    try:
        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
        env.setdefault("PATH", "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin")
        result = subprocess.run(
            ["claude", "-p", prompt, "--output-format", "json", "--allowedTools", "mcp__claude_ai__web_search,WebSearch,web_search"],
            capture_output=True,
            text=True,
            timeout=600,
            env=env,
        )
        if result.returncode != 0:
            raise RuntimeError(f"claude CLI 에러: {result.stderr}")

        data = json.loads(result.stdout)
        usage = data.get("usage", {})
        input_tokens = usage.get("input_tokens")
        output_tokens = usage.get("output_tokens")
        reviewed_html = data.get("result", "")
    except Exception as e:
        success = False
        error_message = str(e)[:1000]
        raise
    finally:
        latency_ms = int((time.monotonic() - start) * 1000)
        _save_trace_sync(
            run_id=run_id,
            pipeline=pipeline,
            stage="review",
            provider_name="claude-cli",
            model_name="claude-cli",
            system_prompt=REVIEW_SYSTEM_PROMPT,
            user_prompt=f"기사 검수 ({len(html)}자)",
            response=reviewed_html,
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            success=success,
            error_message=error_message,
        )

    reviewed_html = strip_code_block(reviewed_html)

    # HTML 태그 시작 전의 메타 코멘트 제거
    html_start = re.search(r'<(?:h[1-6]|p|div|ul|ol|section|article|figure|table)', reviewed_html)
    if html_start and html_start.start() > 0:
        reviewed_html = reviewed_html[html_start.start():]

    # 검수 결과 로깅
    review_marker = "<!-- REVIEW -->"
    idx = reviewed_html.find(review_marker)
    if idx != -1:
        review_json_str = reviewed_html[idx + len(review_marker):].strip()
        reviewed_html = reviewed_html[:idx].strip()
        try:
            review_data = json.loads(re.search(r'\{[^}]+\}', review_json_str).group())
            corrections = review_data.get("corrections", 0)
            details = review_data.get("details", [])
            if corrections > 0:
                logger.info("[검수] %d건 수정: %s", corrections, "; ".join(details))
            else:
                logger.info("[검수] 수정 없음 — 통과")
        except (json.JSONDecodeError, AttributeError):
            logger.warning("[검수] 검수 결과 JSON 파싱 실패")
    else:
        logger.info("[검수] 검수 완료 (결과 마커 없음)")

    # 빈 응답 방어
    if not reviewed_html.strip():
        logger.warning("[검수] 빈 응답 — 원본 유지")
        return html

    return reviewed_html

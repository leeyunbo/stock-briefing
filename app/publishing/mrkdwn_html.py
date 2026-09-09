"""Slack mrkdwn → 이메일용 HTML 최소 변환기.

지원: *굵게*, _기울임_, 불릿(• 또는 - ), 단독 === 줄 → <hr>, 빈 줄 → 문단 분리, 줄바꿈 → <br>.
그 외 문법(링크·코드)은 현재 프롬프트 출력에 나오지 않아 미지원.
"""

from __future__ import annotations

import html
import re

_BOLD = re.compile(r"(?<![\w*])\*(?=\S)(.+?)(?<=\S)\*(?![\w*])")
_ITALIC = re.compile(r"(?<![\w_])_(?=\S)(.+?)(?<=\S)_(?![\w_])")
_BULLET = re.compile(r"^\s*(?:•|-|\*)\s+(.*)$")


def _inline(text: str) -> str:
    text = html.escape(text, quote=False)
    text = _BOLD.sub(r"<strong>\1</strong>", text)
    text = _ITALIC.sub(r"<em>\1</em>", text)
    return text


def mrkdwn_to_html(text: str) -> str:
    """mrkdwn 문자열을 <p>/<ul>/<hr> 조합의 HTML로 바꾼다."""
    out: list[str] = []
    para: list[str] = []
    items: list[str] = []

    def flush_para() -> None:
        if para:
            out.append("<p>" + "<br>".join(para) + "</p>")
            para.clear()

    def flush_items() -> None:
        if items:
            out.append("<ul>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>")
            items.clear()

    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            flush_para()
            flush_items()
            continue
        if line.strip() == "===":
            flush_para()
            flush_items()
            out.append("<hr>")
            continue
        m = _BULLET.match(line)
        if m:
            flush_para()
            items.append(_inline(m.group(1)))
            continue
        flush_items()
        para.append(_inline(line.strip()))

    flush_para()
    flush_items()
    return "".join(out)

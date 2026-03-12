"""FAQ 스키마 마크업 — HTML에서 FAQ 추출 → JSON-LD 삽입."""

import json
import logging
import re

logger = logging.getLogger(__name__)


def extract_faq_from_html(html: str) -> list[dict]:
    """HTML 본문에서 <h3>Q. ...?</h3><p>...</p> 패턴의 FAQ를 추출한다.

    Returns:
        [{"question": "...", "answer": "..."}]
    """
    # h3 Q. 질문 → 다음 p 태그까지 매칭
    pattern = re.compile(
        r'<h3>\s*Q\.\s*(.+?)\s*</h3>\s*<p>(.*?)</p>',
        re.DOTALL | re.IGNORECASE,
    )
    faqs = []
    for match in pattern.finditer(html):
        question = re.sub(r'<[^>]+>', '', match.group(1)).strip()
        answer = re.sub(r'<[^>]+>', '', match.group(2)).strip()
        if question and answer:
            faqs.append({"question": question, "answer": answer})

    return faqs


def build_faq_jsonld(faqs: list[dict]) -> str:
    """FAQ 리스트로 JSON-LD 스크립트 태그를 생성한다.

    Returns:
        <script type="application/ld+json">...</script> 문자열.
        FAQ가 없으면 빈 문자열.
    """
    if not faqs:
        return ""

    schema = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": faq["question"],
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": faq["answer"],
                },
            }
            for faq in faqs
        ],
    }

    json_str = json.dumps(schema, ensure_ascii=False, indent=2)
    return f'\n<script type="application/ld+json">\n{json_str}\n</script>'


def inject_faq_schema(html: str) -> str:
    """HTML 본문에서 FAQ를 추출하고 JSON-LD 스키마를 본문 끝에 삽입한다.

    Returns:
        JSON-LD가 삽입된 HTML. FAQ가 없으면 원본 그대로 반환.
    """
    faqs = extract_faq_from_html(html)
    if not faqs:
        logger.info("FAQ 섹션 없음 — 스키마 삽입 건너뜀")
        return html

    jsonld = build_faq_jsonld(faqs)
    logger.info("FAQ 스키마 삽입: %d개 Q&A", len(faqs))
    return html + jsonld


def extract_faq_schema_json(html: str) -> str:
    """HTML에서 FAQ를 추출하여 Rank Math용 JSON-LD 문자열을 반환한다.

    WordPress WAF가 <script> 태그를 차단하므로,
    FAQ 스키마는 Rank Math post meta로 전달한다.

    Returns:
        JSON-LD 문자열 (script 태그 없이). FAQ가 없으면 빈 문자열.
    """
    faqs = extract_faq_from_html(html)
    if not faqs:
        return ""

    schema = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": faq["question"],
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": faq["answer"],
                },
            }
            for faq in faqs
        ],
    }
    logger.info("FAQ 스키마 추출: %d개 Q&A", len(faqs))
    return json.dumps(schema, ensure_ascii=False)

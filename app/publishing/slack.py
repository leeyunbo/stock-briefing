"""Slack 발행 — 개인 아침 브리핑.

bot token으로 메시지 전송 + 차트 이미지 업로드(files.upload v2).
incoming webhook이 아니라 chat.postMessage / files API를 쓴다.
"""

import logging
import re

from app.core.config import get_settings
from app.core.http import get_http_client

logger = logging.getLogger(__name__)

_SLACK_API = "https://slack.com/api"
_SECTION_MAX = 2900  # Slack section 블록 텍스트 한도(3000) 여유분


def _auth_header() -> dict:
    return {"Authorization": f"Bearer {get_settings().slack_bot_token}"}


def _chunk(text: str, size: int = _SECTION_MAX) -> list[str]:
    """문단 경계를 지키며 size 이하 청크로 나눈다."""
    chunks: list[str] = []
    buf = ""
    for para in text.split("\n\n"):
        candidate = f"{buf}\n\n{para}" if buf else para
        if len(candidate) <= size:
            buf = candidate
            continue
        if buf:
            chunks.append(buf)
        # 단일 문단이 size를 넘으면 강제 분할
        while len(para) > size:
            chunks.append(para[:size])
            para = para[size:]
        buf = para
    if buf:
        chunks.append(buf)
    return chunks


def _split_sections(text: str) -> list[str]:
    """=== 줄 기준으로 섹션을 나눈다. 없으면 빈 줄 2개 기준."""
    parts = re.split(r"\n\s*={3,}\s*\n", text)
    if len(parts) <= 1:
        parts = re.split(r"\n\s*\n", text)
    return [p.strip() for p in parts if p.strip()]


def _blocks_from_text(header: str, text: str) -> list[dict]:
    """헤더 + 섹션마다 divider로 끊어 시각적 경계를 만든다."""
    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": header[:150], "emoji": True}}
    ]
    for i, section in enumerate(_split_sections(text)):
        if i > 0:
            blocks.append({"type": "divider"})
        for chunk in _chunk(section):
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": chunk}})
    return blocks[:50]  # Slack 블록 50개 한도


async def _post_message(blocks: list[dict], fallback: str) -> bool:
    settings = get_settings()
    client = get_http_client()
    resp = await client.post(
        f"{_SLACK_API}/chat.postMessage",
        headers={**_auth_header(), "Content-Type": "application/json; charset=utf-8"},
        json={"channel": settings.slack_channel_id, "blocks": blocks, "text": fallback},
    )
    data = resp.json()
    if not data.get("ok"):
        logger.error("Slack 메시지 전송 실패: %s", data.get("error"))
        return False
    return True


async def _upload_image(png: bytes, filename: str, title: str, comment: str) -> bool:
    """files.upload v2: 업로드 URL 발급 → 바이트 전송 → 채널 게시."""
    settings = get_settings()
    client = get_http_client()

    r1 = await client.get(
        f"{_SLACK_API}/files.getUploadURLExternal",
        headers=_auth_header(),
        params={"filename": filename, "length": str(len(png))},
    )
    d1 = r1.json()
    if not d1.get("ok"):
        logger.error("Slack 업로드 URL 발급 실패: %s", d1.get("error"))
        return False

    r2 = await client.post(
        d1["upload_url"], content=png, headers={"Content-Type": "application/octet-stream"}
    )
    if r2.status_code != 200:
        logger.error("Slack 파일 업로드 실패: HTTP %s", r2.status_code)
        return False

    r3 = await client.post(
        f"{_SLACK_API}/files.completeUploadExternal",
        headers={**_auth_header(), "Content-Type": "application/json; charset=utf-8"},
        json={
            "files": [{"id": d1["file_id"], "title": title}],
            "channel_id": settings.slack_channel_id,
            "initial_comment": comment[:3000],
        },
    )
    d3 = r3.json()
    if not d3.get("ok"):
        logger.error("Slack 업로드 완료 실패: %s", d3.get("error"))
        return False
    return True


async def deliver_to_slack(
    header: str,
    overview_md: str,
    spotlights: list[tuple[bytes | None, str, str]],
) -> None:
    """개요 메시지 + 스포트라이트(분석 + 차트)를 순서대로 게시한다.

    spotlights: (차트 PNG | None, 종목 타이틀, 분석 mrkdwn) 리스트.
    """
    if not get_settings().slack_bot_token or not get_settings().slack_channel_id:
        logger.error("SLACK_BOT_TOKEN / SLACK_CHANNEL_ID 미설정 — 발송 건너뜀")
        return

    await _post_message(_blocks_from_text(header, overview_md), header)

    for png, title, analysis in spotlights:
        if png:
            await _upload_image(png, f"{title}.png", title, analysis)
        else:
            # 차트 실패 시 분석 텍스트만 발송
            await _post_message(
                [{"type": "section", "text": {"type": "mrkdwn", "text": analysis[:_SECTION_MAX]}}],
                title,
            )

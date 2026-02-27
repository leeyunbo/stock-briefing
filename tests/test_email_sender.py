"""이메일 발송기 테스트."""

from unittest.mock import patch, MagicMock

import pytest

from app.publishing.email_sender import send_email


@pytest.mark.asyncio
async def test_send_email_success():
    """정상 발송 시 True를 반환한다."""
    with patch("app.publishing.email_sender._send_smtp") as mock_smtp:
        result = await send_email("test@example.com", "제목", "<h2>내용</h2>")

    assert result is True
    mock_smtp.assert_called_once_with("test@example.com", "제목", "<h2>내용</h2>")


@pytest.mark.asyncio
async def test_send_email_failure():
    """SMTP 에러 시 False를 반환한다."""
    with patch("app.publishing.email_sender._send_smtp", side_effect=Exception("SMTP error")):
        result = await send_email("test@example.com", "제목", "<h2>내용</h2>")

    assert result is False

"""SMTP 이메일 발송기 — async + 재시도.

스프링 대응:
- asyncio.to_thread() = @Async (동기 코드를 별도 스레드에서 실행)
- tenacity.retry = @Retryable (자동 재시도 + 지수 백오프)
- asyncio.gather() = CompletableFuture.allOf() (동시 발송)
"""

import asyncio
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.config import settings

logger = logging.getLogger(__name__)


def _build_message(to_email: str, subject: str, html_body: str) -> MIMEMultipart:
    """이메일 MIME 메시지를 조립한다."""
    msg = MIMEMultipart("alternative")
    msg["From"] = settings.smtp_user
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    return msg


def _send_smtp(to_email: str, subject: str, html_body: str) -> None:
    """동기 SMTP 발송 (스레드풀에서 실행될 함수)."""
    msg = _build_message(to_email, subject, html_body)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
        server.starttls()
        server.login(settings.smtp_user, settings.smtp_password)
        server.sendmail(settings.smtp_user, to_email, msg.as_string())


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((
        smtplib.SMTPConnectError,
        smtplib.SMTPServerDisconnected,
    )),
    reraise=True,
)
async def send_email(to_email: str, subject: str, html_body: str) -> bool:
    """HTML 이메일을 비동기로 발송한다. SMTP 에러 시 최대 3회 재시도."""
    try:
        await asyncio.to_thread(_send_smtp, to_email, subject, html_body)
        return True
    except Exception as e:
        logger.error("이메일 발송 실패 (%s): %s", to_email, e)
        return False


async def send_briefing_to_subscribers(subscribers: list[str], subject: str, html_body: str) -> dict:
    """구독자 리스트에 브리핑 이메일을 동시 발송한다."""
    tasks = [send_email(email, subject, html_body) for email in subscribers]
    results_list = await asyncio.gather(*tasks)

    success = sum(1 for r in results_list if r)
    fail = len(results_list) - success
    return {"success": success, "fail": fail}

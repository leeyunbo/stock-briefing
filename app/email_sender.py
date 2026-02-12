"""SMTP 이메일 발송기."""

import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from app.config import settings

logger = logging.getLogger(__name__)


def send_email(to_email: str, subject: str, html_body: str) -> bool:
    """HTML 이메일을 발송한다."""
    msg = MIMEMultipart("alternative")
    msg["From"] = settings.smtp_user
    msg["To"] = to_email
    msg["Subject"] = subject

    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(settings.smtp_user, to_email, msg.as_string())
        return True
    except Exception as e:
        logger.error("이메일 발송 실패 (%s): %s", to_email, e)
        return False


def send_briefing_to_subscribers(subscribers: list[str], subject: str, html_body: str) -> dict:
    """구독자 리스트에 브리핑 이메일을 발송한다."""
    results = {"success": 0, "fail": 0}
    for email in subscribers:
        if send_email(email, subject, html_body):
            results["success"] += 1
        else:
            results["fail"] += 1
    return results

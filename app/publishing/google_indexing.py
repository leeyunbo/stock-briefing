"""Google Indexing API 자동 인덱싱 요청 모듈.

WordPress 발행 후 Google에 "이 URL 크롤링해줘"를 자동으로 요청한다.
서비스 계정 JSON 키 파일이 필요하다.
"""

import logging

import httpx
from google.auth.transport.requests import Request
from google.oauth2 import service_account

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/indexing"]
_ENDPOINT = "https://indexing.googleapis.com/v3/urlNotifications:publish"


async def request_indexing(url: str) -> bool:
    """Google Indexing API로 URL 인덱싱을 요청한다.

    서비스 계정이 설정되지 않으면 건너뛴다.
    실패해도 파이프라인은 중단하지 않는다.
    """
    if not get_settings().google_service_account_json:
        logger.info("Google 서비스 계정 미설정 — 인덱싱 요청 건너뜀")
        return False

    try:
        credentials = service_account.Credentials.from_service_account_file(
            get_settings().google_service_account_json,
            scopes=_SCOPES,
        )
        credentials.refresh(Request())

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                _ENDPOINT,
                headers={
                    "Authorization": f"Bearer {credentials.token}",
                    "Content-Type": "application/json",
                },
                json={"url": url, "type": "URL_UPDATED"},
            )

        if resp.status_code == 200:
            logger.info("Google 인덱싱 요청 완료: %s", url)
            return True

        logger.error(
            "Google 인덱싱 요청 실패: status=%s, body=%s",
            resp.status_code,
            resp.text[:300],
        )
        return False

    except Exception as e:
        logger.error("Google 인덱싱 요청 오류: %s", e)
        return False

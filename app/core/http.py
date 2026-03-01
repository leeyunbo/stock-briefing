"""공유 httpx 클라이언트 — 커넥션 재사용으로 성능 향상."""

import httpx

from app.core.config import get_settings

_client: httpx.AsyncClient | None = None


def get_http_client() -> httpx.AsyncClient:
    """모듈 레벨 AsyncClient를 반환한다 (lazy 초기화, 커넥션 풀 재사용)."""
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=get_settings().api_timeout)
    return _client


async def close_http_client() -> None:
    """앱 종료 시 클라이언트를 정리한다."""
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
        _client = None

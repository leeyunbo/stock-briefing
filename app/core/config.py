"""애플리케이션 설정 — pydantic-settings로 환경변수를 타입 안전하게 관리한다."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    # API Keys (필수 — 없으면 앱 시작 실패)
    dart_api_key: str
    anthropic_api_key: str
    gemini_api_key: str
    naver_client_id: str
    naver_client_secret: str

    # AI Provider
    ai_provider: Literal["claude", "gemini", "claude-cli"] = "claude"
    claude_model: str = "claude-sonnet-4-5-20250929"
    gemini_model: str = "gemini-2.0-flash"

    # SMTP
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str
    smtp_password: str

    # Nasdaq (Finnhub)
    finnhub_api_key: str
    nasdaq_watchlist: str = "AAPL,NVDA,MSFT,GOOGL,AMZN,META,TSLA,PLTR,CRM,SNOW,NOW,SMCI"

    # WordPress
    wp_url: str = ""
    wp_user: str = ""
    wp_app_password: str = ""

    # Google Indexing API (서비스 계정 JSON 경로)
    google_service_account_json: str = ""

    # 청약Home API (공공데이터포털)
    applyhome_api_key: str = ""

    # Unsplash
    unsplash_access_key: str = ""

    # News dedup
    news_dedup_threshold: float = 0.92
    news_dedup_ttl_days: int = 7

    # HTTP
    api_timeout: int = 15

    # Pagination
    archive_page_size: int = 10

    # OG Image
    og_font_path: str = "/System/Library/Fonts/AppleSDGothicNeo.ttc"

    # Upbit (코인 자동매매)
    upbit_access_key: str = ""
    upbit_secret_key: str = ""
    upbit_trading_enabled: bool = False  # True일 때만 실제 주문 실행
    upbit_initial_capital: int = 100_000  # 초기 자본금 (원)

    # Database
    database_url: str = "sqlite+aiosqlite:///briefing.db"


@lru_cache
def get_settings() -> Settings:
    """Settings 인스턴스를 반환한다 (테스트에서 cache_clear로 재생성 가능)."""
    return Settings()

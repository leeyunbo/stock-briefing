"""애플리케이션 설정 - pydantic-settings로 환경변수를 타입 안전하게 관리한다.

스프링의 @ConfigurationProperties + @Validated 와 동일한 역할:
- 환경변수 → 필드 자동 바인딩 (스프링의 relaxed binding과 유사)
- 기본값 없는 필드 = 필수값 → 앱 시작 시 ValidationError (스프링의 @NotNull)
- Literal 타입 = 허용값 제한 (스프링의 @Pattern 또는 enum 바인딩)
"""

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
    ai_provider: Literal["claude", "gemini"] = "claude"
    claude_model: str = "claude-sonnet-4-5-20250929"
    gemini_model: str = "gemini-2.0-flash"

    # SMTP
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587  # str→int 자동 변환 (스프링의 @Value 타입 변환)
    smtp_user: str
    smtp_password: str

    # Database
    database_url: str = "sqlite+aiosqlite:///briefing.db"


# 싱글턴 인스턴스 — 스프링의 @Bean과 유사
settings = Settings()

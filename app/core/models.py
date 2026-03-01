from datetime import UTC, date, datetime
from enum import StrEnum

from sqlalchemy import Date, Integer, String, Text, DateTime, Boolean, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class BriefingType(StrEnum):
    """브리핑 카테고리 — 파이프라인·발행·OG이미지 등에서 공유."""

    KOSPI = "kospi_briefing"
    NASDAQ = "nasdaq_briefing"
    NEWS_DIVE = "news_dive"
    REAL_ESTATE = "real_estate_briefing"


class Subscriber(Base):
    __tablename__ = "subscribers"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class Briefing(Base):
    __tablename__ = "briefings"
    __table_args__ = (
        UniqueConstraint("date", "briefing_type", name="uq_briefing_date_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    briefing_type: Mapped[str] = mapped_column(String(20), default="kr")
    title: Mapped[str] = mapped_column(String(200))
    content_html: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class IndexSnapshot(Base):
    """지수 스냅샷 — 매일 파이프라인 실행 시 당일 지수를 저장한다."""

    __tablename__ = "index_snapshots"
    __table_args__ = (
        UniqueConstraint("date", "market", "index_name", name="uq_snapshot"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    market: Mapped[str] = mapped_column(String(20))
    index_name: Mapped[str] = mapped_column(String(50))
    close: Mapped[str] = mapped_column(String(30))
    change_pct: Mapped[str] = mapped_column(String(20))
    direction: Mapped[str] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class AiTrace(Base):
    __tablename__ = "ai_traces"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), index=True, default="")
    pipeline: Mapped[str] = mapped_column(String(50), index=True)
    stage: Mapped[str] = mapped_column(String(50))
    provider_name: Mapped[str] = mapped_column(String(30))
    model_name: Mapped[str] = mapped_column(String(100))
    system_prompt: Mapped[str] = mapped_column(Text)
    user_prompt: Mapped[str] = mapped_column(Text)
    response: Mapped[str] = mapped_column(Text, default="")
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC), index=True)

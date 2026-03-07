from datetime import UTC, date, datetime
from enum import StrEnum

from sqlalchemy import Date, Float, Integer, String, Text, DateTime, Boolean, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class BriefingType(StrEnum):
    """브리핑 카테고리 — 파이프라인·발행·OG이미지 등에서 공유."""

    KOSPI = "kospi_briefing"
    NASDAQ = "nasdaq_briefing"
    NEWS_DIVE = "news_dive"
    ISSUE_DIVE = "issue_dive"
    REAL_ESTATE = "real_estate_briefing"
    STOCK_DEEP_DIVE = "stock_deep_dive"
    PORTFOLIO = "portfolio"


class Subscriber(Base):
    __tablename__ = "subscribers"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class Briefing(Base):
    __tablename__ = "briefings"

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    briefing_type: Mapped[str] = mapped_column(String(20), default="kr")
    title: Mapped[str] = mapped_column(String(200))
    content_html: Mapped[str] = mapped_column(Text)
    blog_url: Mapped[str] = mapped_column(String(500), default="")
    excerpt: Mapped[str] = mapped_column(String(500), default="")
    slug: Mapped[str] = mapped_column(String(200), default="")
    tags: Mapped[str] = mapped_column(String(500), default="")
    focus_keyword: Mapped[str] = mapped_column(String(100), default="")
    image_keyword: Mapped[str] = mapped_column(String(100), default="")
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


class PortfolioHolding(Base):
    """AI 포트폴리오 현재 보유 종목."""

    __tablename__ = "portfolio_holdings"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(10), index=True)
    name: Mapped[str] = mapped_column(String(100), default="")
    industry: Mapped[str] = mapped_column(String(100), default="")
    weight_pct: Mapped[float] = mapped_column(Float, default=0.0)
    entry_price: Mapped[float] = mapped_column(Float, default=0.0)
    entry_date: Mapped[date] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))


class PortfolioDailySnapshot(Base):
    """일일 포트폴리오 P&L 스냅샷."""

    __tablename__ = "portfolio_daily_snapshots"
    __table_args__ = (
        UniqueConstraint("snapshot_date", "ticker", name="uq_portfolio_snapshot"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_date: Mapped[date] = mapped_column(Date, index=True)
    ticker: Mapped[str] = mapped_column(String(10))
    current_price: Mapped[float] = mapped_column(Float, default=0.0)
    entry_price: Mapped[float] = mapped_column(Float, default=0.0)
    weight_pct: Mapped[float] = mapped_column(Float, default=0.0)
    return_pct: Mapped[float] = mapped_column(Float, default=0.0)
    contribution_pct: Mapped[float] = mapped_column(Float, default=0.0)


class PortfolioChangeLog(Base):
    """포트폴리오 변경 이력."""

    __tablename__ = "portfolio_change_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    change_date: Mapped[date] = mapped_column(Date, index=True)
    action: Mapped[str] = mapped_column(String(20))
    ticker: Mapped[str] = mapped_column(String(10))
    old_weight_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    new_weight_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    run_id: Mapped[str] = mapped_column(String(36), default="")

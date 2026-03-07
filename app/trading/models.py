"""코인 자동매매 — DB 모델."""

from datetime import UTC, date, datetime

from sqlalchemy import Date, Float, Integer, String, Text, DateTime, Boolean, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class CryptoPosition(Base):
    """현재 코인 포지션."""

    __tablename__ = "crypto_positions"

    id: Mapped[int] = mapped_column(primary_key=True)
    market: Mapped[str] = mapped_column(String(20), index=True)  # "KRW-BTC"
    avg_price: Mapped[float] = mapped_column(Float, default=0.0)
    quantity: Mapped[float] = mapped_column(Float, default=0.0)
    target_weight_pct: Mapped[float] = mapped_column(Float, default=0.0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


class CryptoTrade(Base):
    """매매 이력."""

    __tablename__ = "crypto_trades"

    id: Mapped[int] = mapped_column(primary_key=True)
    trade_date: Mapped[datetime] = mapped_column(DateTime, index=True)
    market: Mapped[str] = mapped_column(String(20), index=True)
    side: Mapped[str] = mapped_column(String(10))  # "BUY" / "SELL"
    price: Mapped[float] = mapped_column(Float, default=0.0)
    quantity: Mapped[float] = mapped_column(Float, default=0.0)
    amount_krw: Mapped[float] = mapped_column(Float, default=0.0)
    fee: Mapped[float] = mapped_column(Float, default=0.0)
    signal_type: Mapped[str] = mapped_column(String(10))  # "RULE" / "AI"
    reason: Mapped[str] = mapped_column(Text, default="")
    run_id: Mapped[str] = mapped_column(String(36), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class CryptoSnapshot(Base):
    """일일 포트폴리오 스냅샷."""

    __tablename__ = "crypto_snapshots"
    __table_args__ = (
        UniqueConstraint("snapshot_date", name="uq_crypto_snapshot_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_date: Mapped[date] = mapped_column(Date, index=True)
    total_krw: Mapped[float] = mapped_column(Float, default=0.0)
    cash_krw: Mapped[float] = mapped_column(Float, default=0.0)
    invested_krw: Mapped[float] = mapped_column(Float, default=0.0)
    return_pct: Mapped[float] = mapped_column(Float, default=0.0)
    positions_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class StrategyState(Base):
    """AI가 조정한 전략 파라미터."""

    __tablename__ = "crypto_strategy_states"

    id: Mapped[int] = mapped_column(primary_key=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    mode: Mapped[str] = mapped_column(String(20), default="moderate")  # aggressive/moderate/defensive
    max_position_pct: Mapped[float] = mapped_column(Float, default=20.0)
    rsi_buy_threshold: Mapped[float] = mapped_column(Float, default=30.0)
    rsi_sell_threshold: Mapped[float] = mapped_column(Float, default=70.0)
    params_json: Mapped[str] = mapped_column(Text, default="{}")
    ai_reasoning: Mapped[str] = mapped_column(Text, default="")
    run_id: Mapped[str] = mapped_column(String(36), default="")

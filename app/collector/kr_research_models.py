"""한국 종목 리서치 Pydantic 모델."""

from pydantic import BaseModel

from app.collector.research_models import PriceHistoryPoint


class KRCompanyProfile(BaseModel):
    """한국 종목 기업 프로필."""
    name: str = ""
    code: str = ""  # 6자리 종목코드
    market: str = ""  # KOSPI / KOSDAQ
    industry: str = ""
    market_cap: int = 0  # 억 원
    per: float | None = None
    pbr: float | None = None
    dividend_yield: float | None = None


class KRQuoteData(BaseModel):
    """한국 종목 실시간 시세."""
    current: int = 0
    change: int = 0
    change_pct: float = 0
    high: int = 0
    low: int = 0
    open: int = 0
    prev_close: int = 0
    volume: int = 0


class KRFinancialRow(BaseModel):
    """한국 종목 재무제표 행 (연간/분기)."""
    period: str = ""
    period_type: str = ""  # "annual" or "quarterly"
    revenue: float | None = None  # 매출액 (억 원)
    operating_income: float | None = None  # 영업이익
    net_income: float | None = None  # 순이익
    eps: float | None = None
    roe: float | None = None
    debt_ratio: float | None = None  # 부채비율


class KRStockResearchData(BaseModel):
    """한국 종목 딥 리서치 최상위 모델."""
    ticker: str  # 원래 입력값 (종목명 또는 코드)
    code: str = ""  # 6자리 종목코드
    profile: KRCompanyProfile = KRCompanyProfile()
    quote: KRQuoteData = KRQuoteData()
    financials: list[KRFinancialRow] = []
    price_history: list[PriceHistoryPoint] = []
    news_headlines: list[str] = []

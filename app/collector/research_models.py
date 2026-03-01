"""종목 리서치 Pydantic 모델."""

from pydantic import BaseModel


# ── 마켓 스캔 모델 ──


class MacroIndicators(BaseModel):
    """매크로 지표 — VIX, 금리, 달러, 지수, 원자재."""
    vix: float | None = None
    vix_change: float | None = None
    treasury_10y: float | None = None
    treasury_10y_change: float | None = None
    dxy: float | None = None
    dxy_change: float | None = None
    fear_greed_value: int | None = None
    fear_greed_label: str = ""
    sp500_close: float | None = None
    sp500_change_pct: float | None = None
    nasdaq_close: float | None = None
    nasdaq_change_pct: float | None = None
    dow_close: float | None = None
    dow_change_pct: float | None = None
    gold_close: float | None = None
    gold_change_pct: float | None = None
    wti_close: float | None = None
    wti_change_pct: float | None = None


class MarketScanStock(BaseModel):
    """스캔 시 개별 종목 데이터."""
    ticker: str
    name: str = ""
    close: float = 0
    change_pct: float = 0
    volume: int = 0
    avg_volume: float = 0
    market_cap: float = 0
    pe_ratio: float = 0
    industry: str = ""


class EarningsCalendarItem(BaseModel):
    """실적 발표 캘린더 항목."""
    ticker: str
    date: str = ""
    eps_estimate: float | None = None
    revenue_estimate: float | None = None


class MarketNewsItem(BaseModel):
    """시장 뉴스 항목."""
    headline: str
    summary: str = ""
    source: str = ""
    url: str = ""
    related: str = ""
    datetime_ts: int = 0


class MarketScanData(BaseModel):
    """마켓 스캔 결과 — Claude가 종목을 선택하기 위한 데이터."""
    scan_date: str = ""
    top_gainers: list[MarketScanStock] = []
    top_losers: list[MarketScanStock] = []
    top_volume: list[MarketScanStock] = []
    earnings_today: list[EarningsCalendarItem] = []
    earnings_tomorrow: list[EarningsCalendarItem] = []
    market_news: list[MarketNewsItem] = []


# ── 딥 리서치 모델 ──


class CompanyProfile(BaseModel):
    """Finnhub 기업 프로필."""
    name: str = ""
    ticker: str = ""
    exchange: str = ""
    industry: str = ""
    market_cap: float = 0
    share_outstanding: float = 0
    logo: str = ""
    weburl: str = ""
    ipo: str = ""
    country: str = ""


class QuoteData(BaseModel):
    """Finnhub 실시간 시세."""
    current: float = 0
    change: float = 0
    change_pct: float = 0
    high: float = 0
    low: float = 0
    open: float = 0
    prev_close: float = 0


class BasicFinancials(BaseModel):
    """Finnhub 핵심 재무지표."""
    pe_ttm: float | None = None
    pb_annual: float | None = None
    ps_ttm: float | None = None
    roe_ttm: float | None = None
    roi_ttm: float | None = None
    gross_margin_ttm: float | None = None
    operating_margin_ttm: float | None = None
    net_margin_ttm: float | None = None
    debt_equity: float | None = None
    current_ratio: float | None = None
    dividend_yield: float | None = None
    beta: float | None = None
    week52_high: float | None = None
    week52_low: float | None = None
    week52_high_date: str = ""
    week52_low_date: str = ""
    revenue_growth_3y: float | None = None
    eps_growth_3y: float | None = None


class EarningsData(BaseModel):
    """분기별 EPS 데이터."""
    period: str = ""
    actual: float | None = None
    estimate: float | None = None
    surprise_pct: float | None = None


class AnalystRecommendation(BaseModel):
    """애널리스트 추천."""
    period: str = ""
    strong_buy: int = 0
    buy: int = 0
    hold: int = 0
    sell: int = 0
    strong_sell: int = 0


class CompanyNews(BaseModel):
    """기업 뉴스."""
    headline: str = ""
    summary: str = ""
    source: str = ""
    url: str = ""
    datetime_ts: int = 0


class IncomeStatementRow(BaseModel):
    """손익계산서 행."""
    period: str = ""
    period_type: str = ""  # "annual" or "quarterly"
    total_revenue: float | None = None
    gross_profit: float | None = None
    operating_income: float | None = None
    net_income: float | None = None
    ebitda: float | None = None
    research_development: float | None = None
    diluted_eps: float | None = None


class BalanceSheetRow(BaseModel):
    """대차대조표 행."""
    period: str = ""
    period_type: str = ""
    total_assets: float | None = None
    total_liabilities: float | None = None
    stockholders_equity: float | None = None
    total_cash: float | None = None
    total_debt: float | None = None
    net_debt: float | None = None


class CashFlowRow(BaseModel):
    """현금흐름표 행."""
    period: str = ""
    period_type: str = ""
    operating_cf: float | None = None
    capital_expenditure: float | None = None
    free_cash_flow: float | None = None
    dividends_paid: float | None = None
    share_buyback: float | None = None


class PriceHistoryPoint(BaseModel):
    """일별 주가."""
    date: str
    close: float
    volume: int = 0


class RecentFiling(BaseModel):
    """SEC 공시."""
    form_type: str = ""
    filing_date: str = ""
    description: str = ""
    url: str = ""


class PeerFinancials(BaseModel):
    """Peer 기업 비교 지표."""
    ticker: str
    name: str = ""
    market_cap: float = 0
    pe_ttm: float | None = None
    pb_annual: float | None = None
    ps_ttm: float | None = None
    roe_ttm: float | None = None
    gross_margin_ttm: float | None = None
    operating_margin_ttm: float | None = None
    revenue_growth_3y: float | None = None


class StockResearchData(BaseModel):
    """딥 리서치 최상위 모델."""
    ticker: str
    profile: CompanyProfile = CompanyProfile()
    quote: QuoteData = QuoteData()
    financials: BasicFinancials = BasicFinancials()
    earnings: list[EarningsData] = []
    recommendations: list[AnalystRecommendation] = []
    news: list[CompanyNews] = []
    peers: list[str] = []
    income_statements: list[IncomeStatementRow] = []
    balance_sheets: list[BalanceSheetRow] = []
    cash_flows: list[CashFlowRow] = []
    price_history: list[PriceHistoryPoint] = []
    sec_filings: list[RecentFiling] = []
    peer_financials: list[PeerFinancials] = []


# ── 후보 종목 스크리닝 모델 ──


class CandidateScreenData(BaseModel):
    """후보 종목 스크리닝 결과 — 경량 재무지표."""
    ticker: str
    name: str = ""
    industry: str = ""
    close: float = 0
    change_pct_1d: float = 0
    change_pct_1y: float = 0
    market_cap: float = 0  # 백만 달러
    pe_ttm: float | None = None
    ps_ttm: float | None = None
    pb_annual: float | None = None
    roe_ttm: float | None = None
    gross_margin_ttm: float | None = None
    operating_margin_ttm: float | None = None
    revenue_growth_3y: float | None = None
    eps_growth_3y: float | None = None
    week52_high: float | None = None
    week52_low: float | None = None
    beta: float | None = None
    analyst_buy_pct: float | None = None  # (strongBuy+buy) / total

"""프롬프트 빌더 + 포맷 유틸리티 테스트."""

from app.prompts import fmt_money, fmt_num, fmt_pct


# ── fmt_money ──


def test_fmt_money_trillion():
    assert fmt_money(2_500_000_000_000) == "$2.5T"


def test_fmt_money_billion():
    assert fmt_money(3_400_000_000) == "$3.4B"


def test_fmt_money_million():
    assert fmt_money(56_700_000) == "$56.7M"


def test_fmt_money_small():
    assert fmt_money(1234) == "$1,234"


def test_fmt_money_negative():
    assert fmt_money(-1_200_000_000) == "-$1.2B"


def test_fmt_money_none():
    assert fmt_money(None) == "N/A"


def test_fmt_money_zero():
    assert fmt_money(0) == "$0"


# ── fmt_pct ──


def test_fmt_pct_positive():
    assert fmt_pct(12.34) == "12.3%"


def test_fmt_pct_negative():
    assert fmt_pct(-3.5) == "-3.5%"


def test_fmt_pct_none():
    assert fmt_pct(None) == "N/A"


# ── fmt_num ──


def test_fmt_num_normal():
    assert fmt_num(25.678) == "25.68"


def test_fmt_num_none():
    assert fmt_num(None) == "N/A"


# ── _build_research_prompt ──


def test_build_research_prompt_minimal():
    """최소 데이터로 프롬프트가 생성된다."""
    from app.collector.research_models import StockResearchData

    data = StockResearchData(ticker="AAPL")
    from app.prompts.deep_research import _build_research_prompt
    result = _build_research_prompt(data)
    assert "## 종목: AAPL" in result


def test_build_research_prompt_with_financials():
    """재무 데이터가 있으면 해당 섹션이 포함된다."""
    from app.collector.research_models import StockResearchData, BasicFinancials, QuoteData, CompanyProfile

    data = StockResearchData(
        ticker="NVDA",
        profile=CompanyProfile(
            name="NVIDIA", ticker="NVDA", exchange="NASDAQ",
            industry="Semiconductors", market_cap=3000,
        ),
        quote=QuoteData(current=950.0, change=-5.0, change_pct=-0.52),
        financials=BasicFinancials(pe_ttm=65.0, pb_annual=40.0, roe_ttm=120.0),
    )
    from app.prompts.deep_research import _build_research_prompt
    result = _build_research_prompt(data)
    assert "NVIDIA" in result
    assert "밸류에이션" in result
    assert "PER 65.00" in result

"""AI 포트폴리오 — 시스템 프롬프트, 프롬프트 빌더, LLM 호출."""

import json
import logging
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import func, select

from app.collector.research_models import CandidateScreenData, MacroIndicators, MarketScanData
from app.core.database import async_session
from app.core.models import PortfolioDailySnapshot, PortfolioHolding
from app.summarizer import get_provider, strip_code_block

logger = logging.getLogger(__name__)


# ── 데이터클래스 ──


@dataclass
class PortfolioDecision:
    action: str  # KEEP, ADD, REMOVE, REWEIGHT
    ticker: str
    name: str
    new_weight_pct: float
    reason: str


@dataclass
class PortfolioDecisions:
    decisions: list[PortfolioDecision] = field(default_factory=list)
    market_view: str = ""
    cash_weight_pct: float = 0.0


# ── 프롬프트 ──


PORTFOLIO_SYSTEM_DAY1 = """\
당신은 나스닥 100 기반 가상 포트폴리오를 운용하는 AI 포트폴리오 매니저예요.
오늘은 Day 1 — 최초 포트폴리오를 구성해야 해요.

## 역할
- NASDAQ 100 종목 중에서 10~15종목을 골라 가상 포트폴리오를 구성하세요.
- 각 종목에 비중(weight_pct)을 배정하세요.
- 시장 불확실성이 높다면 현금(cash_weight_pct)을 보유할 수 있어요.

## 규칙
1. 종목 수: 10~15개
2. **종목 비중 합계 + cash_weight_pct = 정확히 100%**
3. 단일 종목 최대 비중: 15%
4. 단일 종목 최소 비중: 2%
5. 동일 섹터 합산 최대: 30%
6. 현금 비중: 0~30% (시장이 안정적이면 0%, 불확실하면 최대 30%)
7. 모든 종목의 action은 "ADD"

## 코인 관련 규칙
- 후보에 코인(Cryptocurrency)도 포함되어 있음. 시장 상황상 코인이 유리하다고 판단하면 편입 가능
- 코인 편입은 선택 사항 — 강제 아님. 주식만으로 구성해도 됨
- 코인 편입 시 합산 최대 20%
- 코인은 PER/ROE 등 재무지표 없음 — 시총/거래량/추세/시장 심리 기반 판단

## 출력 형식 (반드시 JSON만 출력, 다른 텍스트 없이)
```json
{
  "decisions": [
    {"action": "ADD", "ticker": "NVDA", "name": "NVIDIA", "new_weight_pct": 12.0, "reason": "이유"}
  ],
  "cash_weight_pct": 5.0,
  "market_view": "현재 시장 판단 2~3문장"
}
```
"""

PORTFOLIO_SYSTEM_DAYN = """\
당신은 나스닥 100 기반 가상 포트폴리오를 운용하는 AI 포트폴리오 매니저예요.
오늘은 Day {day_number} — 기존 포트폴리오를 리뷰하고 필요시 조정해야 해요.

## 역할
- 현재 보유 종목과 시장 상황을 분석하세요.
- 유지(KEEP), 추가(ADD), 제거(REMOVE), 비중조정(REWEIGHT) 결정을 내리세요.
- 시장 불확실성에 따라 현금 비중을 조절할 수 있어요.

## 규칙
1. 최종 종목 수: 10~15개
2. **종목 비중 합계 + cash_weight_pct = 정확히 100%**
3. 단일 종목 최대 비중: 15%
4. 단일 종목 최소 비중: 2%
5. 동일 섹터 합산 최대: 30%
6. 현금 비중: 0~30% (시장이 안정적이면 0%, 불확실하면 최대 30%)
7. **변경 최소화 원칙**: 명확한 근거 없이 변경하지 마세요. KEEP을 우선하세요.
8. REMOVE된 종목은 decisions에 포함하되 new_weight_pct를 0으로 설정
9. 모든 보유 종목은 반드시 decisions에 포함 (KEEP이든 REWEIGHT든)

## 코인 관련 규칙
- 후보에 코인(Cryptocurrency)도 포함되어 있음. 시장 상황상 코인이 유리하다고 판단하면 편입 가능
- 코인 편입은 선택 사항 — 강제 아님. 주식만으로 구성해도 됨
- 코인 편입 시 합산 최대 20%
- 코인은 PER/ROE 등 재무지표 없음 — 시총/거래량/추세/시장 심리 기반 판단

## 출력 형식 (반드시 JSON만 출력, 다른 텍스트 없이)
```json
{{
  "decisions": [
    {{"action": "KEEP", "ticker": "NVDA", "name": "NVIDIA", "new_weight_pct": 12.0, "reason": "이유"}},
    {{"action": "ADD", "ticker": "NEW", "name": "NewCorp", "new_weight_pct": 5.0, "reason": "이유"}},
    {{"action": "REMOVE", "ticker": "OLD", "name": "OldCorp", "new_weight_pct": 0, "reason": "이유"}},
    {{"action": "REWEIGHT", "ticker": "XYZ", "name": "XYZCorp", "new_weight_pct": 8.0, "reason": "이유"}}
  ],
  "cash_weight_pct": 5.0,
  "market_view": "현재 시장 판단 2~3문장"
}}
```
"""


def _build_portfolio_prompt(
    holdings: list[PortfolioHolding],
    candidates: list[CandidateScreenData],
    macro: MacroIndicators,
    scan: MarketScanData,
) -> tuple[str, str]:
    """(system_prompt, user_prompt) 튜플을 반환한다."""
    is_day1 = len(holdings) == 0
    parts: list[str] = [f"## 날짜: {date.today()}\n"]

    # 매크로 지표
    parts.append("## 매크로 지표")
    if macro.vix is not None:
        parts.append(f"- VIX: {macro.vix} (변화: {macro.vix_change})")
    if macro.treasury_10y is not None:
        parts.append(f"- 미국 10년물 금리: {macro.treasury_10y}%")
    if macro.fear_greed_value is not None:
        parts.append(f"- Fear & Greed: {macro.fear_greed_value} ({macro.fear_greed_label})")
    if macro.sp500_close is not None:
        parts.append(f"- S&P500: {macro.sp500_close} ({macro.sp500_change_pct:+.2f}%)")
    if macro.nasdaq_close is not None:
        parts.append(f"- NASDAQ: {macro.nasdaq_close} ({macro.nasdaq_change_pct:+.2f}%)")
    if macro.dxy is not None:
        parts.append(f"- 달러 인덱스: {macro.dxy}")
    parts.append("")

    # 시장 스캔
    if scan.top_gainers:
        parts.append("## 상승 상위 종목")
        for s in scan.top_gainers[:5]:
            parts.append(f"- {s.ticker}: ${s.close} ({s.change_pct:+.2f}%)")
    if scan.top_losers:
        parts.append("## 하락 상위 종목")
        for s in scan.top_losers[:5]:
            parts.append(f"- {s.ticker}: ${s.close} ({s.change_pct:+.2f}%)")
    if scan.market_news:
        parts.append("## 주요 뉴스")
        for n in scan.market_news[:10]:
            parts.append(f"- {n.headline}")
    parts.append("")

    # 현재 보유 종목 (Day N)
    if holdings:
        parts.append("## 현재 포트폴리오")
        for h in holdings:
            parts.append(f"- {h.ticker} ({h.name}): 비중 {h.weight_pct}%, 편입가 ${h.entry_price:.2f}, 섹터 {h.industry}")
        parts.append("")

    # 후보 종목 스크리닝 데이터 (주식/코인 분리)
    stock_candidates = [c for c in candidates if c.industry != "Cryptocurrency"]
    crypto_candidates = [c for c in candidates if c.industry == "Cryptocurrency"]

    parts.append("## 후보 종목 스크리닝")
    for c in stock_candidates:
        line = f"- {c.ticker} ({c.name}): ${c.close} ({c.change_pct_1d:+.2f}%), 섹터 {c.industry}"
        if c.pe_ttm is not None:
            line += f", PER {c.pe_ttm:.1f}"
        if c.roe_ttm is not None:
            line += f", ROE {c.roe_ttm:.1f}%"
        if c.analyst_buy_pct is not None:
            line += f", 매수 비율 {c.analyst_buy_pct:.0f}%"
        if c.market_cap:
            line += f", 시총 ${c.market_cap:,.0f}M"
        parts.append(line)

    if crypto_candidates:
        parts.append("")
        parts.append("## 코인 후보 (편입 선택 사항)")
        for c in crypto_candidates:
            line = f"- {c.ticker} ({c.name}): ${c.close:,.2f} ({c.change_pct_1d:+.2f}%)"
            if c.market_cap:
                line += f", 시총 ${c.market_cap:,.0f}M"
            if c.week52_high is not None:
                line += f", 52주 고가 ${c.week52_high:,.2f}"
            if c.week52_low is not None:
                line += f", 52주 저가 ${c.week52_low:,.2f}"
            parts.append(line)

    user_prompt = "\n".join(parts)

    if is_day1:
        system_prompt = PORTFOLIO_SYSTEM_DAY1
    else:
        day_number = _compute_day_number_sync(holdings)
        system_prompt = PORTFOLIO_SYSTEM_DAYN.format(day_number=day_number)

    return system_prompt, user_prompt


def _compute_day_number_sync(holdings: list) -> int:
    """보유 종목의 최초 편입일 기준 Day 번호를 계산한다 (동기 호출용 근사치)."""
    if not holdings:
        return 1
    earliest = min(h.entry_date for h in holdings)
    return (date.today() - earliest).days + 1


async def _compute_day_number() -> int:
    """DB 스냅샷 날짜 수를 카운트하여 Day 번호를 계산한다."""
    async with async_session() as db:
        result = await db.execute(
            select(func.count(func.distinct(PortfolioDailySnapshot.snapshot_date)))
        )
        count = result.scalar() or 0
    return count + 1


async def call_portfolio_llm(
    holdings: list[PortfolioHolding],
    candidates: list[CandidateScreenData],
    macro: MacroIndicators,
    scan: MarketScanData,
    run_id: str = "",
) -> PortfolioDecisions:
    """LLM을 호출하여 포트폴리오 결정을 받는다."""
    import asyncio

    system_prompt, user_prompt = _build_portfolio_prompt(holdings, candidates, macro, scan)
    provider = get_provider(pipeline="portfolio", stage="decision", run_id=run_id)
    raw = await asyncio.to_thread(provider.call, system_prompt, user_prompt)
    raw = strip_code_block(raw)

    # JSON 파싱
    try:
        data = _extract_json(raw)
        decisions = [
            PortfolioDecision(
                action=d["action"],
                ticker=d["ticker"],
                name=d.get("name", ""),
                new_weight_pct=float(d["new_weight_pct"]),
                reason=d.get("reason", ""),
            )
            for d in data.get("decisions", [])
        ]
        result = PortfolioDecisions(
            decisions=decisions,
            market_view=data.get("market_view", ""),
            cash_weight_pct=float(data.get("cash_weight_pct", 0)),
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        logger.error("포트폴리오 LLM JSON 파싱 실패 — 기존 포트폴리오 KEEP: %s", e)
        # fallback: 기존 포트폴리오 전부 KEEP
        result = PortfolioDecisions(
            decisions=[
                PortfolioDecision(
                    action="KEEP",
                    ticker=h.ticker,
                    name=h.name,
                    new_weight_pct=h.weight_pct,
                    reason="LLM 응답 파싱 실패로 기존 유지",
                )
                for h in holdings
            ],
            market_view="LLM 응답 파싱 실패로 기존 포트폴리오를 유지합니다.",
        )

    # 비중 합계 정규화 (REMOVE 제외)
    _normalize_weights(result)

    logger.info(
        "포트폴리오 결정 완료: %d종목, actions=%s",
        len(result.decisions),
        {d.action for d in result.decisions},
    )
    return result


def _extract_json(raw: str) -> dict:
    """LLM 응답에서 최상위 JSON 객체를 추출한다."""
    import re

    # 코드블록 내부 추출
    m = re.search(r'```(?:json)?\s*\n?(.*?)```', raw, re.DOTALL)
    text = m.group(1).strip() if m else raw.strip()

    # { 부터 마지막 } 까지 추출
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise json.JSONDecodeError("No JSON object found", text, 0)

    return json.loads(text[start:end + 1])


def _normalize_weights(result: PortfolioDecisions) -> None:
    """종목 비중 + 현금 비중 = 100%가 되도록 정규화한다."""
    active = [d for d in result.decisions if d.action != "REMOVE"]
    if not active:
        return

    # 현금 비중 범위 제한 (0~30%)
    result.cash_weight_pct = max(0.0, min(30.0, result.cash_weight_pct))

    stock_total = sum(d.new_weight_pct for d in active)
    grand_total = stock_total + result.cash_weight_pct

    if abs(grand_total - 100.0) > 0.5:
        logger.warning("비중 합계 %.1f%% (종목 %.1f%% + 현금 %.1f%%) → 100%%로 정규화",
                        grand_total, stock_total, result.cash_weight_pct)
        # 현금 비중은 유지하고 종목 비중만 스케일링
        target_stock = 100.0 - result.cash_weight_pct
        if stock_total > 0:
            for d in active:
                d.new_weight_pct = round(d.new_weight_pct / stock_total * target_stock, 1)
            # 반올림 오차 보정
            remainder = target_stock - sum(d.new_weight_pct for d in active)
            biggest = max(active, key=lambda d: d.new_weight_pct)
            biggest.new_weight_pct = round(biggest.new_weight_pct + remainder, 1)

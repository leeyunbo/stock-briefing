"""코인 자동매매 — AI 전략 프롬프트, 프롬프트 빌더, LLM 호출."""

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime

from app.summarizer import get_provider, strip_code_block
from app.trading.indicators import TechnicalIndicators
from app.trading.signals import StrategyParams

logger = logging.getLogger(__name__)


# ── 데이터클래스 ──


@dataclass
class CryptoAIDecision:
    """AI의 개별 코인 결정."""

    market: str          # "KRW-BTC"
    action: str          # "BUY" / "SELL" / "HOLD" / "REWEIGHT"
    target_weight_pct: float
    reason: str


@dataclass
class CryptoStrategyResult:
    """AI 전략 판단 결과."""

    mode: str = "moderate"  # aggressive / moderate / defensive
    decisions: list[CryptoAIDecision] = field(default_factory=list)
    market_view: str = ""
    params: StrategyParams = field(default_factory=StrategyParams)


# ── 프롬프트 ──


CRYPTO_STRATEGY_SYSTEM = """\
당신은 100만원으로 업비트에서 코인을 운용하는 AI 트레이더예요.
스윙 트레이딩 (15분~4시간봉) 전략을 사용합니다.

## 역할
- 현재 포지션, 기술적 지표, 시장 상황을 분석하세요.
- 전략 모드(aggressive/moderate/defensive)를 결정하세요.
- 포지션 비중을 조정하세요 (BUY/SELL/HOLD/REWEIGHT).

## 리스크 관리 규칙
1. 단일 코인 최대 비중: 30%
2. 총 투자 비중: 30~90% (나머지 현금)
3. 손절: 편입가 대비 -7% 도달 시 자동 매도 (규칙 기반에서 처리)
4. 익절: 편입가 대비 +15% 도달 시 일부(50%) 매도 (규칙 기반에서 처리)
5. 1회 매매 최대 금액: 총 자산의 20%

## 전략 모드 설명
- **aggressive**: RSI 매수 기준 35, 매도 기준 65. 빠른 진입/청산.
- **moderate**: RSI 매수 기준 30, 매도 기준 70. 균형 전략.
- **defensive**: RSI 매수 기준 25, 매도 기준 75. 보수적 진입, 현금 비중 높게.

## 출력 형식 (반드시 JSON만 출력, 다른 텍스트 없이)
```json
{
  "mode": "moderate",
  "decisions": [
    {"market": "KRW-BTC", "action": "HOLD", "target_weight_pct": 15.0, "reason": "이유"},
    {"market": "KRW-ETH", "action": "BUY", "target_weight_pct": 10.0, "reason": "이유"}
  ],
  "market_view": "현재 시장 판단 2~3문장",
  "strategy_params": {
    "rsi_buy_threshold": 30,
    "rsi_sell_threshold": 70,
    "max_position_pct": 20
  }
}
```
"""


# ── 프롬프트 빌더 ──


@dataclass
class MarketDataForPrompt:
    """AI 프롬프트에 전달할 시장 데이터."""

    market: str
    current_price: float = 0.0
    change_pct_24h: float = 0.0
    volume_24h: float = 0.0
    indicators: TechnicalIndicators = field(default_factory=TechnicalIndicators)
    # 포지션 정보 (보유 중인 경우)
    holding_qty: float = 0.0
    avg_price: float = 0.0
    return_pct: float = 0.0


def build_strategy_prompt(
    market_data: list[MarketDataForPrompt],
    cash_krw: float,
    total_asset_krw: float,
    current_mode: str = "moderate",
) -> str:
    """AI 전략 판단을 위한 user prompt를 생성한다."""
    parts: list[str] = []
    now = datetime.now()
    parts.append(f"## 시각: {now.strftime('%Y-%m-%d %H:%M')}")
    parts.append(f"## 현금: {cash_krw:,.0f}원 / 총자산: {total_asset_krw:,.0f}원")
    parts.append(f"## 현재 전략 모드: {current_mode}")
    parts.append("")

    # 보유 포지션
    holdings = [m for m in market_data if m.holding_qty > 0]
    if holdings:
        parts.append("## 현재 포지션")
        for m in holdings:
            invested = m.avg_price * m.holding_qty
            parts.append(
                f"- {m.market}: 수량 {m.holding_qty:.8f}, 평단가 {m.avg_price:,.0f}원, "
                f"현재가 {m.current_price:,.0f}원, 수익률 {m.return_pct:+.2f}%, "
                f"평가금 {m.current_price * m.holding_qty:,.0f}원"
            )
        parts.append("")

    # 전체 코인 기술적 지표
    parts.append("## 코인별 기술적 지표")
    for m in market_data:
        ind = m.indicators
        line = f"- {m.market}: {m.current_price:,.0f}원 ({m.change_pct_24h:+.2f}%)"

        details = []
        if ind.rsi_14 is not None:
            details.append(f"RSI {ind.rsi_14:.1f}")
        if ind.macd_histogram is not None:
            direction = "+" if ind.macd_histogram > 0 else ""
            details.append(f"MACD히스토그램 {direction}{ind.macd_histogram:.1f}")
        if ind.bb_lower is not None and ind.bb_upper is not None:
            details.append(f"BB [{ind.bb_lower:,.0f}~{ind.bb_upper:,.0f}]")
        if ind.sma_20 is not None:
            details.append(f"SMA20 {ind.sma_20:,.0f}")
        if ind.sma_50 is not None:
            details.append(f"SMA50 {ind.sma_50:,.0f}")
        if ind.volume_ratio is not None:
            details.append(f"거래량비 {ind.volume_ratio:.1f}x")
        if ind.atr_14 is not None:
            details.append(f"ATR {ind.atr_14:,.0f}")

        if details:
            line += " | " + ", ".join(details)
        parts.append(line)

    return "\n".join(parts)


# ── LLM 호출 ──


async def call_crypto_strategy_llm(
    market_data: list[MarketDataForPrompt],
    cash_krw: float,
    total_asset_krw: float,
    current_mode: str = "moderate",
    run_id: str = "",
) -> CryptoStrategyResult:
    """AI에게 전략 판단을 요청한다."""
    user_prompt = build_strategy_prompt(market_data, cash_krw, total_asset_krw, current_mode)
    provider = get_provider(pipeline="crypto_trading", stage="strategy", run_id=run_id)
    raw = await asyncio.to_thread(provider.call, CRYPTO_STRATEGY_SYSTEM, user_prompt)
    raw = strip_code_block(raw)

    try:
        data = _extract_json(raw)
        decisions = [
            CryptoAIDecision(
                market=d["market"],
                action=d["action"],
                target_weight_pct=float(d["target_weight_pct"]),
                reason=d.get("reason", ""),
            )
            for d in data.get("decisions", [])
        ]

        sp = data.get("strategy_params", {})
        params = StrategyParams(
            mode=data.get("mode", "moderate"),
            rsi_buy_threshold=float(sp.get("rsi_buy_threshold", 30)),
            rsi_sell_threshold=float(sp.get("rsi_sell_threshold", 70)),
            max_position_pct=float(sp.get("max_position_pct", 20)),
        )

        return CryptoStrategyResult(
            mode=data.get("mode", "moderate"),
            decisions=decisions,
            market_view=data.get("market_view", ""),
            params=params,
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        logger.error("AI 전략 JSON 파싱 실패 — 기본 moderate 유지: %s", e)
        return CryptoStrategyResult(mode="moderate", market_view="AI 응답 파싱 실패")


def _extract_json(raw: str) -> dict:
    """LLM 응답에서 JSON 객체를 추출한다."""
    m = re.search(r'```(?:json)?\s*\n?(.*?)```', raw, re.DOTALL)
    text = m.group(1).strip() if m else raw.strip()

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise json.JSONDecodeError("No JSON object found", text, 0)

    return json.loads(text[start:end + 1])

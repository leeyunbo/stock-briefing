"""프롬프트 모듈 — 시스템 프롬프트, 프롬프트 빌더, AI 호출 함수."""


def fmt_money(value: float | None) -> str:
    """금액을 읽기 쉬운 형태로 변환한다 (예: $1.2T, $3.4B)."""
    if value is None:
        return "N/A"
    abs_val = abs(value)
    sign = "-" if value < 0 else ""
    if abs_val >= 1_000_000_000_000:
        return f"{sign}${abs_val / 1_000_000_000_000:,.1f}T"
    if abs_val >= 1_000_000_000:
        return f"{sign}${abs_val / 1_000_000_000:,.1f}B"
    if abs_val >= 1_000_000:
        return f"{sign}${abs_val / 1_000_000:,.1f}M"
    return f"{sign}${abs_val:,.0f}"


def fmt_pct(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:.1f}%"


def fmt_num(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:.2f}"

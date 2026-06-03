"""개인 아침 브리핑 — 내 레이더(보유·관심) + 발굴 유니버스(테마).

중장기 관점. 티커는 yfinance 형식 (US: 심볼 그대로, KR: 6자리+.KS/.KQ).
종목 추가/삭제는 이 파일만 고치면 된다.
"""

# 내 레이더 — 보유 중이거나 진지하게 보는 종목 (relevance filter의 핵심)
WATCHLIST: list[tuple[str, str]] = [
    ("MRVL", "마벨테크놀로지"),
    ("AMZN", "아마존"),
    ("GOOGL", "알파벳"),
    ("035420.KS", "네이버"),
    ("000660.KS", "SK하이닉스"),
]

# 발굴 유니버스 — 테마별 우량주 풀. 여기서 '밸류 눌림목'을 골라 추가 후보를 제안한다.
THEMES: dict[str, list[tuple[str, str]]] = {
    "반도체": [
        ("NVDA", "엔비디아"),
        ("AVGO", "브로드컴"),
        ("AMD", "AMD"),
        ("TSM", "TSMC"),
        ("ASML", "ASML"),
        ("MU", "마이크론"),
        ("ARM", "ARM"),
        ("005930.KS", "삼성전자"),
        ("000660.KS", "SK하이닉스"),
    ],
    "AI SW": [
        ("MSFT", "마이크로소프트"),
        ("GOOGL", "알파벳"),
        ("PLTR", "팔란티어"),
        ("NOW", "서비스나우"),
        ("CRM", "세일즈포스"),
        ("SNOW", "스노우플레이크"),
        ("035420.KS", "네이버"),
        ("035720.KS", "카카오"),
    ],
    "로봇": [
        ("ISRG", "인튜이티브서지컬"),
        ("TER", "테라다인"),
        ("ROK", "로크웰오토메이션"),
        ("SYM", "심보틱"),
        ("454910.KS", "두산로보틱스"),
        ("277810.KQ", "레인보우로보틱스"),
    ],
    "M7": [
        ("AAPL", "애플"),
        ("MSFT", "마이크로소프트"),
        ("GOOGL", "알파벳"),
        ("AMZN", "아마존"),
        ("NVDA", "엔비디아"),
        ("META", "메타"),
        ("TSLA", "테슬라"),
    ],
}


def _names() -> dict[str, str]:
    """티커 → 표시 이름 (레이더 + 테마 통합)."""
    out: dict[str, str] = {}
    for ticker, name in WATCHLIST:
        out[ticker] = name
    for pairs in THEMES.values():
        for ticker, name in pairs:
            out.setdefault(ticker, name)
    return out


def all_tickers() -> list[str]:
    """레이더 + 테마의 중복 제거된 티커 목록."""
    return list(_names())

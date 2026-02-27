"""주식 리서치 CLI 엔트리포인트.

사용법:
    python -m app.cli.research                              # 테마 기반 종합 리포트 → 전체 구독자
    python -m app.cli.research --email a@b.com              # 테마 기반 → 특정 주소로
    python -m app.cli.research --ticker NVDA                # 개별 종목 딥리서치 → 전체 구독자
    python -m app.cli.research --ticker NVDA --email a@b.com  # 개별 종목 → 특정 주소로
    python -m app.cli.research --no-email                   # 발송 없이 생성만
"""

import argparse
import asyncio
import logging
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="주식 리서치 파이프라인")
    parser.add_argument("--ticker", type=str, default=None,
                        help="개별 종목 딥리서치 모드 (미지정 시 뉴스 딥다이브)")
    parser.add_argument("--email", type=str, nargs="+", default=None,
                        help="발송할 이메일 주소 (미지정 시 전체 구독자)")
    parser.add_argument("--no-email", action="store_true",
                        help="이메일 발송 없이 리포트만 생성")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logger = logging.getLogger(__name__)

    # 이메일 옵션
    if args.no_email:
        email_to: list[str] | None = []
    elif args.email:
        email_to = args.email
    else:
        email_to = None

    ticker = args.ticker.upper() if args.ticker else None

    if ticker:
        # Mode B: 개별 종목 딥리서치
        logger.info("개별 종목 딥리서치 시작: %s", ticker)
        from app.pipeline.research import run_deep_research_pipeline
        html = asyncio.run(run_deep_research_pipeline(ticker=ticker, email_to=email_to))
        out_path = Path(f"/tmp/research_{ticker.lower()}.html")
    else:
        # Mode A: 뉴스 딥다이브
        logger.info("뉴스 딥다이브 리포트 시작")
        from app.pipeline.research import run_news_dive_pipeline
        html = asyncio.run(run_news_dive_pipeline(email_to=email_to))
        out_path = Path("/tmp/news_dive.html")

    out_path.write_text(html, encoding="utf-8")
    logger.info("리포트 저장: %s", out_path)
    print(f"\n리포트 저장 완료: {out_path}")


if __name__ == "__main__":
    main()

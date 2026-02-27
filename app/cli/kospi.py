"""국내주식 마감 브리핑 CLI 엔트리포인트.

사용법:
    python -m app.cli.kospi                              # 브리핑 → 전체 구독자
    python -m app.cli.kospi --email a@b.com              # 브리핑 → 특정 주소로
    python -m app.cli.kospi --no-email                   # 발송 없이 생성만
"""

import argparse
import asyncio
import logging
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="국내주식 마감 브리핑 파이프라인")
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

    if args.no_email:
        email_to: list[str] | None = []
    elif args.email:
        email_to = args.email
    else:
        email_to = None

    logger.info("국내주식 마감 브리핑 시작")
    from app.pipeline.kospi import run_pipeline
    html = asyncio.run(run_pipeline(email_to=email_to))

    out_path = Path("/tmp/kospi_briefing.html")
    out_path.write_text(html, encoding="utf-8")
    logger.info("리포트 저장: %s", out_path)
    print(f"\n리포트 저장 완료: {out_path}")


if __name__ == "__main__":
    main()

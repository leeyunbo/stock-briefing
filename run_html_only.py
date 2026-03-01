"""전체 파이프라인 HTML만 생성 (WordPress/이메일 없음)."""

import asyncio
import logging
from datetime import date

from app.core.models import BriefingType
from app.pipeline.base import deliver, run_steps
from app.pipeline.kospi import KOSPI_STEPS
from app.pipeline.nasdaq import NASDAQ_STEPS
from app.pipeline.real_estate import REAL_ESTATE_STEPS
from app.pipeline.research import NEWS_DIVE_STEPS
from app.tracing import generate_run_id

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

PIPELINES = [
    ("국내주식 (KOSPI)", "kospi", BriefingType.KOSPI, KOSPI_STEPS),
    ("미국주식 (NASDAQ)", "nasdaq", BriefingType.NASDAQ, NASDAQ_STEPS),
    ("부동산", "real_estate", BriefingType.REAL_ESTATE, REAL_ESTATE_STEPS),
    ("뉴스 딥다이브", "news_dive", BriefingType.NEWS_DIVE, NEWS_DIVE_STEPS),
]


async def main():
    today = date.today().isoformat()

    for label, pipeline, briefing_type, steps in PIPELINES:
        print(f"\n=== {label} 시작 ===")
        dry_steps = [s for s in steps if s is not deliver]
        ctx = {
            "run_id": generate_run_id(),
            "pipeline": pipeline,
            "briefing_type": briefing_type,
        }
        await run_steps(dry_steps, ctx)
        result = ctx.get("result")
        if result:
            fname = f"briefing_{pipeline}_{today}.html"
            with open(fname, "w") as f:
                f.write(result.html)
            print(f"저장 완료: {fname}")
        else:
            print(f"{label} 스킵됨 (데이터 없음)")

    print("\n전체 완료!")


if __name__ == "__main__":
    asyncio.run(main())

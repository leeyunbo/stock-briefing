"""파이프라인 수동 실행 관리자 페이지."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.models import AiTrace, Briefing, BriefingType
from app.pipeline.kospi import run_pipeline
from app.pipeline.nasdaq import run_nasdaq_pipeline
from app.pipeline.research import run_news_dive_pipeline
from app.pipeline.issue_dive import run_issue_dive_pipeline
from app.pipeline.real_estate import run_real_estate_pipeline
from app.pipeline.stock_deep_dive import run_stock_deep_dive_pipeline
from app.pipeline.chart_analysis import run_chart_analysis_pipeline
from app.pipeline.portfolio import run_portfolio_pipeline

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pipelines")
templates = Jinja2Templates(directory="templates")

KST = timezone(timedelta(hours=9))

# 파이프라인 ID → BriefingType 매핑
BRIEFING_TYPE_MAP: dict[str, str] = {
    "kospi": BriefingType.KOSPI,
    "nasdaq": BriefingType.NASDAQ,
    "news_dive": BriefingType.NEWS_DIVE,
    "issue_dive": BriefingType.ISSUE_DIVE,
    "real_estate": BriefingType.REAL_ESTATE,
    "stock_deep_dive": BriefingType.STOCK_DEEP_DIVE,
    "portfolio": BriefingType.PORTFOLIO,
}

# ── 파이프라인 정의 ──────────────────────────────────────────
PIPELINES: list[dict[str, Any]] = [
    {
        "id": "kospi",
        "name": "KOSPI 브리핑",
        "description": "국내 증시 요약 브리핑을 생성합니다.",
        "schedule": "월–금 20:00",
        "func": run_pipeline,
    },
    {
        "id": "nasdaq",
        "name": "NASDAQ 브리핑",
        "description": "미국 증시 요약 브리핑을 생성합니다.",
        "schedule": "화–토 08:00",
        "func": run_nasdaq_pipeline,
    },
    {
        "id": "news_dive",
        "name": "뉴스 딥다이브",
        "description": "주요 뉴스를 분석하고 관련 종목을 스크리닝합니다.",
        "schedule": "매일 09:00",
        "func": run_news_dive_pipeline,
    },
    {
        "id": "issue_dive",
        "name": "이슈 딥다이브",
        "description": "핵심 이슈를 선정해 심층 분석 기사를 작성합니다.",
        "schedule": "매일 10:00 / 15:00 / 21:00",
        "func": run_issue_dive_pipeline,
        "has_topic_input": True,
    },
    {
        "id": "real_estate",
        "name": "부동산 브리핑",
        "description": "부동산 시장 뉴스를 분석하고 브리핑을 생성합니다.",
        "schedule": "월요일 07:00",
        "func": run_real_estate_pipeline,
    },
    {
        "id": "stock_deep_dive",
        "name": "주식 딥다이브",
        "description": "개별 종목을 심층 분석합니다. 티커를 입력하거나 비워두면 AI가 자동 선정합니다.",
        "schedule": "매일 11:00",
        "func": run_stock_deep_dive_pipeline,
        "has_ticker_input": True,
        "has_html_option": True,
    },
    {
        "id": "chart_analysis",
        "name": "차트 기술적 분석",
        "description": "개별 종목의 기술적 분석 리포트를 생성합니다. (HTML 파일 출력)",
        "schedule": "수동 실행",
        "func": run_chart_analysis_pipeline,
        "has_ticker_input": True,
    },
    {
        "id": "portfolio",
        "name": "AI 포트폴리오",
        "description": "NASDAQ 100 기반 AI 가상 포트폴리오를 운용합니다. 일일 리뷰 + 이메일 발송.",
        "schedule": "화–토 08:30",
        "func": run_portfolio_pipeline,
    },
]

# ── 인메모리 실행 상태 ────────────────────────────────────────
_run_state: dict[str, dict[str, Any]] = {}


_USE_DEFAULT_EMAIL = {"portfolio"}  # 자체 기본 수신자를 사용하는 파이프라인


async def _execute(pipeline_id: str, func, **kwargs):
    """파이프라인을 실행하고 상태를 갱신한다."""
    try:
        if pipeline_id not in _USE_DEFAULT_EMAIL:
            kwargs.setdefault("email_to", [])
        run_id = await func(**kwargs)
        _run_state[pipeline_id].update(status="done", run_id=run_id)
    except Exception as e:
        logger.exception("Pipeline %s failed", pipeline_id)
        _run_state[pipeline_id].update(status="error", error=str(e))


# ── Routes ────────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
async def pipelines_page(request: Request, db: AsyncSession = Depends(get_db)):
    """파이프라인 관리 페이지."""
    today_kst = datetime.now(KST).date()
    today_start_utc = datetime(today_kst.year, today_kst.month, today_kst.day, tzinfo=KST).astimezone(timezone.utc)
    tomorrow_start_utc = today_start_utc + timedelta(days=1)

    # 오늘(KST) run 단위 집계 (최신순)
    result = await db.execute(
        select(
            AiTrace.pipeline,
            AiTrace.run_id,
            func.min(AiTrace.created_at).label("started_at"),
            func.min(case((AiTrace.success == False, 0), else_=1)).label("all_success"),
        )
        .where(AiTrace.created_at >= today_start_utc)
        .where(AiTrace.created_at < tomorrow_start_utc)
        .where(AiTrace.run_id != "")
        .group_by(AiTrace.pipeline, AiTrace.run_id)
        .order_by(func.min(AiTrace.created_at).desc())
    )
    rows = result.all()

    # 파이프라인별 run 리스트 (시간순)
    today_runs: dict[str, list[dict]] = {}
    for r in rows:
        today_runs.setdefault(r.pipeline, []).append({
            "run_id": r.run_id,
            "time": r.started_at.replace(tzinfo=timezone.utc).astimezone(KST).strftime("%H:%M"),
            "success": bool(r.all_success),
        })
    for runs in today_runs.values():
        runs.reverse()  # 시간순 정렬

    # 최근 7일 블로그 발행 내역
    week_ago = today_kst - timedelta(days=7)
    briefing_result = await db.execute(
        select(Briefing.id, Briefing.briefing_type, Briefing.title, Briefing.blog_url, Briefing.date)
        .where(Briefing.date >= week_ago, Briefing.blog_url != "", Briefing.blog_url.isnot(None))
        .order_by(Briefing.date.desc(), Briefing.created_at.asc())
    )

    # 오늘 발행 (기존 호환)
    published: dict[str, list[dict]] = {}
    # 최근 발행 (오늘 제외, 날짜별)
    recent_published: dict[str, list[dict]] = {}
    for b in briefing_result.all():
        for pid, btype in BRIEFING_TYPE_MAP.items():
            if b.briefing_type == btype and b.blog_url:
                entry = {
                    "id": b.id,
                    "title": b.title,
                    "blog_url": b.blog_url,
                    "date": b.date.strftime("%m/%d"),
                }
                if b.date == today_kst:
                    published.setdefault(pid, []).append(entry)
                else:
                    recent_published.setdefault(pid, []).append(entry)

    return templates.TemplateResponse("pipelines.html", {
        "request": request,
        "pipelines": PIPELINES,
        "today_runs": today_runs,
        "published": published,
        "recent_published": recent_published,
    })


@router.post("/{pipeline_id}/run")
async def run(pipeline_id: str, request: Request):
    """파이프라인을 백그라운드로 실행한다."""
    # 유효성 검증
    target = next((p for p in PIPELINES if p["id"] == pipeline_id), None)
    if target is None:
        return JSONResponse({"error": "Unknown pipeline"}, status_code=404)

    # 이미 실행 중이면 거부
    state = _run_state.get(pipeline_id)
    if state and state["status"] == "running":
        return JSONResponse({"error": "Already running"}, status_code=409)

    # 추가 파라미터 추출
    extra_kwargs: dict = {}
    body: dict = {}
    if target.get("has_ticker_input") or target.get("has_topic_input"):
        try:
            body = await request.json()
        except Exception:
            body = {}

    if target.get("has_ticker_input"):
        ticker_val = body.get("ticker", "").strip()
        if ticker_val:
            extra_kwargs["ticker"] = ticker_val

    if target.get("has_html_option") and body.get("html_only"):
        extra_kwargs["html_only"] = True

    if target.get("has_topic_input"):
        topic_val = body.get("topic", "").strip() if isinstance(body.get("topic"), str) else ""
        if topic_val:
            import json
            try:
                extra_kwargs["topic"] = json.loads(topic_val)
            except json.JSONDecodeError:
                return JSONResponse({"error": "Topic JSON 파싱 실패"}, status_code=400)

    # 상태 초기화 + 백그라운드 실행
    _run_state[pipeline_id] = {
        "status": "running",
        "run_id": None,
        "started_at": datetime.now(KST).isoformat(),
        "error": None,
    }
    asyncio.create_task(_execute(pipeline_id, target["func"], **extra_kwargs))

    return {"status": "running", "pipeline_id": pipeline_id}


@router.post("/{pipeline_id}/republish")
async def republish(pipeline_id: str, db: AsyncSession = Depends(get_db)):
    """오늘 생성된 브리핑을 WordPress에 재발행한다."""
    from app.pipeline.base import BriefingResult, WordPressPublisher, DBPublisher

    briefing_type = BRIEFING_TYPE_MAP.get(pipeline_id)
    if not briefing_type:
        return JSONResponse({"error": "Unknown pipeline"}, status_code=404)

    today_kst = datetime.now(KST).date()
    result = await db.execute(
        select(Briefing)
        .where(Briefing.date == today_kst, Briefing.briefing_type == briefing_type)
        .where((Briefing.blog_url == "") | (Briefing.blog_url.is_(None)))
        .order_by(Briefing.created_at.desc())
    )
    briefings = result.scalars().all()

    if not briefings:
        return JSONResponse({"error": "재발행할 브리핑이 없습니다."}, status_code=404)

    published = []
    for b in briefings:
        br = BriefingResult(
            title=b.title, html=b.content_html, excerpt=b.excerpt or "",
            slug=b.slug or "",
            tags=b.tags.split(",") if b.tags else [],
            focus_keyword=b.focus_keyword or "",
            image_keyword=b.image_keyword or "",
        )
        out = await WordPressPublisher().publish(br, briefing_type, briefing_id=b.id)
        blog_url = out.get("blog_url", "")
        if blog_url:
            published.append(blog_url)

    if not published:
        return JSONResponse({"error": "WordPress 발행에 실패했습니다."}, status_code=502)

    return {"status": "published", "count": len(published), "urls": published}


@router.post("/fix-featured-images")
async def fix_featured_images_endpoint():
    """기존 글의 대표 이미지를 Unsplash 이미지로 일괄 교체한다."""
    from app.publishing.wordpress import fix_featured_images
    result = await fix_featured_images()
    return result


TEASER_SYSTEM_PROMPT = """\
너는 블로그 교차 게시용 티저 작성 전문가야.
원문 HTML을 읽고, 네이버 블로그에 붙여넣기할 티저 HTML을 만들어.

## 규칙
- 반드시 **인라인 style 속성**만 사용 (네이버 에디터가 CSS class 무시)
- <div>, <style>, <class> 금지. <h2>, <p>, <a>, <span>, <strong> 만 사용
- 출력은 HTML만. 설명·마크다운·코드블록 없이 순수 HTML만 출력
- 아래 예시의 HTML 구조를 **그대로** 따르고, 텍스트 내용만 바꿔

## 출력 예시 (이 구조를 정확히 따를 것)

<h2 style="font-size:22px;font-weight:700;color:#191f28;margin:0 0 16px 0;line-height:1.4;">제목을 여기에</h2>
<p style="font-size:16px;line-height:1.8;color:#333;margin:0 0 12px 0;">도입 첫째 문단. 궁금증을 유발하되 핵심만 살짝 보여줌.</p>
<p style="font-size:16px;line-height:1.8;color:#333;margin:0 0 12px 0;">도입 둘째 문단.</p>
<p style="font-size:15px;font-weight:700;color:#191f28;margin:24px 0 8px 0;padding:12px 16px;background:#f7f8fa;border-left:4px solid #3182f6;line-height:1.4;">📌 이 글에서 다루는 내용</p>
<p style="font-size:14px;color:#333;margin:0 0 4px 20px;line-height:1.6;">• 섹션 제목 1</p>
<p style="font-size:14px;color:#333;margin:0 0 4px 20px;line-height:1.6;">• 섹션 제목 2</p>
<p style="font-size:14px;color:#333;margin:0 0 4px 20px;line-height:1.6;">• 섹션 제목 3</p>
<p style="font-size:15px;color:#6b7684;margin:20px 0 16px 0;line-height:1.6;">전체 분석과 차트, 관련 종목 데이터는 아래에서 확인하실 수 있어요.</p>
<p style="margin:0 0 20px 0;"><a href="URL" target="_blank" style="display:inline-block;padding:12px 28px;background:#3182f6;color:#fff;font-size:15px;font-weight:700;border-radius:8px;text-decoration:none;">전문 보기 →</a></p>
<p style="font-size:13px;color:#b0b8c1;margin:16px 0 0 0;">출처: 데일리머니다이브</p>

## 작성 지침
- 도입부 2~3문단: 원문 첫 부분을 자연스럽게 편집. 궁금증을 유발하되 핵심 내용은 살짝만 보여줌
- 📌 불릿: 원문 h2 섹션 제목을 나열 (이모지 제거)
- URL: 제공된 원문 링크로 교체
- margin은 반드시 margin:0 0 Xpx 0 형태로 (상하좌우 명시). margin-bottom 같은 축약 금지
"""


@router.get("/{pipeline_id}/teaser")
async def teaser(pipeline_id: str, briefing_id: int = 0, db: AsyncSession = Depends(get_db)):
    """LLM으로 네이버/티스토리용 티저 HTML을 생성한다."""
    from app.summarizer import ClaudeCliProvider

    briefing_type = BRIEFING_TYPE_MAP.get(pipeline_id)
    if not briefing_type:
        return JSONResponse({"error": "Unknown pipeline"}, status_code=404)

    if briefing_id:
        result = await db.execute(
            select(Briefing).where(Briefing.id == briefing_id)
        )
    else:
        today_kst = datetime.now(KST).date()
        result = await db.execute(
            select(Briefing)
            .where(
                Briefing.date == today_kst,
                Briefing.briefing_type == briefing_type,
                Briefing.blog_url != "",
                Briefing.blog_url.isnot(None),
            )
            .order_by(Briefing.created_at.desc())
            .limit(1)
        )
    briefing = result.scalar_one_or_none()
    if not briefing:
        return JSONResponse({"error": "오늘 발행된 브리핑이 없습니다."}, status_code=404)

    user_prompt = (
        f"제목: {briefing.title}\n"
        f"원문 링크: {briefing.blog_url}\n\n"
        f"원문 HTML:\n{briefing.content_html}"
    )

    system_prompt = TEASER_SYSTEM_PROMPT
    if pipeline_id == "real_estate":
        system_prompt += (
            "\n\n## 부동산 브리핑 추가 규칙\n"
            '- CTA 문구를 "자세한 내용은 아래 링크에서 확인하실 수 있어요."로 변경\n'
            "- 출처 위에 자연스럽게 한 문장을 추가해:\n"
            '"청약 일정과 분양 정보가 궁금하시다면 '
            '<a href="https://house-ping.com" target="_blank" '
            'style="color:#3182f6;font-weight:600;text-decoration:none;">'
            'house-ping.com</a>에서 한눈에 확인해보세요." 느낌으로.'
        )

    provider = ClaudeCliProvider(timeout=300)
    teaser_html = await asyncio.to_thread(provider.call, system_prompt, user_prompt)
    # 혹시 코드블록으로 감싸져 있으면 제거
    teaser_html = teaser_html.strip()
    if teaser_html.startswith("```"):
        teaser_html = teaser_html.split("\n", 1)[1]
    if teaser_html.endswith("```"):
        teaser_html = teaser_html.rsplit("```", 1)[0]
    teaser_html = teaser_html.strip()

    # 태그 추출 (네이버 블로그용)
    tags = [t.strip() for t in (briefing.tags or "").split(",") if t.strip()]
    # focus_keyword를 태그 맨 앞에
    if briefing.focus_keyword and briefing.focus_keyword not in tags:
        tags.insert(0, briefing.focus_keyword)

    return {"teaser_html": teaser_html, "blog_url": briefing.blog_url, "tags": tags}


@router.get("/{pipeline_id}/tags")
async def get_tags(pipeline_id: str, briefing_id: int = 0, db: AsyncSession = Depends(get_db)):
    """브리핑의 태그를 반환한다."""
    briefing_type = BRIEFING_TYPE_MAP.get(pipeline_id)
    if not briefing_type:
        return JSONResponse({"error": "Unknown pipeline"}, status_code=404)

    if briefing_id:
        result = await db.execute(select(Briefing).where(Briefing.id == briefing_id))
    else:
        today_kst = datetime.now(KST).date()
        result = await db.execute(
            select(Briefing)
            .where(Briefing.date == today_kst, Briefing.briefing_type == briefing_type)
            .order_by(Briefing.created_at.desc())
            .limit(1)
        )
    briefing = result.scalar_one_or_none()
    if not briefing:
        return JSONResponse({"error": "브리핑 없음"}, status_code=404)

    tags = [t.strip() for t in (briefing.tags or "").split(",") if t.strip()]
    if briefing.focus_keyword and briefing.focus_keyword not in tags:
        tags.insert(0, briefing.focus_keyword)

    return {"tags": tags}


@router.get("/status")
async def status():
    """전체 파이프라인 실행 상태를 반환한다 (폴링용)."""
    return _run_state

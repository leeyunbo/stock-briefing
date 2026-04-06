"""AI 트레이스 브라우저 — run 단위 파이프라인 흐름 열람."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.models import AiTrace

router = APIRouter(prefix="/traces")
templates = Jinja2Templates(directory="templates")

KST = timezone(timedelta(hours=9))


def _to_kst(dt: datetime) -> datetime:
    """UTC datetime을 KST로 변환한다."""
    return dt.replace(tzinfo=timezone.utc).astimezone(KST)


templates.env.filters["kst"] = _to_kst

PAGE_SIZE = 20

# 파이프라인 한글 표시명
PIPELINE_LABELS = {
    "kospi": "KOSPI 브리핑",
    "nasdaq": "NASDAQ 브리핑",
    "news_dive": "뉴스 딥다이브",
    "deep_research": "딥리서치",
    "real_estate": "부동산 브리핑",
}


_TOKEN_COSTS: dict[str, tuple[float, float]] = {
    # model_prefix: (input_cost_per_mtok, output_cost_per_mtok)
    "claude-sonnet": (3.0, 15.0),
    "claude-opus": (15.0, 75.0),
    "claude-haiku": (0.25, 1.25),
    "gemini-2.0-flash": (0.10, 0.40),
    "gemini-2.5-flash": (0.15, 0.60),
    "gemini-2.5-pro": (1.25, 10.0),
}


def _estimate_cost(model_name: str, input_tokens: int, output_tokens: int) -> float:
    """모델명과 토큰 수로 예상 비용(USD)을 계산한다."""
    for prefix, (input_cost, output_cost) in _TOKEN_COSTS.items():
        if prefix in (model_name or ""):
            return (input_tokens * input_cost + output_tokens * output_cost) / 1_000_000
    return 0.0


@router.get("", response_class=HTMLResponse)
async def traces_list(
    request: Request,
    pipeline: str = "",
    date_from: str = "",
    date_to: str = "",
    page: int = Query(default=1, ge=1),
    db: AsyncSession = Depends(get_db),
):
    """run_id 단위로 그룹핑된 파이프라인 실행 목록."""
    # 필터 조건
    filters = []
    if pipeline:
        filters.append(AiTrace.pipeline == pipeline)
    if date_from:
        filters.append(AiTrace.created_at >= datetime.fromisoformat(date_from))
    if date_to:
        filters.append(AiTrace.created_at < datetime.fromisoformat(date_to) + timedelta(days=1))

    # 토큰 합계 (필터 적용)
    token_query = select(
        func.coalesce(func.sum(AiTrace.input_tokens), 0).label("total_input"),
        func.coalesce(func.sum(AiTrace.output_tokens), 0).label("total_output"),
    ).where(AiTrace.run_id != "")
    if filters:
        token_query = token_query.where(*filters)
    token_result = await db.execute(token_query)
    token_row = token_result.one()
    total_input_tokens = token_row.total_input
    total_output_tokens = token_row.total_output

    # 모델별 비용 계산
    cost_query = select(
        AiTrace.model_name,
        func.coalesce(func.sum(AiTrace.input_tokens), 0).label("input_sum"),
        func.coalesce(func.sum(AiTrace.output_tokens), 0).label("output_sum"),
    ).where(AiTrace.run_id != "").group_by(AiTrace.model_name)
    if filters:
        cost_query = cost_query.where(*filters)
    cost_result = await db.execute(cost_query)
    total_cost = sum(
        _estimate_cost(r.model_name, r.input_sum, r.output_sum) for r in cost_result.all()
    )

    # run_id 기준 그룹 집계
    group_query = (
        select(
            AiTrace.run_id,
            AiTrace.pipeline,
            func.min(AiTrace.created_at).label("started_at"),
            func.count().label("stage_count"),
            func.sum(AiTrace.latency_ms).label("total_latency_ms"),
            func.sum(AiTrace.input_tokens).label("total_input_tokens"),
            func.sum(AiTrace.output_tokens).label("total_output_tokens"),
            func.min(case((AiTrace.success == False, 0), else_=1)).label("all_success"),
        )
        .where(AiTrace.run_id != "")
        .where(*filters)
        .group_by(AiTrace.run_id)
    )

    # 전체 건수
    count_result = await db.execute(select(func.count()).select_from(group_query.subquery()))
    total = count_result.scalar() or 0
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)

    # 페이지네이션
    offset = (page - 1) * PAGE_SIZE
    rows_result = await db.execute(
        group_query.order_by(func.min(AiTrace.created_at).desc()).offset(offset).limit(PAGE_SIZE)
    )
    runs = rows_result.all()

    # 파이프라인 목록 (필터용)
    pipelines_result = await db.execute(
        select(AiTrace.pipeline).distinct().order_by(AiTrace.pipeline)
    )
    pipelines = [r[0] for r in pipelines_result.all()]

    return templates.TemplateResponse("traces_list.html", {
        "request": request,
        "runs": runs,
        "pipelines": pipelines,
        "pipeline_labels": PIPELINE_LABELS,
        "selected_pipeline": pipeline,
        "date_from": date_from,
        "date_to": date_to,
        "page": page,
        "total_pages": total_pages,
        "total": total,
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "total_cost": total_cost,
    })


@router.get("/run/{run_id}", response_class=HTMLResponse)
async def run_detail(
    request: Request,
    run_id: str,
    db: AsyncSession = Depends(get_db),
):
    """run_id에 속한 모든 트레이스를 시간순으로 보여준다."""
    result = await db.execute(
        select(AiTrace)
        .where(AiTrace.run_id == run_id)
        .order_by(AiTrace.created_at.asc())
    )
    traces = result.scalars().all()

    if not traces:
        return HTMLResponse("<h1>실행 기록을 찾을 수 없습니다.</h1>", status_code=404)

    pipeline = traces[0].pipeline
    total_latency = sum(t.latency_ms for t in traces)
    all_success = all(t.success for t in traces)
    total_input = sum(t.input_tokens or 0 for t in traces)
    total_output = sum(t.output_tokens or 0 for t in traces)
    total_cost = sum(
        _estimate_cost(t.model_name, t.input_tokens or 0, t.output_tokens or 0) for t in traces
    )

    return templates.TemplateResponse("trace_detail.html", {
        "request": request,
        "run_id": run_id,
        "traces": traces,
        "pipeline": pipeline,
        "pipeline_label": PIPELINE_LABELS.get(pipeline, pipeline),
        "total_latency": total_latency,
        "all_success": all_success,
        "total_input": total_input,
        "total_output": total_output,
        "total_cost": total_cost,
    })

"""AI 호출 트레이싱 — TracingProvider 래퍼.

기존 AiProvider를 감싸서, call() 실행 시 자동으로:
- 소요시간(latency_ms) 측정
- 토큰 수(input_tokens/output_tokens) 수집 (가능한 경우)
- ai_traces 테이블에 동기 저장

저장 실패해도 파이프라인은 멈추지 않는다 (try-except + warning log).
"""

import logging
import time
import uuid

from sqlalchemy.orm import Session

from app.core.database import sync_engine
from app.core.models import AiTrace

logger = logging.getLogger(__name__)


def generate_run_id() -> str:
    """파이프라인 실행 단위의 고유 ID를 생성한다."""
    return uuid.uuid4().hex[:12]


class TracingProvider:
    """기존 AiProvider를 감싸는 트레이싱 래퍼."""

    def __init__(
        self,
        provider,
        provider_name: str,
        model_name: str,
        pipeline: str,
        stage: str,
        run_id: str = "",
    ):
        self._provider = provider
        self._provider_name = provider_name
        self._model_name = model_name
        self._pipeline = pipeline
        self._stage = stage
        self._run_id = run_id

    def call(self, system_prompt: str, user_prompt: str) -> str:
        start = time.monotonic()
        input_tokens = None
        output_tokens = None
        response_text = ""
        success = True
        error_message = None

        try:
            response_text = self._provider.call(system_prompt, user_prompt)

            # 토큰 수집 — provider 내부 last_usage에서 가져온다
            usage = getattr(self._provider, "last_usage", None)
            if usage:
                input_tokens = usage.get("input_tokens")
                output_tokens = usage.get("output_tokens")

            return response_text
        except Exception as e:
            success = False
            error_message = str(e)[:1000]
            raise
        finally:
            latency_ms = int((time.monotonic() - start) * 1000)
            _save_trace_sync(
                run_id=self._run_id,
                pipeline=self._pipeline,
                stage=self._stage,
                provider_name=self._provider_name,
                model_name=self._model_name,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response=response_text,
                latency_ms=latency_ms,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                success=success,
                error_message=error_message,
            )


def get_cli_provider(timeout: int, pipeline: str, stage: str, run_id: str = "") -> TracingProvider:
    """ClaudeCliProvider를 TracingProvider로 감싸서 반환한다."""
    from app.summarizer import ClaudeCliProvider

    return TracingProvider(
        provider=ClaudeCliProvider(timeout=timeout),
        provider_name="claude-cli",
        model_name="claude-cli",
        pipeline=pipeline,
        stage=stage,
        run_id=run_id,
    )


def _save_trace_sync(
    *,
    run_id: str,
    pipeline: str,
    stage: str,
    provider_name: str,
    model_name: str,
    system_prompt: str,
    user_prompt: str,
    response: str,
    latency_ms: int,
    input_tokens: int | None,
    output_tokens: int | None,
    success: bool,
    error_message: str | None,
) -> None:
    """동기 SQLite로 트레이스를 저장한다. 실패해도 파이프라인을 멈추지 않는다."""
    try:
        with Session(sync_engine) as session:
            trace = AiTrace(
                run_id=run_id,
                pipeline=pipeline,
                stage=stage,
                provider_name=provider_name,
                model_name=model_name,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response=response,
                latency_ms=latency_ms,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                success=success,
                error_message=error_message,
            )
            session.add(trace)
            session.commit()
    except Exception as e:
        logger.warning("트레이스 저장 실패 (파이프라인 계속 진행): %s", e)

"""로깅 설정 — 스프링의 logback-spring.xml 역할.

파이썬 logging 핵심:
- getLogger(__name__) → 모듈 경로가 로거 이름 (스프링의 패키지 기반 로거와 동일)
- 레벨: DEBUG < INFO < WARNING < ERROR < CRITICAL
- lazy formatting: logger.info("count: %d", count) → 로그 안 찍히면 포매팅 안 함
"""

import contextvars
import logging

correlation_id: contextvars.ContextVar[str] = contextvars.ContextVar("correlation_id", default="-")


class CorrelationIdFilter(logging.Filter):
    """로그 레코드에 correlation_id를 추가한다."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = correlation_id.get()
        return True


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] [%(correlation_id)s] %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logging.getLogger().addFilter(CorrelationIdFilter())

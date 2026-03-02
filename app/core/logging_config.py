"""로깅 설정."""

import contextvars
import logging

correlation_id: contextvars.ContextVar[str] = contextvars.ContextVar("correlation_id", default="-")


class CorrelationIdFilter(logging.Filter):
    """로그 레코드에 correlation_id를 추가한다."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "correlation_id"):
            record.correlation_id = correlation_id.get()
        return True


class SafeFormatter(logging.Formatter):
    """correlation_id가 없는 레코드에도 안전하게 동작하는 포매터."""

    def format(self, record: logging.LogRecord) -> str:
        if not hasattr(record, "correlation_id"):
            record.correlation_id = correlation_id.get()
        return super().format(record)


def setup_logging() -> None:
    fmt = SafeFormatter(
        fmt="%(asctime)s [%(levelname)s] [%(correlation_id)s] %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler = logging.StreamHandler()
    handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    root.addFilter(CorrelationIdFilter())

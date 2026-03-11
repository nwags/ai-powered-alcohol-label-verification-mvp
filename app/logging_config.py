import logging
from collections import deque

RECENT_LOG_BUFFER_MAX = 300
_recent_logs: deque[str] = deque(maxlen=RECENT_LOG_BUFFER_MAX)


class RingBufferLogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
        except Exception:  # pragma: no cover - defensive path
            message = record.getMessage()
        _recent_logs.append(message)


def configure_logging(log_level: str = "INFO") -> None:
    resolved_level = getattr(logging, log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=resolved_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    root_logger = logging.getLogger()
    if not any(isinstance(handler, RingBufferLogHandler) for handler in root_logger.handlers):
        ring_handler = RingBufferLogHandler()
        ring_handler.setLevel(resolved_level)
        ring_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        root_logger.addHandler(ring_handler)

    noisy_logger_names = [
        "httpx",
        "httpcore",
        "urllib3",
        "huggingface_hub",
        "filelock",
    ]
    for logger_name in noisy_logger_names:
        logging.getLogger(logger_name).setLevel(logging.WARNING)


def get_recent_logs(limit: int = 200) -> list[str]:
    if limit <= 0:
        return []
    return list(_recent_logs)[-limit:]

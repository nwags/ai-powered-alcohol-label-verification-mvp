import logging
import uuid

from app.logging_config import configure_logging, get_recent_logs


def test_recent_logs_capture_root_logger_messages():
    configure_logging("INFO")
    marker = f"diag-root-{uuid.uuid4().hex}"
    logging.getLogger("app.test").info(marker)

    assert any(marker in line for line in get_recent_logs(300))


def test_recent_logs_capture_uvicorn_logger_messages():
    configure_logging("INFO")
    marker = f"diag-uvicorn-{uuid.uuid4().hex}"
    logging.getLogger("uvicorn.error").info(marker)

    assert any(marker in line for line in get_recent_logs(300))

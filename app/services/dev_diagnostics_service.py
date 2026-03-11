from __future__ import annotations

import logging
import subprocess
import threading
from pathlib import Path
from typing import Any

from app.logging_config import get_recent_logs


class DevDiagnosticsService:
    def __init__(self, coverage_dir: Path) -> None:
        self.coverage_dir = coverage_dir
        self._lock = threading.Lock()
        self._state = "idle"
        self._last_message = "No coverage run has been started."
        self._last_exit_code: int | None = None

    def coverage_status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "state": self._state,
                "message": self._last_message,
                "last_exit_code": self._last_exit_code,
            }

    def trigger_coverage(self) -> bool:
        with self._lock:
            if self._state == "running":
                return False
            self._state = "running"
            self._last_message = "Coverage generation is running."
            self._last_exit_code = None
        thread = threading.Thread(target=self._run_coverage, daemon=True)
        thread.start()
        return True

    def recent_logs(self, limit: int = 200) -> list[str]:
        return get_recent_logs(limit=limit)

    def _run_coverage(self) -> None:
        logger = logging.getLogger("app.diagnostics")
        coverage_json = self.coverage_dir / "coverage.json"
        coverage_html = self.coverage_dir / "html"
        coverage_html.mkdir(parents=True, exist_ok=True)
        command = [
            "python",
            "-m",
            "pytest",
            "-q",
            "--cov=app",
            "--cov-report=term-missing",
            f"--cov-report=html:{coverage_html}",
            f"--cov-report=json:{coverage_json}",
        ]
        logger.info("Starting coverage generation command: %s", " ".join(command))
        repo_root = Path(__file__).resolve().parents[2]
        try:
            completed = subprocess.run(command, cwd=str(repo_root), capture_output=True, text=True, check=False)
        except Exception as exc:  # pragma: no cover - defensive path
            with self._lock:
                self._state = "failure"
                self._last_message = f"Coverage generation failed to start: {exc.__class__.__name__}"
                self._last_exit_code = -1
            logger.exception("Coverage generation failed before execution.")
            return

        if completed.stdout:
            logger.info("Coverage stdout:\n%s", completed.stdout.strip())
        if completed.stderr:
            logger.warning("Coverage stderr:\n%s", completed.stderr.strip())

        with self._lock:
            self._last_exit_code = completed.returncode
            if completed.returncode == 0:
                self._state = "success"
                self._last_message = "Coverage generation completed successfully."
            else:
                self._state = "failure"
                self._last_message = f"Coverage generation failed with exit code {completed.returncode}."

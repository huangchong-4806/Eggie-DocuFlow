import logging
import logging.handlers
import os
import queue
import shutil
import uuid
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

from utils.file_helper import available_output_path
from version import APP_VERSION


STEP_LEVEL = 25
logging.addLevelName(STEP_LEVEL, "STEP")


def default_log_root():
    configured = os.environ.get("EGGIE_LOG_DIR")
    return Path(configured) if configured else Path.home() / ".eggie_excel_tool" / "logs"


def clean_old_logs(log_root):
    cutoff = date.today() - timedelta(days=7)
    if not log_root.exists():
        return
    for child in log_root.iterdir():
        if not child.is_dir():
            continue
        try:
            folder_date = datetime.strptime(child.name, "%Y-%m-%d").date()
        except ValueError:
            continue
        if folder_date < cutoff:
            try:
                shutil.rmtree(child)
            except OSError:
                pass


class SessionLogger:
    def __init__(self, log_root=None):
        self.log_root = Path(log_root) if log_root else default_log_root()
        clean_old_logs(self.log_root)
        day_folder = self.log_root / date.today().isoformat()
        day_folder.mkdir(parents=True, exist_ok=True)
        session_id = uuid.uuid4().hex[:12]
        formatter = logging.Formatter(
            f"%(asctime)s | %(levelname)s | version={APP_VERSION} | %(message)s",
            "%Y-%m-%d %H:%M:%S",
        )

        handlers = []
        for filename, level in (
            ("app.log", logging.INFO),
            ("error.log", logging.ERROR),
            (f"session-{session_id}.log", logging.INFO),
        ):
            handler = logging.FileHandler(day_folder / filename, encoding="utf-8")
            handler.setLevel(level)
            handler.setFormatter(formatter)
            handlers.append(handler)

        self._queue = queue.Queue()
        self._listener = logging.handlers.QueueListener(
            self._queue, *handlers, respect_handler_level=True
        )
        self.logger = logging.getLogger(f"eggie.document.{session_id}")
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        self.logger.handlers = [logging.handlers.QueueHandler(self._queue)]
        self._handlers = handlers
        self._listener.start()

    def info(self, message):
        self.logger.info(message)

    def step(self, message):
        self.logger.log(STEP_LEVEL, message)

    def error(self, message, exc_info=False):
        self.logger.error(message, exc_info=exc_info)

    def close(self):
        self._listener.stop()
        self.logger.handlers.clear()
        for handler in self._handlers:
            handler.close()


def export_logs(output_zip, log_root=None):
    """Export app, error, and session logs to one ZIP without overwriting files."""
    log_root = Path(log_root) if log_root else default_log_root()
    if not log_root.is_dir():
        raise FileNotFoundError("没有可导出的日志。")
    output_zip = Path(output_zip).expanduser().resolve()
    if output_zip.suffix.lower() != ".zip":
        output_zip = output_zip.with_suffix(".zip")
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    output_zip = available_output_path(output_zip)

    with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as archive:
        for source in sorted(log_root.rglob("*.log")):
            archive.write(source, source.relative_to(log_root))
    return str(output_zip)

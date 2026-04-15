import logging
import logging.handlers
from pathlib import Path


def setup_logging() -> None:
    """Configure structured logging to stdout and a rotating file sink."""
    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    date_format = "%Y-%m-%dT%H:%M:%S"

    # Ensure logs directory exists
    logs_dir = Path(__file__).parents[3] / "logs"
    logs_dir.mkdir(exist_ok=True)

    log_file = logs_dir / "app.log"

    root_logger = logging.getLogger()

    # Avoid adding duplicate handlers on reload (e.g. uvicorn --reload)
    if root_logger.handlers:
        return

    root_logger.setLevel(logging.INFO)

    # Stdout handler
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(logging.Formatter(log_format, datefmt=date_format))
    root_logger.addHandler(stream_handler)

    # Rotating file handler — 10 MB per file, keep 5 backups
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter(log_format, datefmt=date_format))
    root_logger.addHandler(file_handler)

    # Quiet noisy third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

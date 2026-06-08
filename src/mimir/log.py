import logging
from pathlib import Path

# Library-friendly: no output unless the caller configures a handler.
logging.getLogger("mimir").addHandler(logging.NullHandler())

_FMT = "%(asctime)s %(levelname)-8s %(message)s"
_DATE_FMT = "%Y-%m-%dT%H:%M:%S"


def get_logger() -> logging.Logger:
    return logging.getLogger("mimir")


def configure(log_file: str | Path, level: str = "INFO") -> None:
    """Attach a rotating file handler to the mimir logger."""
    logger = logging.getLogger("mimir")
    path = Path(log_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter(_FMT, datefmt=_DATE_FMT))
    logger.addHandler(handler)
    logger.setLevel(level.upper())

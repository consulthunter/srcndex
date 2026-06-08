import logging
from pathlib import Path

from mimir.log import configure, get_logger


def test_get_logger_returns_mimir_logger() -> None:
    assert get_logger().name == "mimir"


def test_configure_creates_log_file(tmp_path: Path) -> None:
    log_file = tmp_path / "mimir.log"
    configure(log_file, "DEBUG")
    get_logger().info("hello from test")
    assert log_file.exists()
    assert "hello from test" in log_file.read_text(encoding="utf-8")
    # clean up handler so it doesn't bleed into other tests
    logger = logging.getLogger("mimir")
    for h in logger.handlers[:]:
        if isinstance(h, logging.FileHandler) and Path(h.baseFilename) == log_file:
            h.close()
            logger.removeHandler(h)


def test_configure_creates_parent_dirs(tmp_path: Path) -> None:
    log_file = tmp_path / "logs" / "sub" / "mimir.log"
    configure(log_file, "INFO")
    get_logger().info("nested dir test")
    assert log_file.exists()
    logger = logging.getLogger("mimir")
    for h in logger.handlers[:]:
        if isinstance(h, logging.FileHandler) and Path(h.baseFilename) == log_file:
            h.close()
            logger.removeHandler(h)


def test_configure_respects_log_level(tmp_path: Path) -> None:
    log_file = tmp_path / "level_test.log"
    configure(log_file, "WARNING")
    get_logger().debug("should not appear")
    get_logger().warning("should appear")
    content = log_file.read_text(encoding="utf-8")
    assert "should not appear" not in content
    assert "should appear" in content
    logger = logging.getLogger("mimir")
    for h in logger.handlers[:]:
        if isinstance(h, logging.FileHandler) and Path(h.baseFilename) == log_file:
            h.close()
            logger.removeHandler(h)

import time
from pathlib import Path

from mimir.config import MimirConfig
from mimir.watcher import EventKind, FileChangedEvent, Watcher


def _drain(watcher: Watcher, timeout: float = 2.0) -> list[FileChangedEvent]:
    """Collect events for up to `timeout` seconds using poll()."""
    events: list[FileChangedEvent] = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        event = watcher.poll(timeout=min(0.1, max(remaining, 0)))
        if event is not None:
            events.append(event)
    return events


def test_created_event(tmp_path: Path) -> None:
    with Watcher(tmp_path) as watcher:
        time.sleep(0.1)
        (tmp_path / "Service.java").write_text("public class Service {}")
        events = _drain(watcher)

    assert any(e.kind == EventKind.CREATED and "Service.java" in e.path for e in events)


def test_modified_event(tmp_path: Path) -> None:
    f = tmp_path / "Service.java"
    f.write_text("public class Service {}")
    with Watcher(tmp_path) as watcher:
        time.sleep(0.1)
        f.write_text("public class Service { void run() {} }")
        events = _drain(watcher)

    assert any(e.kind == EventKind.MODIFIED and "Service.java" in e.path for e in events)


def test_deleted_event(tmp_path: Path) -> None:
    f = tmp_path / "Service.java"
    f.write_text("public class Service {}")
    with Watcher(tmp_path) as watcher:
        time.sleep(0.1)
        f.unlink()
        events = _drain(watcher)

    assert any(e.kind == EventKind.DELETED and "Service.java" in e.path for e in events)


def test_non_source_files_ignored(tmp_path: Path) -> None:
    with Watcher(tmp_path) as watcher:
        time.sleep(0.1)
        (tmp_path / "archive.zip").write_bytes(b"PK")
        (tmp_path / "image.png").write_bytes(b"\x89PNG")
        (tmp_path / "binary.bin").write_bytes(b"\x00\x01\x02")
        events = _drain(watcher, timeout=0.5)

    assert len(events) == 0


def test_rel_path_is_posix(tmp_path: Path) -> None:
    sub = tmp_path / "src" / "main"
    sub.mkdir(parents=True)
    with Watcher(tmp_path) as watcher:
        time.sleep(0.1)
        (sub / "App.java").write_text("public class App {}")
        events = _drain(watcher)

    created = [e for e in events if "App.java" in e.path]
    assert created
    assert created[0].rel_path == "src/main/App.java"
    assert "\\" not in created[0].rel_path


def test_context_manager_stops_cleanly(tmp_path: Path) -> None:
    watcher = Watcher(tmp_path)
    watcher.start()
    watcher.stop()
    assert not watcher._observer.is_alive()


def test_multiple_languages_watched(tmp_path: Path) -> None:
    with Watcher(tmp_path) as watcher:
        time.sleep(0.1)
        (tmp_path / "App.java").write_text("public class App {}")
        (tmp_path / "service.py").write_text("class Service: pass")
        (tmp_path / "util.ts").write_text("class Util {}")
        (tmp_path / "component.cs").write_text("public class Component {}")
        events = _drain(watcher)

    extensions = {Path(e.path).suffix for e in events if e.kind == EventKind.CREATED}
    assert ".java" in extensions
    assert ".py" in extensions
    assert ".ts" in extensions
    assert ".cs" in extensions


def test_tracked_extensions_watched(tmp_path: Path) -> None:
    with Watcher(tmp_path) as watcher:
        time.sleep(0.1)
        (tmp_path / "config.yml").write_text("key: value")
        (tmp_path / "settings.json").write_text("{}")
        (tmp_path / "README.md").write_text("# docs")
        (tmp_path / "deploy.sh").write_text("#!/bin/bash")
        events = _drain(watcher)

    created = {Path(e.path).suffix for e in events if e.kind == EventKind.CREATED}
    assert ".yml" in created
    assert ".json" in created
    assert ".md" in created
    assert ".sh" in created


def test_tracked_names_watched(tmp_path: Path) -> None:
    with Watcher(tmp_path) as watcher:
        time.sleep(0.1)
        (tmp_path / "Dockerfile").write_text("FROM python:3.13")
        (tmp_path / "Makefile").write_text("build:\n\tmvn package")
        events = _drain(watcher)

    names = {Path(e.path).name for e in events if e.kind == EventKind.CREATED}
    assert "Dockerfile" in names
    assert "Makefile" in names


def test_untracked_files_still_ignored(tmp_path: Path) -> None:
    with Watcher(tmp_path) as watcher:
        time.sleep(0.1)
        (tmp_path / "archive.zip").write_bytes(b"PK")
        (tmp_path / "image.png").write_bytes(b"\x89PNG")
        events = _drain(watcher, timeout=0.5)

    assert len(events) == 0


def test_watch_tracked_files_false_ignores_yaml(tmp_path: Path) -> None:
    cfg = MimirConfig(watch_tracked_files=False, exclude_dirs=[])
    with Watcher(tmp_path, config=cfg) as watcher:
        time.sleep(0.1)
        (tmp_path / "config.yml").write_text("key: value")
        (tmp_path / "Service.java").write_text("class S {}")
        events = _drain(watcher)

    paths = {Path(e.path).name for e in events}
    assert "Service.java" in paths
    assert "config.yml" not in paths


def test_watcher_exclude_dir(tmp_path: Path) -> None:
    vendor = tmp_path / "vendor"
    vendor.mkdir()
    cfg = MimirConfig(exclude_dirs=["vendor"])
    with Watcher(tmp_path, config=cfg) as watcher:
        time.sleep(0.1)
        (vendor / "Lib.java").write_text("class Lib {}")
        (tmp_path / "App.java").write_text("class App {}")
        events = _drain(watcher)

    names = {Path(e.path).name for e in events}
    assert "App.java" in names
    assert "Lib.java" not in names


def test_watcher_exclude_file(tmp_path: Path) -> None:
    cfg = MimirConfig(exclude_files=["package-lock.json"], exclude_dirs=[])
    with Watcher(tmp_path, config=cfg) as watcher:
        time.sleep(0.1)
        (tmp_path / "package-lock.json").write_text("{}")
        (tmp_path / "tsconfig.json").write_text("{}")
        events = _drain(watcher)

    names = {Path(e.path).name for e in events}
    assert "tsconfig.json" in names
    assert "package-lock.json" not in names


def test_watcher_exclude_extension(tmp_path: Path) -> None:
    cfg = MimirConfig(exclude_extensions=[".md"], exclude_dirs=[])
    with Watcher(tmp_path, config=cfg) as watcher:
        time.sleep(0.1)
        (tmp_path / "README.md").write_text("# docs")
        (tmp_path / "App.java").write_text("class App {}")
        events = _drain(watcher)

    names = {Path(e.path).name for e in events}
    assert "App.java" in names
    assert "README.md" not in names

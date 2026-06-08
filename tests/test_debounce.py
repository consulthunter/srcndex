import time
from pathlib import Path

from mimir.config import MimirConfig
from mimir.debounce import Debouncer
from mimir.watcher import EventKind, Watcher


def test_debouncer_batches_events(tmp_path: Path) -> None:
    cfg = MimirConfig(debounce_seconds=0.2, exclude_dirs=[])
    with Debouncer(Watcher(tmp_path, config=cfg), quiet_seconds=0.2) as d:
        time.sleep(0.05)
        (tmp_path / "A.java").write_text("class A {}")
        (tmp_path / "B.java").write_text("class B {}")
        time.sleep(0.05)
        (tmp_path / "C.java").write_text("class C {}")
        batch = d.wait()

    assert batch is not None
    names = {Path(e.path).name for e in batch}
    assert "A.java" in names
    assert "B.java" in names
    assert "C.java" in names


def test_debouncer_resets_on_new_event(tmp_path: Path) -> None:
    quiet = 0.3
    cfg = MimirConfig(exclude_dirs=[])
    with Debouncer(Watcher(tmp_path, config=cfg), quiet_seconds=quiet) as d:
        time.sleep(0.05)
        (tmp_path / "A.java").write_text("class A {}")
        time.sleep(quiet * 0.5)
        (tmp_path / "B.java").write_text("class B {}")  # resets timer
        batch = d.wait()

    assert batch is not None
    names = {Path(e.path).name for e in batch}
    assert "A.java" in names
    assert "B.java" in names


def test_debouncer_returns_none_when_stopped_with_no_events(tmp_path: Path) -> None:
    cfg = MimirConfig(exclude_dirs=[])
    watcher = Watcher(tmp_path, config=cfg)
    d = Debouncer(watcher, quiet_seconds=0.1)
    watcher.start()
    watcher.stop()
    result = d.wait()
    assert result is None


def test_debouncer_context_manager_starts_and_stops(tmp_path: Path) -> None:
    cfg = MimirConfig(exclude_dirs=[])
    watcher = Watcher(tmp_path, config=cfg)
    d = Debouncer(watcher, quiet_seconds=0.1)
    with d:
        assert watcher._observer.is_alive()
    assert not watcher._observer.is_alive()


def test_debouncer_batches_generator(tmp_path: Path) -> None:
    cfg = MimirConfig(exclude_dirs=[])
    collected: list = []
    with Debouncer(Watcher(tmp_path, config=cfg), quiet_seconds=0.2) as d:
        time.sleep(0.05)
        (tmp_path / "Service.java").write_text("class Service {}")
        batch = next(d.batches())
        collected.extend(batch)

    assert any("Service.java" in e.path for e in collected)


def test_debouncer_contains_created_event(tmp_path: Path) -> None:
    cfg = MimirConfig(exclude_dirs=[])
    with Debouncer(Watcher(tmp_path, config=cfg), quiet_seconds=0.2) as d:
        time.sleep(0.05)
        (tmp_path / "X.java").write_text("class X {}")
        batch = d.wait()

    assert batch is not None
    assert any(e.kind == EventKind.CREATED and "X.java" in e.path for e in batch)

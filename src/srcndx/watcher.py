import queue
import threading
from collections.abc import Generator
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from watchdog.events import (
    FileCreatedEvent,
    FileDeletedEvent,
    FileModifiedEvent,
    FileMovedEvent,
    FileSystemEvent,
    FileSystemEventHandler,
)
from watchdog.observers import Observer

from srcndx.config import SrcndxConfig, load_config
from srcndx.scanner import _PARSERS, _TRACKED_EXTENSIONS, _TRACKED_NAMES


class EventKind(StrEnum):
    CREATED = "created"
    MODIFIED = "modified"
    DELETED = "deleted"


@dataclass(frozen=True)
class FileChangedEvent:
    path: str
    rel_path: str
    kind: EventKind


class _Handler(FileSystemEventHandler):
    def __init__(
        self,
        repo_root: Path,
        extensions: frozenset[str],
        tracked_names: dict[str, str],
        out: "queue.Queue[FileChangedEvent]",
        exclude_dirs: frozenset[str],
        exclude_extensions: frozenset[str],
        exclude_files: frozenset[str],
    ) -> None:
        self._root = repo_root
        self._extensions = extensions
        self._tracked_names = tracked_names
        self._out = out
        self._exclude_dirs = exclude_dirs
        self._exclude_extensions = exclude_extensions
        self._exclude_files = exclude_files

    def _emit(self, src: str, kind: EventKind) -> None:
        p = Path(src)
        if p.suffix.lower() not in self._extensions and p.name not in self._tracked_names:
            return
        try:
            rel = p.relative_to(self._root)
        except ValueError:
            return
        parts = rel.parts
        if any(part in self._exclude_dirs for part in parts[:-1]):
            return
        if p.suffix.lower() in self._exclude_extensions:
            return
        if p.name in self._exclude_files:
            return
        self._out.put(FileChangedEvent(path=str(p), rel_path=rel.as_posix(), kind=kind))

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory and isinstance(event, FileCreatedEvent):
            self._emit(event.src_path, EventKind.CREATED)

    def on_modified(self, event: FileSystemEvent) -> None:
        if not event.is_directory and isinstance(event, FileModifiedEvent):
            self._emit(event.src_path, EventKind.MODIFIED)

    def on_deleted(self, event: FileSystemEvent) -> None:
        if not event.is_directory and isinstance(event, FileDeletedEvent):
            self._emit(event.src_path, EventKind.DELETED)

    def on_moved(self, event: FileSystemEvent) -> None:
        if not event.is_directory and isinstance(event, FileMovedEvent):
            self._emit(event.src_path, EventKind.DELETED)
            self._emit(event.dest_path, EventKind.CREATED)


class Watcher:
    """
    Watches a repository directory for source file changes.

    Usage::

        with Watcher(repo_path) as watcher:
            for event in watcher.events():
                print(event)
    """

    def __init__(
        self,
        repo_path: str | Path,
        extensions: frozenset[str] | None = None,
        config: SrcndxConfig | None = None,
    ) -> None:
        self._root = Path(repo_path).resolve()
        if config is None:
            config = load_config(self._root)
        self._config = config

        if extensions is not None:
            self._extensions = extensions
        elif config.watch_tracked_files:
            self._extensions = (
                frozenset(_PARSERS.keys())
                | frozenset(_TRACKED_EXTENSIONS.keys())
                | frozenset(config.extra_tracked_extensions.keys())
            )
        else:
            self._extensions = frozenset(_PARSERS.keys())

        self._tracked_names: dict[str, str] = (
            {**_TRACKED_NAMES, **config.extra_tracked_names}
            if config.watch_tracked_files
            else {}
        )

        self._queue: queue.Queue[FileChangedEvent] = queue.Queue()
        self._observer = Observer()
        self._stop = threading.Event()

    def start(self) -> None:
        handler = _Handler(
            repo_root=self._root,
            extensions=self._extensions,
            tracked_names=self._tracked_names,
            out=self._queue,
            exclude_dirs=self._config.effective_exclude_dirs,
            exclude_extensions=frozenset(self._config.exclude_extensions),
            exclude_files=frozenset(self._config.exclude_files),
        )
        self._observer.schedule(handler, str(self._root), recursive=True)
        self._observer.start()

    def stop(self) -> None:
        self._stop.set()
        self._observer.stop()
        self._observer.join()

    def is_stopped(self) -> bool:
        return self._stop.is_set()

    def poll(self, timeout: float = 0.0) -> FileChangedEvent | None:
        """Return one event or None if none available within timeout."""
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def events(self, timeout: float = 1.0) -> Generator[FileChangedEvent]:
        """Yield FileChangedEvents until stop() is called."""
        while not self._stop.is_set():
            event = self.poll(timeout=timeout)
            if event is not None:
                yield event

    def __enter__(self) -> "Watcher":
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()

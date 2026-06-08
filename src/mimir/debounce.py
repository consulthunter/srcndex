from collections.abc import Generator

from mimir.watcher import FileChangedEvent, Watcher


class Debouncer:
    """Wraps a Watcher and batches events after a configurable quiet period.

    Each file-change event resets the quiet timer. Once no events arrive for
    ``quiet_seconds``, the accumulated batch is returned and the timer resets.
    """

    def __init__(self, watcher: Watcher, quiet_seconds: float = 15.0) -> None:
        self._watcher = watcher
        self._quiet = quiet_seconds

    def wait(self) -> list[FileChangedEvent] | None:
        """Block until the quiet period elapses with no new events.

        Returns the accumulated batch, or None if the watcher stopped with no
        pending events.
        """
        events: list[FileChangedEvent] = []
        while not self._watcher.is_stopped():
            event = self._watcher.poll(timeout=self._quiet)
            if event is None:
                if events:
                    return events
                # quiet period elapsed, nothing accumulated — keep waiting
            else:
                events.append(event)
        # drain any events queued before stop
        while True:
            event = self._watcher.poll(timeout=0.0)
            if event is None:
                break
            events.append(event)
        return events if events else None

    def batches(self) -> Generator[list[FileChangedEvent]]:
        """Yield event batches indefinitely until the watcher stops."""
        while True:
            batch = self.wait()
            if batch is None:
                return
            yield batch

    def __enter__(self) -> "Debouncer":
        self._watcher.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._watcher.stop()

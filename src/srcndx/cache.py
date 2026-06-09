import hashlib
import json
from pathlib import Path

from srcndx.log import get_logger
from srcndx.models import IndexedFile

_log = get_logger()


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class ScanCache:
    """Content-hash cache that stores parsed IndexedFile results.

    On a cache hit, the previously parsed IndexedFile is returned directly,
    avoiding a re-parse. Git metadata (churn_count, git_status) is updated
    by the caller after retrieval since it changes independently of file content.

    Call save() / load() to persist the cache across process restarts.
    """

    _VERSION = 1

    def __init__(self) -> None:
        self._store: dict[str, tuple[str, IndexedFile]] = {}

    def get(self, path: Path) -> IndexedFile | None:
        """Return the cached IndexedFile if content is unchanged, else None."""
        key = path.as_posix()
        entry = self._store.get(key)
        if entry is None:
            return None
        cached_hash, cached_file = entry
        if file_hash(path) == cached_hash:
            return cached_file
        return None

    def put(self, path: Path, content_hash: str, indexed_file: IndexedFile) -> None:
        """Store an IndexedFile and its content hash."""
        self._store[path.as_posix()] = (content_hash, indexed_file)

    def save(self, path: Path) -> None:
        """Persist the cache to a JSON file."""
        data = {
            "version": self._VERSION,
            "entries": {
                key: [h, f.model_dump(mode="json")]
                for key, (h, f) in self._store.items()
            },
        }
        path.write_text(json.dumps(data), encoding="utf-8")
        _log.debug("cache saved: %d entries → %s", len(self._store), path)

    @classmethod
    def load(cls, path: Path) -> "ScanCache":
        """Load a previously saved cache; returns an empty cache on any error."""
        cache = cls()
        if not path.exists():
            return cache
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for key, (h, file_dict) in data.get("entries", {}).items():
                cache._store[key] = (h, IndexedFile.model_validate(file_dict))
            _log.debug("cache loaded: %d entries ← %s", len(cache._store), path)
        except Exception:
            _log.warning("cache load failed (corrupt or incompatible): %s", path)
            return cls()
        return cache

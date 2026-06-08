from pathlib import Path

from mimir.cache import ScanCache, file_hash
from mimir.models import GitStatus, IndexedFile


def _dummy_file(path: str = "src/Foo.java") -> IndexedFile:
    return IndexedFile(
        path=path,
        language="java",
        content_hash="abc123",
        git_status=GitStatus.UNCHANGED,
        churn_count=0,
        symbols=[],
    )


def test_file_hash_is_deterministic(tmp_path: Path) -> None:
    f = tmp_path / "sample.java"
    f.write_bytes(b"public class Foo {}")
    assert file_hash(f) == file_hash(f)


def test_file_hash_changes_on_content_change(tmp_path: Path) -> None:
    f = tmp_path / "sample.java"
    f.write_bytes(b"public class Foo {}")
    h1 = file_hash(f)
    f.write_bytes(b"public class Bar {}")
    h2 = file_hash(f)
    assert h1 != h2


def test_scan_cache_miss_on_empty_cache(tmp_path: Path) -> None:
    f = tmp_path / "sample.java"
    f.write_bytes(b"public class Foo {}")
    cache = ScanCache()
    assert cache.get(f) is None


def test_scan_cache_hit_returns_indexed_file(tmp_path: Path) -> None:
    f = tmp_path / "sample.java"
    f.write_bytes(b"public class Foo {}")
    cache = ScanCache()
    indexed = _dummy_file()
    cache.put(f, file_hash(f), indexed)
    result = cache.get(f)
    assert result is indexed


def test_scan_cache_miss_after_content_change(tmp_path: Path) -> None:
    f = tmp_path / "sample.java"
    f.write_bytes(b"public class Foo {}")
    cache = ScanCache()
    cache.put(f, file_hash(f), _dummy_file())
    f.write_bytes(b"public class Bar {}")
    assert cache.get(f) is None


def test_scan_cache_put_updates_entry(tmp_path: Path) -> None:
    f = tmp_path / "sample.java"
    f.write_bytes(b"public class Foo {}")
    cache = ScanCache()
    first = _dummy_file("src/Foo.java")
    cache.put(f, file_hash(f), first)
    second = _dummy_file("src/Foo.java")
    cache.put(f, file_hash(f), second)
    assert cache.get(f) is second


def test_cache_save_creates_file(tmp_path: Path) -> None:
    f = tmp_path / "sample.java"
    f.write_bytes(b"public class Foo {}")
    cache = ScanCache()
    cache.put(f, file_hash(f), _dummy_file())
    cache_file = tmp_path / "cache.json"
    cache.save(cache_file)
    assert cache_file.exists()


def test_cache_load_returns_empty_on_missing(tmp_path: Path) -> None:
    cache = ScanCache.load(tmp_path / "nonexistent.json")
    assert isinstance(cache, ScanCache)


def test_cache_load_returns_empty_on_corrupt(tmp_path: Path) -> None:
    cache_file = tmp_path / "cache.json"
    cache_file.write_text("not valid json")
    cache = ScanCache.load(cache_file)
    assert isinstance(cache, ScanCache)


def test_cache_save_load_round_trip(tmp_path: Path) -> None:
    f = tmp_path / "sample.java"
    f.write_bytes(b"public class Foo {}")
    cache = ScanCache()
    indexed = _dummy_file()
    cache.put(f, file_hash(f), indexed)
    cache_file = tmp_path / "cache.json"
    cache.save(cache_file)
    loaded = ScanCache.load(cache_file)
    result = loaded.get(f)
    assert result is not None
    assert result.path == indexed.path
    assert result.language == indexed.language

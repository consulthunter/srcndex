from pathlib import Path

from mimir.cache import ScanCache
from mimir.config import MimirConfig
from mimir.scanner import scan

JAVA_SOURCE = b"""
public class Service {
    public void execute() {}
    private void helper() {}
}
"""


def _make_repo(tmp_path: Path, files: dict[str, bytes]) -> Path:
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
    return tmp_path


def test_scan_returns_scan_result(tmp_path: Path) -> None:
    _make_repo(tmp_path, {"src/Service.java": JAVA_SOURCE})
    result = scan(tmp_path)
    assert result.repo_path == str(tmp_path)
    assert result.files_scanned == 1
    assert result.files_skipped == 0


def test_scan_finds_java_symbols(tmp_path: Path) -> None:
    _make_repo(tmp_path, {"src/Service.java": JAVA_SOURCE})
    result = scan(tmp_path)
    all_symbols = [s for p in result.projects for f in p.files for s in f.symbols]
    names = {s.name for s in all_symbols}
    assert "Service" in names
    assert "execute" in names


def test_scan_ignores_untracked_extensions(tmp_path: Path) -> None:
    _make_repo(tmp_path, {
        "src/Service.java": JAVA_SOURCE,
        "binary.bin": b"\x00\x01",
        "archive.zip": b"PK",
        "image.png": b"\x89PNG",
    })
    result = scan(tmp_path)
    all_files = [f for p in result.projects for f in p.files]
    paths = {f.path for f in all_files}
    assert not any(p.endswith((".bin", ".zip", ".png")) for p in paths)


def test_scan_indexes_tracked_files_with_empty_symbols(tmp_path: Path) -> None:
    _make_repo(tmp_path, {
        "src/Service.java": JAVA_SOURCE,
        "README.md": b"# docs",
        "config.yml": b"key: value",
        "settings.json": b"{}",
    })
    result = scan(tmp_path)
    all_files = [f for p in result.projects for f in p.files]
    by_path = {f.path: f for f in all_files}
    assert "README.md" in by_path
    assert "config.yml" in by_path
    assert "settings.json" in by_path
    assert by_path["README.md"].symbols == []
    assert by_path["config.yml"].language == "yaml"
    assert by_path["settings.json"].language == "json"


def test_scan_indexes_dockerfile_by_name(tmp_path: Path) -> None:
    _make_repo(tmp_path, {
        "Dockerfile": b"FROM python:3.13",
        "src/Service.java": JAVA_SOURCE,
    })
    result = scan(tmp_path)
    all_files = [f for p in result.projects for f in p.files]
    dockerfile = next((f for f in all_files if f.path == "Dockerfile"), None)
    assert dockerfile is not None
    assert dockerfile.language == "dockerfile"
    assert dockerfile.symbols == []


def test_scan_tracked_files_included_in_files_scanned(tmp_path: Path) -> None:
    _make_repo(tmp_path, {
        "src/Service.java": JAVA_SOURCE,
        "README.md": b"# docs",
        "Makefile": b"build:\n\tmvn package",
    })
    result = scan(tmp_path)
    assert result.files_scanned == 3


def test_scan_tracked_files_cache_skipped(tmp_path: Path) -> None:
    _make_repo(tmp_path, {
        "src/Service.java": JAVA_SOURCE,
        "README.md": b"# docs",
    })
    cache = ScanCache()
    r1 = scan(tmp_path, cache=cache)
    r2 = scan(tmp_path, cache=cache)
    assert r1.files_scanned == 2
    assert r2.files_skipped == 2


def test_scan_cache_skips_unchanged_files(tmp_path: Path) -> None:
    _make_repo(tmp_path, {"src/Service.java": JAVA_SOURCE})
    cache = ScanCache()
    r1 = scan(tmp_path, cache=cache)
    r2 = scan(tmp_path, cache=cache)
    assert r1.files_scanned == 1
    assert r2.files_scanned == 0
    assert r2.files_skipped == 1


def test_scan_cache_second_call_returns_all_files(tmp_path: Path) -> None:
    _make_repo(tmp_path, {
        "src/Service.java": JAVA_SOURCE,
        "README.md": b"# docs",
    })
    cache = ScanCache()
    r1 = scan(tmp_path, cache=cache)
    r2 = scan(tmp_path, cache=cache)
    files1 = {f.path for p in r1.projects for f in p.files}
    files2 = {f.path for p in r2.projects for f in p.files}
    assert files1 == files2


def test_scan_deduplicates_projects_with_multiple_build_files(tmp_path: Path) -> None:
    _make_repo(tmp_path, {
        "src/Service.java": JAVA_SOURCE,
        "pyproject.toml": b"[project]\nname = 'x'",
        "setup.py": b"from setuptools import setup",
    })
    result = scan(tmp_path)
    # Both build files are in the same directory — should produce one project
    assert len(result.projects) == 1


def test_scan_build_file_is_relative_path(tmp_path: Path) -> None:
    _make_repo(tmp_path, {
        "src/Service.java": JAVA_SOURCE,
        "pyproject.toml": b"[project]\nname = 'x'",
    })
    result = scan(tmp_path)
    project = result.projects[0]
    assert not project.build_file.startswith(str(tmp_path))
    assert project.build_file == "pyproject.toml"


def test_scan_empty_repo(tmp_path: Path) -> None:
    result = scan(tmp_path)
    assert result.files_scanned == 0
    assert result.projects == []


def test_scan_result_has_timestamp(tmp_path: Path) -> None:
    _make_repo(tmp_path, {"src/Service.java": JAVA_SOURCE})
    result = scan(tmp_path)
    assert result.scanned_at is not None


def test_scan_excludes_dir(tmp_path: Path) -> None:
    _make_repo(tmp_path, {
        "src/Service.java": JAVA_SOURCE,
        "vendor/Lib.java": JAVA_SOURCE,
    })
    cfg = MimirConfig(exclude_dirs=["vendor"])
    result = scan(tmp_path, config=cfg)
    all_paths = [f.path for p in result.projects for f in p.files]
    assert not any("vendor" in p for p in all_paths)
    assert any("Service.java" in p for p in all_paths)


def test_scan_excludes_extension(tmp_path: Path) -> None:
    _make_repo(tmp_path, {
        "src/Service.java": JAVA_SOURCE,
        "package.lock": b"locked",
    })
    cfg = MimirConfig(exclude_extensions=[".lock"], extra_tracked_extensions={".lock": "lockfile"})
    result = scan(tmp_path, config=cfg)
    all_paths = [f.path for p in result.projects for f in p.files]
    assert not any(p.endswith(".lock") for p in all_paths)


def test_scan_excludes_file(tmp_path: Path) -> None:
    _make_repo(tmp_path, {
        "src/Service.java": JAVA_SOURCE,
        "package-lock.json": b"{}",
    })
    cfg = MimirConfig(exclude_files=["package-lock.json"])
    result = scan(tmp_path, config=cfg)
    all_paths = [f.path for p in result.projects for f in p.files]
    assert "package-lock.json" not in all_paths


def test_scan_extra_tracked_extension(tmp_path: Path) -> None:
    _make_repo(tmp_path, {
        "src/Service.java": JAVA_SOURCE,
        "schema.proto": b'syntax = "proto3";',
    })
    cfg = MimirConfig(extra_tracked_extensions={".proto": "protobuf"})
    result = scan(tmp_path, config=cfg)
    all_files = [f for p in result.projects for f in p.files]
    proto = next((f for f in all_files if f.path.endswith(".proto")), None)
    assert proto is not None
    assert proto.language == "protobuf"
    assert proto.symbols == []


def test_scan_extra_tracked_name(tmp_path: Path) -> None:
    _make_repo(tmp_path, {
        "src/Service.java": JAVA_SOURCE,
        "Jenkinsfile": b"pipeline {}",
    })
    cfg = MimirConfig(extra_tracked_names={"Jenkinsfile": "groovy"})
    result = scan(tmp_path, config=cfg)
    all_files = [f for p in result.projects for f in p.files]
    jenkins = next((f for f in all_files if f.path == "Jenkinsfile"), None)
    assert jenkins is not None
    assert jenkins.language == "groovy"


def test_scan_additional_exclude_dirs(tmp_path: Path) -> None:
    _make_repo(tmp_path, {
        "src/Service.java": JAVA_SOURCE,
        "fixtures/Stub.java": JAVA_SOURCE,
    })
    cfg = MimirConfig(additional_exclude_dirs=["fixtures"])
    result = scan(tmp_path, config=cfg)
    all_paths = [f.path for p in result.projects for f in p.files]
    assert not any("fixtures" in p for p in all_paths)
    assert any("Service.java" in p for p in all_paths)


def test_scan_auto_loads_config_file(tmp_path: Path) -> None:
    _make_repo(tmp_path, {
        "src/Service.java": JAVA_SOURCE,
        "vendor/Lib.java": JAVA_SOURCE,
    })
    (tmp_path / ".mimir.toml").write_text('exclude_dirs = ["vendor"]\n')
    result = scan(tmp_path)
    all_paths = [f.path for p in result.projects for f in p.files]
    assert not any("vendor" in p for p in all_paths)


def test_scan_skips_large_files(tmp_path: Path) -> None:
    _make_repo(tmp_path, {
        "src/Service.java": JAVA_SOURCE,
        "src/Large.java": b"x" * (501 * 1024),
    })
    cfg = MimirConfig(max_file_size_kb=500)
    result = scan(tmp_path, config=cfg)
    all_paths = [f.path for p in result.projects for f in p.files]
    assert not any("Large.java" in p for p in all_paths)
    assert any("Service.java" in p for p in all_paths)


def test_scan_parallel_produces_all_files(tmp_path: Path) -> None:
    files = {f"src/Service{i}.java": JAVA_SOURCE for i in range(20)}
    _make_repo(tmp_path, files)
    result = scan(tmp_path)
    all_paths = [f.path for p in result.projects for f in p.files]
    assert len(all_paths) == 20


def test_scan_files_sorted_by_path(tmp_path: Path) -> None:
    _make_repo(tmp_path, {
        "src/Zebra.java": JAVA_SOURCE,
        "src/Alpha.java": JAVA_SOURCE,
        "src/Mango.java": JAVA_SOURCE,
    })
    result = scan(tmp_path)
    paths = [f.path for p in result.projects for f in p.files]
    assert paths == sorted(paths)


def test_scan_persist_cache_creates_file(tmp_path: Path) -> None:
    _make_repo(tmp_path, {"src/Service.java": JAVA_SOURCE})
    cfg = MimirConfig(persist_cache=True, cache_file=".test-cache.json")
    scan(tmp_path, config=cfg)
    assert (tmp_path / ".test-cache.json").exists()


def test_scan_persist_cache_second_call_skips(tmp_path: Path) -> None:
    _make_repo(tmp_path, {"src/Service.java": JAVA_SOURCE})
    cfg = MimirConfig(persist_cache=True, cache_file=".test-cache.json")
    scan(tmp_path, config=cfg)
    r2 = scan(tmp_path, config=cfg)
    assert r2.files_skipped == 1
    assert r2.files_scanned == 0

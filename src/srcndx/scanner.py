from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic

import pygit2

from srcndx.cache import ScanCache, file_hash
from srcndx.config import SrcndxConfig, load_config
from srcndx.git_metadata import churn_map, file_status, head_commit, load_repo
from srcndx.log import get_logger
from srcndx.models import (
    GitStatus,
    IndexedFile,
    IndexedProject,
    ProjectKind,
    ScanResult,
)
from srcndx.parsers.base import BaseParser
from srcndx.parsers.csharp import CSharpParser
from srcndx.parsers.java import JavaParser
from srcndx.parsers.python import PythonParser
from srcndx.parsers.typescript import TypeScriptParser

_log = get_logger()

# Module-level instances — only for extension registry (watcher) and single-threaded use.
# Parallel paths use _PARSERS directly; the per-parser lock in BaseParser ensures safety.
_PARSERS: dict[str, BaseParser] = {
    ".java": JavaParser(),
    ".py": PythonParser(),
    ".cs": CSharpParser(),
    ".ts": TypeScriptParser(tsx=False),
    ".tsx": TypeScriptParser(tsx=True),
}

# Files tracked without symbol extraction — enriched later by static analysis.
_TRACKED_EXTENSIONS: dict[str, str] = {
    ".yml": "yaml",
    ".yaml": "yaml",
    ".json": "json",
    ".xml": "xml",
    ".toml": "toml",
    ".properties": "properties",
    ".ini": "ini",
    ".cfg": "ini",
    ".md": "markdown",
    ".rst": "rst",
    ".sh": "shell",
    ".bash": "shell",
    ".ps1": "powershell",
    ".bat": "batch",
    ".cmd": "batch",
    ".sql": "sql",
    ".tf": "terraform",
    ".dockerfile": "dockerfile",
    ".graphql": "graphql",
    ".gql": "graphql",
}

_TRACKED_NAMES: dict[str, str] = {
    "Dockerfile": "dockerfile",
    "dockerfile": "dockerfile",
    "Makefile": "makefile",
    "makefile": "makefile",
    ".gitignore": "gitignore",
    ".dockerignore": "dockerignore",
}

_BUILD_FILES: dict[str, ProjectKind] = {
    "pom.xml": ProjectKind.MAVEN,
    "build.gradle": ProjectKind.GRADLE,
    "build.gradle.kts": ProjectKind.GRADLE,
    "*.csproj": ProjectKind.CSPROJ,
    "setup.py": ProjectKind.PYTHON_PACKAGE,
    "pyproject.toml": ProjectKind.PYTHON_PACKAGE,
}


def _detect_projects(
    repo_root: Path, config: SrcndxConfig
) -> list[tuple[Path, ProjectKind, str]]:
    exclude_dirs = config.effective_exclude_dirs
    found: list[tuple[Path, ProjectKind, str]] = []
    seen: set[Path] = set()

    for build_name, kind in _BUILD_FILES.items():
        pattern = f"*{build_name.lstrip('*')}" if "*" in build_name else build_name
        for p in repo_root.rglob(pattern):
            rel_parts = p.relative_to(repo_root).parts
            if any(part in exclude_dirs for part in rel_parts[:-1]):
                continue
            if p.parent not in seen:
                seen.add(p.parent)
                found.append((p.parent, kind, p.relative_to(repo_root).as_posix()))

    if not found:
        found.append((repo_root, ProjectKind.UNKNOWN, ""))
    return found


def _language(path: Path, config: SrcndxConfig | None = None) -> str | None:
    """Return the language tag for a file, or None if it should not be indexed."""
    suffix = path.suffix.lower()
    if suffix in _PARSERS:
        return suffix
    tracked_exts = _TRACKED_EXTENSIONS
    tracked_names = _TRACKED_NAMES
    if config:
        if config.extra_tracked_extensions:
            tracked_exts = {**tracked_exts, **config.extra_tracked_extensions}
        if config.extra_tracked_names:
            tracked_names = {**tracked_names, **config.extra_tracked_names}
    if suffix in tracked_exts:
        return tracked_exts[suffix]
    return tracked_names.get(path.name)


def _is_excluded(path: Path, root: Path, config: SrcndxConfig) -> bool:
    parts = path.relative_to(root).parts
    if any(p in config.effective_exclude_dirs for p in parts[:-1]):
        return True
    if path.suffix.lower() in frozenset(config.exclude_extensions):
        return True
    if path.name in frozenset(config.exclude_files):
        return True
    # Exclude the cache file — it's an internal mimir artifact, not a source file.
    return path.name == config.cache_file


def _make_tracked_file(
    path: Path, rel_path: str, content_hash: str, language: str
) -> IndexedFile:
    return IndexedFile(
        path=rel_path,
        language=language,
        content_hash=content_hash,
        git_status=GitStatus.UNCHANGED,
        churn_count=0,
        symbols=[],
    )


def _parse_file(
    src_path: Path,
    rel_path: str,
    language: str,
) -> tuple[Path, str, IndexedFile | None]:
    """Parse a single file; safe to call from a worker thread."""
    content_hash = file_hash(src_path)
    suffix = src_path.suffix.lower()
    if suffix in _PARSERS:
        indexed_file = _PARSERS[suffix].extract(src_path, rel_path, content_hash)
    else:
        indexed_file = _make_tracked_file(src_path, rel_path, content_hash, language)
    return src_path, content_hash, indexed_file


def scan(
    repo_path: str | Path,
    cache: ScanCache | None = None,
    config: SrcndxConfig | None = None,
) -> ScanResult:
    root = Path(repo_path).resolve()
    if config is None:
        config = load_config(root)

    # Auto-load persistent cache when configured and caller didn't provide one.
    _cache_path: Path | None = None
    if cache is None:
        if config.persist_cache:
            _cache_path = root / config.cache_file
            cache = ScanCache.load(_cache_path)
        else:
            cache = ScanCache()

    _log.info("scan started: %s", root)
    _t0 = monotonic()

    repo = load_repo(root)
    churns = churn_map(repo) if repo else {}
    h_commit = head_commit(repo) if repo else ""

    projects_raw = _detect_projects(root, config)
    indexed_projects: list[IndexedProject] = []
    files_scanned = 0
    files_skipped = 0
    max_bytes = config.max_file_size_kb * 1024

    for proj_dir, proj_kind, build_file in projects_raw:
        indexed_files: list[IndexedFile] = []
        to_parse: list[tuple[Path, str, str]] = []  # (path, rel_path, language)

        # Phase 1: enumerate files and resolve cache hits sequentially.
        for src_path in proj_dir.rglob("*"):
            if not src_path.is_file():
                continue
            if _is_excluded(src_path, root, config):
                continue
            if src_path.stat().st_size > max_bytes:
                _log.debug(
                    "skipping large file: %s (%d KB > %d KB)",
                    src_path.relative_to(root).as_posix(),
                    src_path.stat().st_size // 1024,
                    config.max_file_size_kb,
                )
                continue

            language = _language(src_path, config)
            if language is None:
                continue

            rel_path = src_path.relative_to(root).as_posix()

            cached = cache.get(src_path)
            if cached is not None:
                cached.churn_count = churns.get(rel_path, 0)
                cached.git_status = (
                    file_status(repo, rel_path) if repo else GitStatus.UNCHANGED
                )
                indexed_files.append(cached)
                files_skipped += 1
                _log.debug("cached:  %s", rel_path)
            else:
                _log.debug("queued:  %s", rel_path)
                to_parse.append((src_path, rel_path, language))

        # Phase 2: parse cache misses in parallel.
        if to_parse:
            with ThreadPoolExecutor() as executor:
                futures = {
                    executor.submit(_parse_file, src_path, rel_path, language): (src_path, rel_path)
                    for src_path, rel_path, language in to_parse
                }
                for future in as_completed(futures):
                    src_path, content_hash, indexed_file = future.result()
                    if indexed_file is None:
                        _log.warning(
                            "parse failed, skipping: %s",
                            src_path.relative_to(root).as_posix(),
                        )
                        continue
                    rel_path = src_path.relative_to(root).as_posix()
                    _log.debug("parsed:  %s", rel_path)
                    indexed_file.churn_count = churns.get(rel_path, 0)
                    indexed_file.git_status = (
                        file_status(repo, rel_path) if repo else GitStatus.UNCHANGED
                    )
                    cache.put(src_path, content_hash, indexed_file)
                    indexed_files.append(indexed_file)
                    files_scanned += 1

        if not indexed_files:
            continue

        indexed_files.sort(key=lambda f: f.path)

        _log.debug(
            "project %s: %d files (%d parsed, %d from cache)",
            proj_dir.relative_to(root).as_posix() or ".",
            len(indexed_files),
            len(to_parse),
            len(indexed_files) - len(to_parse),
        )

        indexed_projects.append(
            IndexedProject(
                path=proj_dir.relative_to(root).as_posix(),
                name=proj_dir.name,
                kind=proj_kind,
                build_file=build_file,
                files=indexed_files,
            )
        )

    if _cache_path is not None:
        cache.save(_cache_path)

    _log.info(
        "scan complete: %d scanned, %d skipped, %.2fs",
        files_scanned,
        files_skipped,
        monotonic() - _t0,
    )

    return ScanResult(
        repo_path=str(root),
        head_commit=h_commit,
        projects=indexed_projects,
        scanned_at=datetime.now(UTC),
        files_scanned=files_scanned,
        files_skipped=files_skipped,
    )


def scan_file(
    file_path: str | Path,
    repo_path: str | Path,
    repo: pygit2.Repository | None = None,
    churns: dict[str, int] | None = None,
    cache: ScanCache | None = None,
    config: SrcndxConfig | None = None,
) -> IndexedFile | None:
    """Re-index a single file; used for incremental updates."""
    path = Path(file_path).resolve()
    root = Path(repo_path).resolve()

    if config is None:
        config = load_config(root)

    if _is_excluded(path, root, config):
        return None

    language = _language(path, config)
    if language is None:
        return None

    rel_path = path.relative_to(root).as_posix()
    content_hash = file_hash(path)
    suffix = path.suffix.lower()

    if suffix in _PARSERS:
        indexed_file = _PARSERS[suffix].extract(path, rel_path, content_hash)
        if indexed_file is None:
            return None
    else:
        indexed_file = _make_tracked_file(path, rel_path, content_hash, language)

    indexed_file.churn_count = (churns or {}).get(rel_path, 0)
    if repo:
        indexed_file.git_status = file_status(repo, rel_path)

    if cache is not None:
        cache.put(path, content_hash, indexed_file)

    return indexed_file

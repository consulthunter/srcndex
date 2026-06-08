# AGENTS.md

This file is for coding agents working on the mimir codebase. Read it before making changes.

---

## Project layout

```
src/mimir/
  models.py          # All Pydantic models and StrEnum types — the shared contract
  config.py          # MimirConfig model + load_config()
  cache.py           # SHA-256 content-hash cache for incremental scans
  git_metadata.py    # pygit2 single-pass churn walk and file status
  scanner.py         # Core scan logic; _PARSERS, _TRACKED_EXTENSIONS, _TRACKED_NAMES
  watcher.py         # Watchdog-based file system watcher
  debounce.py        # Debouncer wrapping Watcher
  __init__.py        # Public API re-exports
  parsers/
    base.py          # BaseParser + tree-sitter AST helpers
    java.py
    python.py
    csharp.py
    typescript.py
  cli/
    commands.py      # argparse entry point
    db.py            # stdlib sqlite3 writer

tests/               # One test file per module
```

---

## Dev commands

```bash
uv run pytest                  # run all tests
uv run pytest tests/test_X.py  # run one module
uv run ruff check src tests    # lint
uv run ruff format src tests   # format
uv run mimir scan .            # run the CLI against this repo
```

All commands use `uv run`. Do not activate a venv manually.

---

## Hard constraints — do not change these

- **No SQLAlchemy.** The CLI layer uses `sqlite3` from stdlib only. Keep it that way.
- **No remote access.** Mimir operates on local paths exclusively. No cloning, no network calls.
- **No write operations.** Mimir reads repos; it never modifies source files.
- **No RAG / vector stores.** This is a structural indexer. Embeddings and semantic search are out of scope.
- **Library layer has zero SQLite dependency.** `scanner.py` and everything it imports must not touch `sqlite3`. The DB write lives only in `cli/db.py`.
- **Python 3.13+.** Use `tomllib` (stdlib), `StrEnum` (stdlib), `UTC` from `datetime` (not `timezone.utc`).

---

## Code conventions

- **Pydantic v2** for all models. Use `StrEnum` for enum types, not `Enum` with string values.
- **Type annotations everywhere.** No untyped function signatures.
- **Ruff** for formatting and linting. Line length 88. Run `ruff format` before committing.
  - Selected rules: `E, F, I, UP, B, SIM`. `E501` is ignored (long lines are fine).
- **No comments explaining what code does.** Only comment when the *why* is non-obvious.
- **No docstrings on simple functions.** Class-level docstrings are acceptable for public-facing classes.
- Individual tree-sitter packages only (`tree-sitter-java`, `tree-sitter-python`, etc.). Do not add `tree-sitter-languages`.

---

## Running tests

```bash
uv run pytest --tb=short -q
```

102 tests across 10 modules. All must pass before any change is considered done. Tests use `tmp_path` fixtures — no external resources, no network, no git repos created at test time unless the test specifically requires one.

**If you add a feature, add tests for it.** Test files live in `tests/` and are named `test_<module>.py`.

---

## Adding a new language parser

1. Create `src/mimir/parsers/<language>.py`. Subclass `BaseParser`:

```python
import tree_sitter_<language>
from tree_sitter import Language
from mimir.parsers.base import BaseParser

class <Language>Parser(BaseParser):
    language_name = "<language>"

    def __init__(self) -> None:
        super().__init__(Language(tree_sitter_<language>.language()))

    def extract(self, path: Path, rel_path: str, content_hash: str) -> IndexedFile | None:
        tree = self.parse_file(path)
        if tree is None:
            return None
        source = path.read_bytes()
        symbols: list[IndexedSymbol] = []
        # ... walk tree.root_node, populate symbols
        return IndexedFile(
            path=rel_path,
            language="<language>",
            content_hash=content_hash,
            git_status=GitStatus.UNCHANGED,
            churn_count=0,
            symbols=symbols,
        )
```

2. Add the package to `pyproject.toml` dependencies.

3. Register a singleton instance in `scanner.py`:

```python
_PARSERS: dict[str, BaseParser] = {
    ...
    ".<ext>": <Language>Parser(),
}
```

4. Add tests in `tests/test_<language>_parser.py`. Cover: class extraction, method extraction, visibility, `is_test` detection, qualified names.

**Use the AST helpers on `BaseParser`** (`nodes_of_type`, `first_child_of_type`, `node_text`, etc.) before writing custom traversal.

**Parser instances are singletons** — they are created once at module import time in `_PARSERS`. Do not instantiate parsers per-file.

---

## Adding tracked (non-parsed) file types

Non-source files are indexed as `IndexedFile(symbols=[])` — tracked for existence and git metadata, no symbol extraction.

To add a new extension, add it to `_TRACKED_EXTENSIONS` in `scanner.py`:

```python
_TRACKED_EXTENSIONS: dict[str, str] = {
    ...
    ".proto": "protobuf",
}
```

To track a file with no extension by exact name, add it to `_TRACKED_NAMES`:

```python
_TRACKED_NAMES: dict[str, str] = {
    ...
    "Jenkinsfile": "groovy",
}
```

Users can also extend both via `.mimir.toml` (`extra_tracked_extensions`, `extra_tracked_names`) without modifying the source.

---

## Models

All models are in `models.py`. Do not define models anywhere else.

`IndexedFile` and `IndexedSymbol` are mutable Pydantic models. The scanner sets `git_status` and `churn_count` after the parser returns — parsers always return them with `GitStatus.UNCHANGED` and `churn_count=0`.

`SymbolKind`, `Visibility`, `GitStatus`, `ProjectKind` are `StrEnum`. Add new variants there if needed; do not use raw strings for these values anywhere in the codebase.

---

## Config

`MimirConfig` is in `config.py`. `load_config(repo_path)` reads `.mimir.toml` via `tomllib` (stdlib, Python 3.11+).

Both `scan()` and `Watcher.__init__` auto-load config from the repo root when no config is passed. If a `MimirConfig` is passed explicitly, it takes precedence and `.mimir.toml` is not read.

---

## Scanner architecture

`scan()` is the main entry point. It:
1. Loads config and cache
2. Resolves git repo metadata (via `pygit2`)
3. Detects projects by searching for build files (`pom.xml`, `pyproject.toml`, etc.)
4. For each project, rglobs all files and routes them:
   - Excluded by config → skip
   - Suffix in `_PARSERS` → call `parser.extract()`
   - Suffix in `_TRACKED_EXTENSIONS` or name in `_TRACKED_NAMES` → `_make_tracked_file()`
   - Otherwise → skip
5. Sets `churn_count` and `git_status` on each `IndexedFile` after extraction

`scan_file()` is the single-file variant used for incremental updates from the watcher.

---

## Watcher / Debouncer

`Watcher` wraps watchdog and emits `FileChangedEvent` objects into a thread-safe queue. `poll(timeout)` is the non-blocking read method. `events()` is a generator that yields until `stop()` is called.

`Debouncer` wraps a `Watcher` and returns batches of events after a configurable quiet period. `wait()` blocks until no events arrive for `quiet_seconds`, then returns the accumulated list. The timer resets on each new event.

Tests for the watcher use `_drain(watcher, timeout)` — a polling loop that collects events for up to `timeout` seconds. Keep this pattern in new watcher tests.

**Do not use the `events()` generator in tests.** It only exits when `stop()` is called, which creates deadlock in test teardown. Use `poll()` directly or `_drain()`.

---

## CLI

Entry point: `mimir.cli:main` (registered in `pyproject.toml`).

`commands.py` handles argument parsing. `db.py` handles SQLite writes. Add new subcommands by adding a new `cmd_<name>` function and registering it with `sub.add_parser(...)` in `main()`.

The CLI must not import anything from `mimir.cli.db` in the library layer.

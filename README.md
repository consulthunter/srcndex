# srcndx

A local, structural code indexer for use with agents.

## What is a code indexer?

A code indexer does a single pass over a repository and builds a map of what exists: files, classes, methods, signatures, line numbers, and metadata. The result is a queryable structure that code can read programmatically — instead of an agent reading files one by one to discover what's in them, it consults the index first.

**Trade-offs:**
- An index is a snapshot. It goes stale as files change (the file watcher handles this for long-running sessions).
- It captures *structure*, not *semantics*. It knows a method named `processPayment` exists on line 42 of `PaymentService.java` with `public` visibility — it does not know what it does. That's still the agent's job.
- Small tasks on a known file don't benefit much. The value scales with repo size and task scope.

**Where it pays off:**
- Finding things before acting — which files implement an interface, where a symbol is defined, what tests exist for a module
- Injecting targeted context — send the symbol skeleton of a file rather than the whole file, then fetch only the lines the agent actually needs
- Prioritizing work — high churn files are more likely to have gaps; `is_test` separates production code from test code without the agent having to guess
- Multi-agent or long sessions — a shared index avoids every agent re-reading the same files independently

## Features

- **Dual-mode** — use as a Python library (returns Pydantic models) or as a CLI (writes to SQLite)
- **Multi-language** — Java, Python, C#, TypeScript, TSX
- **Import tracking** — per-file `imports` list extracted from the AST for all supported languages
- **Annotations** — decorators, Java annotations, and C# attributes stored per symbol
- **Endpoint detection** — `is_endpoint`, `http_method`, `route_path` inferred from annotations (Spring Boot, ASP.NET Core, FastAPI/Flask, NestJS)
- **Test classification** — `test_kind` (unit / integration / e2e) from directory structure and annotations
- **Test framework detection** — `test_framework` inferred from imports (JUnit 4/5, TestNG, pytest, NUnit, xUnit, Jest, Vitest, and more)
- **Full-text search** — FTS5 virtual table over symbol names and signatures; agents can use `MATCH` queries instead of exact SQL
- **Compact map output** — `srcndx map` emits a condensed symbol tree suitable for injection into agent context windows
- **Pass-through tracking** — YAML, JSON, TOML, Markdown, Dockerfiles, and other non-source files are indexed with `symbols=[]` for later enrichment
- **Git metadata** — per-file `git_status` and `churn_count` from a single-pass commit walk
- **Parallel scanning** — cache misses are parsed concurrently via a thread pool
- **Incremental scanning** — SHA-256 content-hash cache skips unchanged files on subsequent scans
- **Persistent cache** — optional on-disk cache so warm starts are free across process restarts
- **File watcher** — debounced file system events for keeping an index current during long sessions
- **Configurable** — exclusions, custom extensions, size limits, and debounce timing via `.srcndx.toml`
- **Logging** — structured file logging with configurable verbosity

## Installation

Requires Python 3.13+.

```bash
uv add srcndx
# or
pip install srcndx
```

## Usage

### CLI

Scan a repo and print JSON to stdout:

```bash
srcndx scan /path/to/repo
```

Write to a SQLite database instead:

```bash
srcndx scan /path/to/repo -o index.db
```

Watch a repo and keep the index up to date as files change. The debouncer waits for a quiet period before re-scanning (default 15 seconds):

```bash
srcndx watch /path/to/repo -o index.db
```

Emit a compact symbol map from an existing index:

```bash
srcndx map -i index.db
srcndx map -i index.db --filter src/api/
```

Sample map output:

```
src/api/UserController.java  [java]
  GET    /api/users/{id}  getUser
  POST   /api/users       createUser

src/test/unit/UserServiceTest.java  [java, unit]
  testCreateUser()
  testGetUser()
```

Enable logging to a file:

```bash
srcndx scan /path/to/repo -o index.db --log-file srcndx.log
srcndx scan /path/to/repo -o index.db --log-file srcndx.log --log-level DEBUG
```

`--log-level` accepts `DEBUG`, `INFO`, `WARNING`, `ERROR` (default `INFO`). At `DEBUG` level each file is logged individually:

```
2026-06-07T14:23:01 INFO     scan started: /path/to/repo
2026-06-07T14:23:01 DEBUG    queued:  src/Service.java
2026-06-07T14:23:01 DEBUG    parsed:  src/Service.java
2026-06-07T14:23:01 DEBUG    cached:  src/Util.java
2026-06-07T14:23:01 DEBUG    skipping large file: src/generated/Big.java (612 KB > 500 KB)
2026-06-07T14:23:01 INFO     scan complete: 1 scanned, 1 skipped, 0.04s
```

Query the database directly:

```sql
-- All non-test methods with their file paths
SELECT f.path, s.name, s.kind, s.start_line
FROM indexed_symbols s
JOIN indexed_files f ON s.file_id = f.id
WHERE s.is_test = 0 AND s.kind = 'method'
ORDER BY f.path;

-- All HTTP endpoints
SELECT s.http_method, s.route_path, s.name, f.path
FROM indexed_symbols s
JOIN indexed_files f ON s.file_id = f.id
WHERE s.is_endpoint = 1
ORDER BY s.http_method, s.route_path;

-- Full-text search across symbol names and signatures
SELECT name, qualified_name, kind FROM symbols_fts
WHERE symbols_fts MATCH 'payment process';

-- Test files and their detected framework
SELECT path, test_framework FROM indexed_files
WHERE test_framework IS NOT NULL;

-- Files that import a specific module
SELECT path FROM indexed_files
WHERE imports LIKE '%"requests"%';
```

### Library

```python
from srcndx import scan, SrcndxConfig

# Full scan — returns a ScanResult (Pydantic model)
result = scan("/path/to/repo")

print(result.files_scanned)   # 142
print(result.head_commit)     # abc123...

for project in result.projects:
    for file in project.files:
        print(file.path, file.language, len(file.symbols))
        print(file.imports)          # ["os", "pathlib", "requests"]
        print(file.test_framework)   # "pytest" | "junit5" | None
```

Filter to just production classes:

```python
classes = [
    s
    for project in result.projects
    for file in project.files
    for s in file.symbols
    if s.kind == "class" and not s.is_test
]
```

Find all HTTP endpoints:

```python
endpoints = [
    (file.path, s.http_method, s.route_path, s.name)
    for project in result.projects
    for file in project.files
    for s in file.symbols
    if s.is_endpoint
]
# e.g. ("src/UserController.java", "GET", "/api/users/{id}", "getUser")
```

Inspect annotations on symbols:

```python
annotated = [
    (file.path, s.name, s.annotations)
    for project in result.projects
    for file in project.files
    for s in file.symbols
    if s.annotations
]
# e.g. ("src/UserService.java", "createUser", ["@Override", "@Transactional"])
```

Re-index a single file after a change:

```python
from srcndx import scan_file

updated = scan_file("/path/to/repo/src/Service.java", repo_path="/path/to/repo")
```

Use a persistent cache so the second call only parses changed files:

```python
from srcndx import scan, SrcndxConfig

config = SrcndxConfig(persist_cache=True, cache_file=".srcndx-cache.json")
result = scan("/path/to/repo", config=config)   # cold start — parses everything
result = scan("/path/to/repo", config=config)   # warm start — skips unchanged files
```

Pass an in-memory cache across repeated calls within a single process:

```python
from srcndx import scan
from srcndx.cache import ScanCache

cache = ScanCache()
r1 = scan("/path/to/repo", cache=cache)   # parses everything
r2 = scan("/path/to/repo", cache=cache)   # skips unchanged files
```

### File watcher (library)

Keep an index current during a long session. The debouncer collects events and waits for a quiet period before firing — if another change arrives, the timer resets.

```python
from srcndx import SrcndxConfig, scan
from srcndx.cache import ScanCache
from srcndx.watcher import Watcher
from srcndx.debounce import Debouncer

config = SrcndxConfig(debounce_seconds=15.0)
cache = ScanCache()

with Debouncer(Watcher("/path/to/repo", config=config)) as debouncer:
    for batch in debouncer.batches():
        result = scan("/path/to/repo", cache=cache, config=config)
        # result now reflects the current state of the repo
```

## Configuration

Drop a `.srcndx.toml` at the repo root. All fields are optional.

```toml
debounce_seconds = 10.0
watch_tracked_files = false   # watch only parseable source files, not YAML/JSON/etc.

exclude_dirs = [".git", "node_modules", "vendor", "dist"]
additional_exclude_dirs = ["fixtures"]   # extends the defaults without replacing them
exclude_extensions = [".lock", ".min.js"]
exclude_files = ["package-lock.json", "srcndx.log"]

max_file_size_kb = 500   # skip files larger than this (default: 500)

persist_cache = true
cache_file = ".srcndx-cache.json"

log_file = "srcndx.log"
log_level = "INFO"   # DEBUG | INFO | WARNING | ERROR

[extra_tracked_extensions]
".proto" = "protobuf"
".avro" = "avro"

[extra_tracked_names]
"Jenkinsfile" = "groovy"
```

Config is loaded automatically from the repo root when calling `scan()` or creating a `Watcher`. Pass a `SrcndxConfig` explicitly to override.

CLI flags (`--log-file`, `--log-level`) take priority over `.srcndx.toml` values when both are set.

## Data model

```
ScanResult
  repo_path, head_commit, scanned_at, files_scanned, files_skipped
  └── IndexedProject (one per detected build file)
        path, name, kind (maven | gradle | csproj | python_package | unknown)
        └── IndexedFile
              path, language, content_hash, git_status, churn_count
              imports: list[str]
              test_framework: str | None
              └── IndexedSymbol
                    name, qualified_name, kind, parent_name
                    start_line, end_line, visibility, is_test, signature
                    annotations: list[str]
                    is_endpoint: bool
                    http_method: str | None
                    route_path: str | None
                    test_kind: str | None   (unit | integration | e2e)
```

`git_status` is one of `new | modified | unchanged | deleted`.
`kind` is one of `class | interface | enum | method | constructor | function | property | field`.
`visibility` is one of `public | private | protected | internal | unknown`.
`test_framework` is inferred from file-level imports; enrichment tools can overwrite it with build-file data.

## Supported languages

| Language   | Extensions        | Symbols extracted                                      |
|------------|-------------------|--------------------------------------------------------|
| Java       | `.java`           | classes, interfaces, enums, methods, constructors      |
| Python     | `.py`             | classes, functions, methods, constructors              |
| C#         | `.cs`             | classes, interfaces, enums, structs, methods, constructors, properties |
| TypeScript | `.ts`, `.tsx`     | classes, interfaces, methods, functions, properties    |

Non-source files (YAML, JSON, XML, TOML, Markdown, shell scripts, SQL, Terraform, Dockerfiles, and more) are indexed as `IndexedFile` with `symbols=[]`.

---

*This README was written with the assistance of generative AI.*

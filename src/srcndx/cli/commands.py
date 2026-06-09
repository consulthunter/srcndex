import argparse
import sys
from pathlib import Path

from srcndx.cli.db import read_map, write
from srcndx.config import load_config
from srcndx.log import configure
from srcndx.scanner import scan

_VIS_CHAR = {"public": "+", "private": "-", "protected": "~", "internal": "#"}


def _format_map(files: list[tuple[str, str, list[dict]]]) -> str:
    lines: list[str] = []
    for file_path, language, symbols in files:
        if not symbols:
            continue  # skip tracked-only files with no symbols

        # Determine file-level tags
        tags: list[str] = [language]
        test_kinds = {s["test_kind"] for s in symbols if s["is_test"] and s["test_kind"]}
        if test_kinds:
            tags.append(sorted(test_kinds)[0])  # unit / integration / e2e
        elif any(s["is_test"] for s in symbols):
            tags.append("test")

        lines.append(f"{file_path}  [{', '.join(tags)}]")

        for s in symbols:
            if s["is_endpoint"] and s["http_method"] or s["route_path"]:
                method = (s["http_method"] or "?").ljust(6)
                path = s["route_path"] or ""
                lines.append(f"  {method} {path}  {s['name']}")
            elif s["is_test"]:
                lines.append(f"  {s['name']}()")
            else:
                vis = _VIS_CHAR.get(s["visibility"], "?")
                lines.append(f"  {vis} {s['signature']}")

        lines.append("")  # blank line between files

    return "\n".join(lines).rstrip()


def _setup_logging(args: argparse.Namespace, repo_path: Path) -> None:
    # CLI flag takes priority; fall back to .srcndx.toml.
    log_file = getattr(args, "log_file", None)
    log_level = getattr(args, "log_level", None)
    if not log_file:
        config = load_config(repo_path)
        log_file = config.log_file
        log_level = log_level or config.log_level
    if log_file:
        configure(Path(log_file), log_level or "INFO")


def cmd_scan(args: argparse.Namespace) -> None:
    repo_path = Path(args.path).resolve()
    if not repo_path.exists():
        print(f"error: path does not exist: {repo_path}", file=sys.stderr)
        sys.exit(1)

    _setup_logging(args, repo_path)
    result = scan(repo_path)
    print(f"scanned {result.files_scanned} files, skipped {result.files_skipped}")

    if args.output:
        out = Path(args.output)
        write(result, out)
        print(f"wrote index to {out}")
    else:
        print(result.model_dump_json(indent=2))


def cmd_watch(args: argparse.Namespace) -> None:
    from srcndx.cache import ScanCache
    from srcndx.debounce import Debouncer
    from srcndx.watcher import Watcher

    repo_path = Path(args.path).resolve()
    if not repo_path.exists():
        print(f"error: path does not exist: {repo_path}", file=sys.stderr)
        sys.exit(1)

    _setup_logging(args, repo_path)
    out = Path(args.output)
    config = load_config(repo_path)
    cache = ScanCache()

    result = scan(repo_path, cache=cache, config=config)
    write(result, out)
    print(f"[initial] scanned {result.files_scanned} files → {out}")
    print(f"watching {repo_path} (debounce {config.debounce_seconds}s) — Ctrl+C to stop")

    watcher = Watcher(repo_path, config=config)
    debouncer = Debouncer(watcher, quiet_seconds=config.debounce_seconds)

    try:
        with debouncer:
            for batch in debouncer.batches():
                changed = {e.path for e in batch}
                result = scan(repo_path, cache=cache, config=config)
                write(result, out)
                print(
                    f"[update] {len(changed)} changed, "
                    f"scanned {result.files_scanned}, "
                    f"skipped {result.files_skipped} → {out}"
                )
    except KeyboardInterrupt:
        print("\nstopped.")


def cmd_map(args: argparse.Namespace) -> None:
    db_path = Path(args.input)
    if not db_path.exists():
        print(f"error: database not found: {db_path}", file=sys.stderr)
        sys.exit(1)

    files = read_map(db_path, path_filter=getattr(args, "filter", None))
    print(_format_map(files))


def _add_log_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--log-file",
        metavar="FILE",
        dest="log_file",
        help="Write log output to FILE (overrides .srcndx.toml).",
    )
    p.add_argument(
        "--log-level",
        metavar="LEVEL",
        dest="log_level",
        default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log verbosity (default: INFO).",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="srcndx",
        description="Index a local repository for use with agents.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    scan_cmd = sub.add_parser("scan", help="Scan a repository and emit an index.")
    scan_cmd.add_argument("path", help="Path to the repository root.")
    scan_cmd.add_argument(
        "-o", "--output",
        metavar="FILE",
        help="Write index to a SQLite file instead of stdout.",
    )
    _add_log_args(scan_cmd)
    scan_cmd.set_defaults(func=cmd_scan)

    watch_cmd = sub.add_parser("watch", help="Watch a repository and keep the index up to date.")
    watch_cmd.add_argument("path", help="Path to the repository root.")
    watch_cmd.add_argument(
        "-o", "--output",
        metavar="FILE",
        required=True,
        help="SQLite file to write and keep up to date.",
    )
    _add_log_args(watch_cmd)
    watch_cmd.set_defaults(func=cmd_watch)

    map_cmd = sub.add_parser("map", help="Emit a compact symbol map from an existing index.")
    map_cmd.add_argument(
        "-i", "--input",
        metavar="FILE",
        required=True,
        help="SQLite index file produced by 'mimir scan -o'.",
    )
    map_cmd.add_argument(
        "--filter",
        metavar="PREFIX",
        help="Only show files whose path starts with PREFIX.",
    )
    map_cmd.set_defaults(func=cmd_map)

    args = parser.parse_args()
    args.func(args)

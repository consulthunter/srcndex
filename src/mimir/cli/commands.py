import argparse
import sys
from pathlib import Path

from mimir.cli.db import write
from mimir.config import load_config
from mimir.log import configure
from mimir.scanner import scan


def _setup_logging(args: argparse.Namespace, repo_path: Path) -> None:
    # CLI flag takes priority; fall back to .mimir.toml.
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
    from mimir.cache import ScanCache
    from mimir.debounce import Debouncer
    from mimir.watcher import Watcher

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


def _add_log_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--log-file",
        metavar="FILE",
        dest="log_file",
        help="Write log output to FILE (overrides .mimir.toml).",
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
        prog="mimir",
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

    args = parser.parse_args()
    args.func(args)

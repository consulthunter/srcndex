import json
import sqlite3
from pathlib import Path

from mimir.models import ScanResult

_SCHEMA = """
CREATE TABLE IF NOT EXISTS scan_results (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_path       TEXT NOT NULL,
    head_commit     TEXT NOT NULL,
    scanned_at      TEXT NOT NULL,
    files_scanned   INTEGER NOT NULL,
    files_skipped   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS indexed_projects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id     INTEGER NOT NULL REFERENCES scan_results(id),
    path        TEXT NOT NULL,
    name        TEXT NOT NULL,
    kind        TEXT NOT NULL,
    build_file  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS indexed_files (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id   INTEGER NOT NULL REFERENCES indexed_projects(id),
    path         TEXT NOT NULL,
    language     TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    git_status   TEXT NOT NULL,
    churn_count  INTEGER NOT NULL,
    imports      TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS indexed_symbols (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id        INTEGER NOT NULL REFERENCES indexed_files(id),
    name           TEXT NOT NULL,
    qualified_name TEXT NOT NULL,
    kind           TEXT NOT NULL,
    parent_name    TEXT,
    start_line     INTEGER NOT NULL,
    end_line       INTEGER NOT NULL,
    visibility     TEXT NOT NULL,
    is_test        INTEGER NOT NULL,
    signature      TEXT NOT NULL,
    annotations    TEXT NOT NULL DEFAULT '[]'
);
"""

# Migrations for databases created before these columns were added.
_MIGRATIONS = [
    "ALTER TABLE indexed_files ADD COLUMN imports TEXT NOT NULL DEFAULT '[]'",
    "ALTER TABLE indexed_symbols ADD COLUMN annotations TEXT NOT NULL DEFAULT '[]'",
]


def write(result: ScanResult, db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.executescript(_SCHEMA)

    for stmt in _MIGRATIONS:
        try:
            con.execute(stmt)
            con.commit()
        except sqlite3.OperationalError:
            pass  # column already exists

    with con:
        # Replace previous scan — the DB always holds the current state, not history.
        con.execute("DELETE FROM indexed_symbols")
        con.execute("DELETE FROM indexed_files")
        con.execute("DELETE FROM indexed_projects")
        con.execute("DELETE FROM scan_results")

        cur = con.execute(
            "INSERT INTO scan_results (repo_path, head_commit, scanned_at, files_scanned, files_skipped) VALUES (?,?,?,?,?)",
            (result.repo_path, result.head_commit, result.scanned_at.isoformat(), result.files_scanned, result.files_skipped),
        )
        scan_id = cur.lastrowid

        for project in result.projects:
            cur = con.execute(
                "INSERT INTO indexed_projects (scan_id, path, name, kind, build_file) VALUES (?,?,?,?,?)",
                (scan_id, project.path, project.name, project.kind, project.build_file),
            )
            project_id = cur.lastrowid

            for file in project.files:
                cur = con.execute(
                    "INSERT INTO indexed_files (project_id, path, language, content_hash, git_status, churn_count, imports) VALUES (?,?,?,?,?,?,?)",
                    (project_id, file.path, file.language, file.content_hash, file.git_status, file.churn_count, json.dumps(file.imports)),
                )
                file_id = cur.lastrowid

                con.executemany(
                    "INSERT INTO indexed_symbols (file_id, name, qualified_name, kind, parent_name, start_line, end_line, visibility, is_test, signature, annotations) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    [
                        (file_id, s.name, s.qualified_name, s.kind, s.parent_name, s.start_line, s.end_line, s.visibility, int(s.is_test), s.signature, json.dumps(s.annotations))
                        for s in file.symbols
                    ],
                )

    con.close()

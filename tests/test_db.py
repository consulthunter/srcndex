import sqlite3
from pathlib import Path

from mimir.cli.db import write
from mimir.scanner import scan

JAVA_SOURCE = b"""
public class Greeter {
    public String greet(String name) {
        return "Hello " + name;
    }
}
"""


def test_write_creates_db_file(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "Greeter.java").write_bytes(JAVA_SOURCE)

    result = scan(repo)
    db_path = tmp_path / "index.db"
    write(result, db_path)

    assert db_path.exists()


def test_write_creates_all_tables(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "Greeter.java").write_bytes(JAVA_SOURCE)

    result = scan(repo)
    db_path = tmp_path / "index.db"
    write(result, db_path)

    con = sqlite3.connect(db_path)
    tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    con.close()

    assert {"scan_results", "indexed_projects", "indexed_files", "indexed_symbols"} <= tables


def test_write_persists_symbols(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "Greeter.java").write_bytes(JAVA_SOURCE)

    result = scan(repo)
    db_path = tmp_path / "index.db"
    write(result, db_path)

    con = sqlite3.connect(db_path)
    symbols = con.execute("SELECT name FROM indexed_symbols").fetchall()
    con.close()

    names = {row[0] for row in symbols}
    assert "Greeter" in names
    assert "greet" in names


def test_write_twice_no_duplicates(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "Greeter.java").write_bytes(JAVA_SOURCE)

    db_path = tmp_path / "index.db"
    write(scan(repo), db_path)
    write(scan(repo), db_path)

    con = sqlite3.connect(db_path)
    assert con.execute("SELECT COUNT(*) FROM scan_results").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM indexed_files").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM indexed_symbols").fetchone()[0] == 2
    con.close()


def test_write_creates_parent_dirs(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "Greeter.java").write_bytes(JAVA_SOURCE)

    result = scan(repo)
    db_path = tmp_path / "deep" / "nested" / "index.db"
    write(result, db_path)

    assert db_path.exists()

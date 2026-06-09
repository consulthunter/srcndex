from pathlib import Path

import pytest

from srcndx.models import SymbolKind, Visibility
from srcndx.parsers.python import PythonParser

SIMPLE_MODULE = b"""
class Service:
    def __init__(self):
        pass

    def process(self):
        pass

    def _helper(self):
        pass

    def __private(self):
        pass


def standalone(x, y):
    return x + y
"""

DECORATED = b"""
import pytest

@pytest.fixture
def my_fixture():
    pass

@pytest.mark.parametrize("x", [1, 2])
def test_something(x):
    pass
"""

NESTED_CLASSES = b"""
class Outer:
    class Inner:
        def method(self):
            pass
"""

ASYNC_FUNCTION = b"""
async def fetch(url: str) -> str:
    pass
"""

IMPORT_MODULE = b"""
import os
import sys
from pathlib import Path
from collections.abc import Generator
"""

TEST_CLASS = b"""
class TestCalculator:
    def test_add(self):
        pass
    def test_subtract(self):
        pass
"""


@pytest.fixture()
def parser() -> PythonParser:
    return PythonParser()


def _extract(parser: PythonParser, source: bytes, tmp_path: Path, filename: str = "module.py"):  # noqa: ANN202
    f = tmp_path / filename
    f.write_bytes(source)
    result = parser.extract(f, filename, "abc123")
    assert result is not None
    return result


def _parse(parser: PythonParser, source: bytes, tmp_path: Path, filename: str = "module.py") -> list:
    f = tmp_path / filename
    f.write_bytes(source)
    result = parser.extract(f, filename, "abc123")
    assert result is not None
    return result.symbols


def test_extracts_class(parser: PythonParser, tmp_path: Path) -> None:
    symbols = _parse(parser, SIMPLE_MODULE, tmp_path)
    classes = [s for s in symbols if s.kind == SymbolKind.CLASS]
    assert len(classes) == 1
    assert classes[0].name == "Service"


def test_extracts_methods(parser: PythonParser, tmp_path: Path) -> None:
    symbols = _parse(parser, SIMPLE_MODULE, tmp_path)
    methods = {s.name for s in symbols if s.kind == SymbolKind.METHOD}
    assert "process" in methods
    assert "_helper" in methods


def test_init_is_constructor(parser: PythonParser, tmp_path: Path) -> None:
    symbols = _parse(parser, SIMPLE_MODULE, tmp_path)
    ctors = [s for s in symbols if s.kind == SymbolKind.CONSTRUCTOR]
    assert len(ctors) == 1
    assert ctors[0].name == "__init__"


def test_standalone_function_is_function_kind(parser: PythonParser, tmp_path: Path) -> None:
    symbols = _parse(parser, SIMPLE_MODULE, tmp_path)
    fns = [s for s in symbols if s.kind == SymbolKind.FUNCTION]
    assert any(s.name == "standalone" for s in fns)


def test_visibility_conventions(parser: PythonParser, tmp_path: Path) -> None:
    symbols = _parse(parser, SIMPLE_MODULE, tmp_path)
    by_name = {s.name: s for s in symbols}
    assert by_name["process"].visibility == Visibility.PUBLIC
    assert by_name["_helper"].visibility == Visibility.PROTECTED
    assert by_name["__private"].visibility == Visibility.PRIVATE


def test_qualified_name_with_parent(parser: PythonParser, tmp_path: Path) -> None:
    symbols = _parse(parser, SIMPLE_MODULE, tmp_path)
    process = next(s for s in symbols if s.name == "process")
    assert process.qualified_name == "Service.process"
    assert process.parent_name == "Service"


def test_decorated_fixture_not_test(parser: PythonParser, tmp_path: Path) -> None:
    symbols = _parse(parser, DECORATED, tmp_path)
    fixture = next(s for s in symbols if s.name == "my_fixture")
    assert fixture.is_test is False


def test_decorated_test_is_marked(parser: PythonParser, tmp_path: Path) -> None:
    symbols = _parse(parser, DECORATED, tmp_path)
    test_fn = next(s for s in symbols if s.name == "test_something")
    assert test_fn.is_test is True


def test_nested_class_qualified_name(parser: PythonParser, tmp_path: Path) -> None:
    symbols = _parse(parser, NESTED_CLASSES, tmp_path)
    inner = next(s for s in symbols if s.name == "Inner")
    assert inner.qualified_name == "Outer.Inner"
    method = next(s for s in symbols if s.name == "method")
    assert method.qualified_name == "Outer.Inner.method"


def test_async_function_extracted(parser: PythonParser, tmp_path: Path) -> None:
    symbols = _parse(parser, ASYNC_FUNCTION, tmp_path)
    assert any(s.name == "fetch" for s in symbols)


def test_test_class_is_marked(parser: PythonParser, tmp_path: Path) -> None:
    symbols = _parse(parser, TEST_CLASS, tmp_path)
    cls = next(s for s in symbols if s.kind == SymbolKind.CLASS)
    assert cls.is_test is True


def test_test_method_name_is_marked(parser: PythonParser, tmp_path: Path) -> None:
    symbols = _parse(parser, TEST_CLASS, tmp_path)
    methods = [s for s in symbols if s.kind == SymbolKind.METHOD]
    assert all(s.is_test for s in methods)


def test_file_in_tests_dir_marks_all(parser: PythonParser, tmp_path: Path) -> None:
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    f = tests_dir / "module.py"
    f.write_bytes(b"def something(): pass")
    result = parser.extract(f, "tests/module.py", "abc123")
    assert result is not None
    assert result.symbols[0].is_test is True


def test_imports_extracted(parser: PythonParser, tmp_path: Path) -> None:
    indexed = _extract(parser, IMPORT_MODULE, tmp_path)
    assert "os" in indexed.imports
    assert "sys" in indexed.imports
    assert "pathlib" in indexed.imports
    assert "collections.abc" in indexed.imports


def test_no_imports_when_absent(parser: PythonParser, tmp_path: Path) -> None:
    indexed = _extract(parser, SIMPLE_MODULE, tmp_path)
    assert indexed.imports == []


def test_annotations_stored_on_decorated_function(parser: PythonParser, tmp_path: Path) -> None:
    symbols = _parse(parser, DECORATED, tmp_path)
    test_fn = next(s for s in symbols if s.name == "test_something")
    assert any("pytest.mark.parametrize" in a for a in test_fn.annotations)


def test_no_annotations_on_plain_function(parser: PythonParser, tmp_path: Path) -> None:
    symbols = _parse(parser, SIMPLE_MODULE, tmp_path)
    standalone = next(s for s in symbols if s.name == "standalone")
    assert standalone.annotations == []

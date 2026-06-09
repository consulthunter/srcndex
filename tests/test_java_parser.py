from pathlib import Path

import pytest

from srcndx.models import SymbolKind, Visibility
from srcndx.parsers.java import JavaParser

SIMPLE_CLASS = b"""
public class Calculator {
    private int value;

    public Calculator() {
        this.value = 0;
    }

    public int add(int a, int b) {
        return a + b;
    }

    private void reset() {
        this.value = 0;
    }
}
"""

INTERFACE_SOURCE = b"""
public interface Processor {
    void process();
    int getCount();
}
"""

NESTED_CLASS = b"""
public class Outer {
    public class Inner {
        public void doWork() {}
    }
}
"""

TEST_CLASS = b"""
import org.junit.jupiter.api.Test;

public class CalculatorTest {
    @Test
    public void testAdd() {
        // ...
    }
}
"""


@pytest.fixture()
def parser() -> JavaParser:
    return JavaParser()


def _parse(parser: JavaParser, source: bytes, tmp_path: Path) -> list:
    f = tmp_path / "Source.java"
    f.write_bytes(source)
    result = parser.extract(f, "Source.java", "abc123")
    assert result is not None
    return result.symbols


def _extract(parser: JavaParser, source: bytes, tmp_path: Path):  # noqa: ANN202
    f = tmp_path / "Source.java"
    f.write_bytes(source)
    result = parser.extract(f, "Source.java", "abc123")
    assert result is not None
    return result


def test_extracts_class(parser: JavaParser, tmp_path: Path) -> None:
    symbols = _parse(parser, SIMPLE_CLASS, tmp_path)
    classes = [s for s in symbols if s.kind == SymbolKind.CLASS]
    assert len(classes) == 1
    assert classes[0].name == "Calculator"
    assert classes[0].visibility == Visibility.PUBLIC


def test_extracts_constructor(parser: JavaParser, tmp_path: Path) -> None:
    symbols = _parse(parser, SIMPLE_CLASS, tmp_path)
    ctors = [s for s in symbols if s.kind == SymbolKind.CONSTRUCTOR]
    assert len(ctors) == 1
    assert ctors[0].name == "Calculator"


def test_extracts_methods(parser: JavaParser, tmp_path: Path) -> None:
    symbols = _parse(parser, SIMPLE_CLASS, tmp_path)
    methods = [s for s in symbols if s.kind == SymbolKind.METHOD]
    names = {m.name for m in methods}
    assert "add" in names
    assert "reset" in names


def test_method_visibility(parser: JavaParser, tmp_path: Path) -> None:
    symbols = _parse(parser, SIMPLE_CLASS, tmp_path)
    add = next(s for s in symbols if s.name == "add")
    reset = next(s for s in symbols if s.name == "reset")
    assert add.visibility == Visibility.PUBLIC
    assert reset.visibility == Visibility.PRIVATE


def test_qualified_name_uses_parent(parser: JavaParser, tmp_path: Path) -> None:
    symbols = _parse(parser, SIMPLE_CLASS, tmp_path)
    add = next(s for s in symbols if s.name == "add")
    assert add.qualified_name == "Calculator.add"
    assert add.parent_name == "Calculator"


def test_extracts_interface(parser: JavaParser, tmp_path: Path) -> None:
    symbols = _parse(parser, INTERFACE_SOURCE, tmp_path)
    interfaces = [s for s in symbols if s.kind == SymbolKind.INTERFACE]
    assert len(interfaces) == 1
    assert interfaces[0].name == "Processor"


def test_nested_class_qualified_name(parser: JavaParser, tmp_path: Path) -> None:
    symbols = _parse(parser, NESTED_CLASS, tmp_path)
    inner = next(s for s in symbols if s.name == "Inner")
    assert inner.qualified_name == "Outer.Inner"
    assert inner.parent_name == "Outer"


def test_nested_method_qualified_name(parser: JavaParser, tmp_path: Path) -> None:
    symbols = _parse(parser, NESTED_CLASS, tmp_path)
    method = next(s for s in symbols if s.name == "doWork")
    assert method.qualified_name == "Outer.Inner.doWork"


def test_test_class_is_marked(parser: JavaParser, tmp_path: Path) -> None:
    symbols = _parse(parser, TEST_CLASS, tmp_path)
    cls = next(s for s in symbols if s.kind == SymbolKind.CLASS)
    assert cls.is_test is True


def test_test_method_is_marked(parser: JavaParser, tmp_path: Path) -> None:
    symbols = _parse(parser, TEST_CLASS, tmp_path)
    method = next(s for s in symbols if s.name == "testAdd")
    assert method.is_test is True


def test_line_numbers(parser: JavaParser, tmp_path: Path) -> None:
    symbols = _parse(parser, SIMPLE_CLASS, tmp_path)
    cls = next(s for s in symbols if s.kind == SymbolKind.CLASS)
    assert cls.start_line >= 1
    assert cls.end_line > cls.start_line


def test_imports_extracted(parser: JavaParser, tmp_path: Path) -> None:
    indexed = _extract(parser, TEST_CLASS, tmp_path)
    assert "org.junit.jupiter.api.Test" in indexed.imports


def test_no_imports_when_absent(parser: JavaParser, tmp_path: Path) -> None:
    indexed = _extract(parser, SIMPLE_CLASS, tmp_path)
    assert indexed.imports == []


def test_annotations_stored_on_method(parser: JavaParser, tmp_path: Path) -> None:
    symbols = _parse(parser, TEST_CLASS, tmp_path)
    method = next(s for s in symbols if s.name == "testAdd")
    assert "@Test" in method.annotations


def test_no_annotations_on_plain_method(parser: JavaParser, tmp_path: Path) -> None:
    symbols = _parse(parser, SIMPLE_CLASS, tmp_path)
    add = next(s for s in symbols if s.name == "add")
    assert add.annotations == []

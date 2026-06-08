from pathlib import Path

import pytest

from mimir.models import SymbolKind, Visibility
from mimir.parsers.csharp import CSharpParser

SIMPLE_CLASS = b"""
namespace MyApp {
    public class Calculator {
        public int Add(int a, int b) { return a + b; }
        private void Reset() {}
        public Calculator() {}
        public string Name { get; set; }
    }
}
"""

INTERFACE = b"""
namespace MyApp {
    public interface IProcessor {
        void Process();
        int GetCount();
    }
}
"""

NESTED_CLASS = b"""
namespace MyApp {
    public class Outer {
        public class Inner {
            public void DoWork() {}
        }
    }
}
"""

TEST_CLASS = b"""
using NUnit.Framework;

namespace MyApp.Tests {
    [TestFixture]
    public class CalculatorTests {
        [Test]
        public void TestAdd() {}

        [Theory]
        public void TestSubtract() {}
    }
}
"""

XUNIT_CLASS = b"""
using Xunit;

namespace MyApp.Tests {
    public class ServiceTests {
        [Fact]
        public void ShouldReturnTrue() {}
    }
}
"""

NO_NAMESPACE = b"""
public class Standalone {
    public void Run() {}
}
"""


@pytest.fixture()
def parser() -> CSharpParser:
    return CSharpParser()


def _extract(parser: CSharpParser, source: bytes, tmp_path: Path, filename: str = "Source.cs"):  # noqa: ANN202
    f = tmp_path / filename
    f.write_bytes(source)
    result = parser.extract(f, filename, "abc123")
    assert result is not None
    return result


def _parse(parser: CSharpParser, source: bytes, tmp_path: Path, filename: str = "Source.cs") -> list:
    f = tmp_path / filename
    f.write_bytes(source)
    result = parser.extract(f, filename, "abc123")
    assert result is not None
    return result.symbols


def test_extracts_class(parser: CSharpParser, tmp_path: Path) -> None:
    symbols = _parse(parser, SIMPLE_CLASS, tmp_path)
    classes = [s for s in symbols if s.kind == SymbolKind.CLASS]
    assert len(classes) == 1
    assert classes[0].name == "Calculator"


def test_class_qualified_name_includes_namespace(parser: CSharpParser, tmp_path: Path) -> None:
    symbols = _parse(parser, SIMPLE_CLASS, tmp_path)
    cls = next(s for s in symbols if s.kind == SymbolKind.CLASS)
    assert cls.qualified_name == "MyApp.Calculator"


def test_extracts_methods(parser: CSharpParser, tmp_path: Path) -> None:
    symbols = _parse(parser, SIMPLE_CLASS, tmp_path)
    methods = {s.name for s in symbols if s.kind == SymbolKind.METHOD}
    assert "Add" in methods
    assert "Reset" in methods


def test_extracts_constructor(parser: CSharpParser, tmp_path: Path) -> None:
    symbols = _parse(parser, SIMPLE_CLASS, tmp_path)
    ctors = [s for s in symbols if s.kind == SymbolKind.CONSTRUCTOR]
    assert len(ctors) == 1
    assert ctors[0].name == "Calculator"


def test_extracts_property(parser: CSharpParser, tmp_path: Path) -> None:
    symbols = _parse(parser, SIMPLE_CLASS, tmp_path)
    props = [s for s in symbols if s.kind == SymbolKind.PROPERTY]
    assert any(s.name == "Name" for s in props)


def test_method_visibility(parser: CSharpParser, tmp_path: Path) -> None:
    symbols = _parse(parser, SIMPLE_CLASS, tmp_path)
    by_name = {s.name: s for s in symbols}
    assert by_name["Add"].visibility == Visibility.PUBLIC
    assert by_name["Reset"].visibility == Visibility.PRIVATE


def test_extracts_interface(parser: CSharpParser, tmp_path: Path) -> None:
    symbols = _parse(parser, INTERFACE, tmp_path)
    ifaces = [s for s in symbols if s.kind == SymbolKind.INTERFACE]
    assert len(ifaces) == 1
    assert ifaces[0].name == "IProcessor"


def test_interface_methods_extracted(parser: CSharpParser, tmp_path: Path) -> None:
    symbols = _parse(parser, INTERFACE, tmp_path)
    methods = {s.name for s in symbols if s.kind == SymbolKind.METHOD}
    assert "Process" in methods
    assert "GetCount" in methods


def test_nested_class_qualified_name(parser: CSharpParser, tmp_path: Path) -> None:
    symbols = _parse(parser, NESTED_CLASS, tmp_path)
    inner = next(s for s in symbols if s.name == "Inner")
    assert inner.qualified_name == "MyApp.Outer.Inner"


def test_nunit_test_class_marked(parser: CSharpParser, tmp_path: Path) -> None:
    symbols = _parse(parser, TEST_CLASS, tmp_path)
    cls = next(s for s in symbols if s.kind == SymbolKind.CLASS)
    assert cls.is_test is True


def test_nunit_test_methods_marked(parser: CSharpParser, tmp_path: Path) -> None:
    symbols = _parse(parser, TEST_CLASS, tmp_path)
    methods = [s for s in symbols if s.kind == SymbolKind.METHOD]
    assert all(s.is_test for s in methods)


def test_xunit_fact_marked(parser: CSharpParser, tmp_path: Path) -> None:
    symbols = _parse(parser, XUNIT_CLASS, tmp_path)
    method = next(s for s in symbols if s.name == "ShouldReturnTrue")
    assert method.is_test is True


def test_no_namespace_fallback(parser: CSharpParser, tmp_path: Path) -> None:
    symbols = _parse(parser, NO_NAMESPACE, tmp_path)
    cls = next(s for s in symbols if s.kind == SymbolKind.CLASS)
    assert cls.qualified_name == "Standalone"
    assert cls.name == "Standalone"


def test_imports_extracted(parser: CSharpParser, tmp_path: Path) -> None:
    indexed = _extract(parser, TEST_CLASS, tmp_path)
    assert "NUnit.Framework" in indexed.imports


def test_no_imports_when_absent(parser: CSharpParser, tmp_path: Path) -> None:
    indexed = _extract(parser, NO_NAMESPACE, tmp_path)
    assert indexed.imports == []


def test_annotations_on_test_method(parser: CSharpParser, tmp_path: Path) -> None:
    symbols = _parse(parser, TEST_CLASS, tmp_path)
    test_method = next(s for s in symbols if s.name == "TestAdd")
    assert "Test" in test_method.annotations


def test_no_annotations_on_plain_method(parser: CSharpParser, tmp_path: Path) -> None:
    symbols = _parse(parser, SIMPLE_CLASS, tmp_path)
    add = next(s for s in symbols if s.name == "Add")
    assert add.annotations == []

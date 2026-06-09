from pathlib import Path

import pytest

from srcndx.models import SymbolKind, Visibility
from srcndx.parsers.typescript import TypeScriptParser

SIMPLE_CLASS = b"""
class PaymentService {
    private name: string;
    public process(): void {}
    constructor(name: string) {}
}
"""

INTERFACE = b"""
interface IProcessor {
    process(): void;
    getCount(): number;
}
"""

ABSTRACT_CLASS = b"""
abstract class Base {
    protected abstract run(): void;
    public execute(): void {}
}
"""

EXPORTED_FUNCTION = b"""
export function helper(x: number): string {
    return String(x);
}

export function calculate(a: number, b: number): number {
    return a + b;
}
"""

NESTED_CLASS = b"""
class Outer {
    class Inner {
        doWork(): void {}
    }
}
"""

TSX_COMPONENT = b"""
interface ButtonProps {
    label: string;
}

class Button {
    private props: ButtonProps;
    render(): string { return ''; }
}
"""

TS_IMPORTS = b"""
import React from 'react';
import { useState } from 'react';
import type { FC } from 'react';

class Component {}
"""


@pytest.fixture()
def parser() -> TypeScriptParser:
    return TypeScriptParser(tsx=False)


@pytest.fixture()
def tsx_parser() -> TypeScriptParser:
    return TypeScriptParser(tsx=True)


def _extract(parser: TypeScriptParser, source: bytes, tmp_path: Path, filename: str = "module.ts"):  # noqa: ANN202
    f = tmp_path / filename
    f.write_bytes(source)
    result = parser.extract(f, filename, "abc123")
    assert result is not None
    return result


def _parse(parser: TypeScriptParser, source: bytes, tmp_path: Path, filename: str = "module.ts") -> list:
    f = tmp_path / filename
    f.write_bytes(source)
    result = parser.extract(f, filename, "abc123")
    assert result is not None
    return result.symbols


def test_extracts_class(parser: TypeScriptParser, tmp_path: Path) -> None:
    symbols = _parse(parser, SIMPLE_CLASS, tmp_path)
    classes = [s for s in symbols if s.kind == SymbolKind.CLASS]
    assert len(classes) == 1
    assert classes[0].name == "PaymentService"


def test_extracts_methods(parser: TypeScriptParser, tmp_path: Path) -> None:
    symbols = _parse(parser, SIMPLE_CLASS, tmp_path)
    methods = {s.name for s in symbols if s.kind == SymbolKind.METHOD}
    assert "process" in methods


def test_extracts_constructor(parser: TypeScriptParser, tmp_path: Path) -> None:
    symbols = _parse(parser, SIMPLE_CLASS, tmp_path)
    ctors = [s for s in symbols if s.kind == SymbolKind.CONSTRUCTOR]
    assert len(ctors) == 1


def test_extracts_field(parser: TypeScriptParser, tmp_path: Path) -> None:
    symbols = _parse(parser, SIMPLE_CLASS, tmp_path)
    fields = [s for s in symbols if s.kind == SymbolKind.FIELD]
    assert any(s.name == "name" for s in fields)


def test_field_visibility(parser: TypeScriptParser, tmp_path: Path) -> None:
    symbols = _parse(parser, SIMPLE_CLASS, tmp_path)
    name_field = next(s for s in symbols if s.name == "name")
    assert name_field.visibility == Visibility.PRIVATE


def test_method_visibility(parser: TypeScriptParser, tmp_path: Path) -> None:
    symbols = _parse(parser, SIMPLE_CLASS, tmp_path)
    process = next(s for s in symbols if s.name == "process")
    assert process.visibility == Visibility.PUBLIC


def test_method_qualified_name(parser: TypeScriptParser, tmp_path: Path) -> None:
    symbols = _parse(parser, SIMPLE_CLASS, tmp_path)
    process = next(s for s in symbols if s.name == "process")
    assert process.qualified_name == "PaymentService.process"
    assert process.parent_name == "PaymentService"


def test_extracts_interface(parser: TypeScriptParser, tmp_path: Path) -> None:
    symbols = _parse(parser, INTERFACE, tmp_path)
    ifaces = [s for s in symbols if s.kind == SymbolKind.INTERFACE]
    assert len(ifaces) == 1
    assert ifaces[0].name == "IProcessor"


def test_extracts_exported_functions(parser: TypeScriptParser, tmp_path: Path) -> None:
    symbols = _parse(parser, EXPORTED_FUNCTION, tmp_path)
    fns = {s.name for s in symbols if s.kind == SymbolKind.FUNCTION}
    assert "helper" in fns
    assert "calculate" in fns


def test_abstract_class_extracted(parser: TypeScriptParser, tmp_path: Path) -> None:
    symbols = _parse(parser, ABSTRACT_CLASS, tmp_path)
    classes = [s for s in symbols if s.kind == SymbolKind.CLASS]
    assert any(s.name == "Base" for s in classes)


def test_test_file_marks_symbols(parser: TypeScriptParser, tmp_path: Path) -> None:
    f = tmp_path / "service.test.ts"
    f.write_bytes(b"class Foo { run(): void {} }")
    result = parser.extract(f, "service.test.ts", "abc123")
    assert result is not None
    assert all(s.is_test for s in result.symbols)


def test_spec_file_marks_symbols(parser: TypeScriptParser, tmp_path: Path) -> None:
    f = tmp_path / "service.spec.ts"
    f.write_bytes(b"class Foo { run(): void {} }")
    result = parser.extract(f, "service.spec.ts", "abc123")
    assert result is not None
    assert all(s.is_test for s in result.symbols)


def test_tsx_parser_language(tsx_parser: TypeScriptParser, tmp_path: Path) -> None:
    symbols = _parse(tsx_parser, TSX_COMPONENT, tmp_path, filename="Button.tsx")
    assert any(s.name == "Button" for s in symbols)
    assert any(s.name == "ButtonProps" for s in symbols)


def test_tsx_file_language_field(tsx_parser: TypeScriptParser, tmp_path: Path) -> None:
    f = tmp_path / "Button.tsx"
    f.write_bytes(b"class X {}")
    result = tsx_parser.extract(f, "Button.tsx", "abc")
    assert result is not None
    assert result.language == "tsx"


def test_imports_extracted(parser: TypeScriptParser, tmp_path: Path) -> None:
    indexed = _extract(parser, TS_IMPORTS, tmp_path)
    assert "react" in indexed.imports


def test_no_imports_when_absent(parser: TypeScriptParser, tmp_path: Path) -> None:
    indexed = _extract(parser, SIMPLE_CLASS, tmp_path)
    assert indexed.imports == []

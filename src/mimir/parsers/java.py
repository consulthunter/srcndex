from pathlib import Path

import tree_sitter_java
from tree_sitter import Language, Node

from mimir.models import (
    GitStatus,
    IndexedFile,
    IndexedSymbol,
    SymbolKind,
    Visibility,
)
from mimir.parsers.base import BaseParser

_VISIBILITY_KEYWORDS = {"public", "private", "protected"}

_TEST_ANNOTATIONS = {"@Test", "@ParameterizedTest", "@RepeatedTest", "@TestFactory"}


def _visibility(modifiers: Node, source: bytes) -> Visibility:
    for child in modifiers.children:
        text = source[child.start_byte:child.end_byte].decode()
        if text in _VISIBILITY_KEYWORDS:
            return Visibility(text)
    return Visibility.UNKNOWN


def _is_test_annotation(annotations: list[str]) -> bool:
    return bool(_TEST_ANNOTATIONS.intersection(annotations))


def _is_test_class(class_name: str, file_path: str) -> bool:
    name = class_name.lower()
    path = file_path.lower()
    return "test" in name or "/test/" in path or "\\test\\" in path


class JavaParser(BaseParser):
    language_name = "java"

    def __init__(self) -> None:
        super().__init__(Language(tree_sitter_java.language()))

    def extract(self, path: Path, rel_path: str, content_hash: str) -> IndexedFile | None:
        tree = self.parse_file(path)
        if tree is None:
            return None

        source = path.read_bytes()
        symbols: list[IndexedSymbol] = []
        imports = self._extract_imports(tree.root_node, source)

        self._walk_declarations(tree.root_node, source, rel_path, symbols, parent=None)

        return IndexedFile(
            path=rel_path,
            language="java",
            content_hash=content_hash,
            git_status=GitStatus.UNCHANGED,
            churn_count=0,
            symbols=symbols,
            imports=imports,
        )

    def _extract_imports(self, root: Node, source: bytes) -> list[str]:
        imports: list[str] = []
        for child in root.children:
            if child.type == "import_declaration":
                text = self.node_text(child, source).strip()
                text = text.removeprefix("import ").removesuffix(";").strip()
                text = text.removeprefix("static ").strip()
                if text:
                    imports.append(text)
        return imports

    def _walk_declarations(
        self,
        node: Node,
        source: bytes,
        file_path: str,
        symbols: list[IndexedSymbol],
        parent: str | None,
    ) -> None:
        for child in node.children:
            if child.type in ("class_declaration", "interface_declaration", "enum_declaration"):
                self._process_type_declaration(child, source, file_path, symbols, parent)
            elif child.type in ("method_declaration", "constructor_declaration"):
                self._process_method(child, source, file_path, symbols, parent)
            else:
                self._walk_declarations(child, source, file_path, symbols, parent)

    def _process_type_declaration(
        self,
        node: Node,
        source: bytes,
        file_path: str,
        symbols: list[IndexedSymbol],
        parent: str | None,
    ) -> None:
        kind_map = {
            "class_declaration": SymbolKind.CLASS,
            "interface_declaration": SymbolKind.INTERFACE,
            "enum_declaration": SymbolKind.ENUM,
        }
        kind = kind_map[node.type]

        name_node = self.first_child_of_type(node, "identifier")
        if name_node is None:
            return
        name = self.node_text(name_node, source)
        qualified = f"{parent}.{name}" if parent else name

        modifiers_node = self.first_child_of_type(node, "modifiers")
        vis = _visibility(modifiers_node, source) if modifiers_node else Visibility.UNKNOWN

        annotations = self._collect_annotations(modifiers_node, source) if modifiers_node else []
        is_test = _is_test_class(name, file_path) or _is_test_annotation(annotations)

        sig = self.node_text(node, source).split("{")[0].strip()

        symbols.append(
            IndexedSymbol(
                name=name,
                qualified_name=qualified,
                kind=kind,
                parent_name=parent,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                visibility=vis,
                is_test=is_test,
                signature=sig,
                annotations=annotations,
            )
        )

        body = self.first_child_of_type(node, "class_body", "interface_body", "enum_body")
        if body:
            self._walk_declarations(body, source, file_path, symbols, parent=qualified)

    def _process_method(
        self,
        node: Node,
        source: bytes,
        file_path: str,
        symbols: list[IndexedSymbol],
        parent: str | None,
    ) -> None:
        kind = (
            SymbolKind.CONSTRUCTOR
            if node.type == "constructor_declaration"
            else SymbolKind.METHOD
        )

        name_node = self.first_child_of_type(node, "identifier")
        if name_node is None:
            return
        name = self.node_text(name_node, source)
        qualified = f"{parent}.{name}" if parent else name

        modifiers_node = self.first_child_of_type(node, "modifiers")
        vis = _visibility(modifiers_node, source) if modifiers_node else Visibility.UNKNOWN
        annotations = self._collect_annotations(modifiers_node, source) if modifiers_node else []
        is_test = _is_test_annotation(annotations)

        sig = self._method_signature(node, source)

        symbols.append(
            IndexedSymbol(
                name=name,
                qualified_name=qualified,
                kind=kind,
                parent_name=parent,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                visibility=vis,
                is_test=is_test,
                signature=sig,
                annotations=annotations,
            )
        )

    def _collect_annotations(self, modifiers_node: Node, source: bytes) -> list[str]:
        annotations = []
        for child in modifiers_node.children:
            if child.type == "marker_annotation":
                annotations.append(self.node_text(child, source))
        return annotations

    def _method_signature(self, node: Node, source: bytes) -> str:
        body = self.first_child_of_type(node, "block")
        if body:
            sig_bytes = source[node.start_byte:body.start_byte]
            return sig_bytes.decode("utf-8", errors="replace").strip()
        return self.node_text(node, source).strip()

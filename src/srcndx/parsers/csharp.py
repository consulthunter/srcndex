from pathlib import Path

import tree_sitter_c_sharp
from tree_sitter import Language, Node

from srcndx.analysis import classify_test, detect_endpoint, detect_test_framework
from srcndx.models import (
    GitStatus,
    IndexedFile,
    IndexedSymbol,
    SymbolKind,
    Visibility,
)
from srcndx.parsers.base import BaseParser

_VISIBILITY_KEYWORDS = {"public", "private", "protected", "internal"}

_TEST_ATTRIBUTES = {
    "Test", "TestMethod", "Fact", "Theory",
    "TestCase", "TestFixture", "InlineData",
}


def _visibility(node: Node, source: bytes) -> Visibility:
    for child in node.children:
        if child.type == "modifier":
            text = source[child.start_byte:child.end_byte].decode()
            if text in _VISIBILITY_KEYWORDS:
                return Visibility(text) if text != "internal" else Visibility.INTERNAL
    return Visibility.UNKNOWN


def _collect_attributes(node: Node, source: bytes) -> list[str]:
    """Return full attribute text (e.g. 'HttpGet("/path")') for each attribute."""
    attrs: list[str] = []
    for child in node.children:
        if child.type == "attribute_list":
            for attr in child.children:
                if attr.type == "attribute":
                    attrs.append(source[attr.start_byte:attr.end_byte].decode("utf-8", errors="replace"))
    return attrs


def _is_test(name: str, file_path: str, attributes: list[str]) -> bool:
    # Strip argument lists before checking names, e.g. "InlineData(1,2)" → "InlineData"
    attr_names = {a.split("(")[0].strip() for a in attributes}
    path = file_path.lower()
    return (
        bool(_TEST_ATTRIBUTES.intersection(attr_names))
        or "test" in path.rsplit("/", 1)[-1].lower()
        or name.lower().startswith("test")
    )


class CSharpParser(BaseParser):
    language_name = "csharp"

    def __init__(self) -> None:
        super().__init__(Language(tree_sitter_c_sharp.language()))

    def extract(self, path: Path, rel_path: str, content_hash: str) -> IndexedFile | None:
        tree = self.parse_file(path)
        if tree is None:
            return None

        source = path.read_bytes()
        symbols: list[IndexedSymbol] = []
        imports = self._extract_imports(tree.root_node, source)
        self._walk(tree.root_node, source, rel_path, symbols, parent=None, namespace=None)

        return IndexedFile(
            path=rel_path,
            language="csharp",
            content_hash=content_hash,
            git_status=GitStatus.UNCHANGED,
            churn_count=0,
            symbols=symbols,
            imports=imports,
            test_framework=detect_test_framework(imports, "csharp"),
        )

    def _extract_imports(self, root: Node, source: bytes) -> list[str]:
        imports: list[str] = []
        for child in root.children:
            if child.type == "using_directive":
                text = self.node_text(child, source).strip()
                text = text.removeprefix("using ").removesuffix(";").strip()
                text = text.removeprefix("static ").strip()
                if "=" in text:
                    text = text.split("=", 1)[1].strip()
                if text:
                    imports.append(text)
        return imports

    def _walk(
        self,
        node: Node,
        source: bytes,
        file_path: str,
        symbols: list[IndexedSymbol],
        parent: str | None,
        namespace: str | None,
    ) -> None:
        for child in node.children:
            if child.type == "namespace_declaration":
                self._process_namespace(child, source, file_path, symbols, parent)
            elif child.type in (
                "class_declaration",
                "interface_declaration",
                "enum_declaration",
                "struct_declaration",
            ):
                self._process_type(child, source, file_path, symbols, parent, namespace)
            elif child.type in ("method_declaration", "constructor_declaration"):
                self._process_method(child, source, file_path, symbols, parent, namespace)
            elif child.type == "property_declaration":
                self._process_property(child, source, file_path, symbols, parent, namespace)
            elif child.type == "declaration_list":
                self._walk(child, source, file_path, symbols, parent, namespace)

    def _process_namespace(
        self,
        node: Node,
        source: bytes,
        file_path: str,
        symbols: list[IndexedSymbol],
        parent: str | None,
    ) -> None:
        name_node = self.first_child_of_type(node, "identifier", "qualified_name")
        ns = self.node_text(name_node, source) if name_node else None
        body = self.first_child_of_type(node, "declaration_list")
        if body:
            self._walk(body, source, file_path, symbols, parent=parent, namespace=ns)

    def _process_type(
        self,
        node: Node,
        source: bytes,
        file_path: str,
        symbols: list[IndexedSymbol],
        parent: str | None,
        namespace: str | None,
    ) -> None:
        kind_map = {
            "class_declaration": SymbolKind.CLASS,
            "interface_declaration": SymbolKind.INTERFACE,
            "enum_declaration": SymbolKind.ENUM,
            "struct_declaration": SymbolKind.CLASS,
        }
        kind = kind_map[node.type]

        name_node = self.first_child_of_type(node, "identifier")
        if name_node is None:
            return
        name = self.node_text(name_node, source)

        if parent:
            qualified = f"{parent}.{name}"
        elif namespace:
            qualified = f"{namespace}.{name}"
        else:
            qualified = name

        vis = _visibility(node, source)
        attrs = _collect_attributes(node, source)
        sig = self.node_text(node, source).split("{")[0].strip()
        is_test = _is_test(name, file_path, attrs)
        is_ep, http_method, route_path = detect_endpoint(attrs)
        tk = classify_test(file_path, attrs) if is_test else None

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
                annotations=attrs,
                is_endpoint=is_ep,
                http_method=http_method,
                route_path=route_path,
                test_kind=tk,
            )
        )

        body = self.first_child_of_type(node, "declaration_list")
        if body:
            self._walk(body, source, file_path, symbols, parent=qualified, namespace=namespace)

    def _process_method(
        self,
        node: Node,
        source: bytes,
        file_path: str,
        symbols: list[IndexedSymbol],
        parent: str | None,
        namespace: str | None,
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

        vis = _visibility(node, source)
        attrs = _collect_attributes(node, source)

        body = self.first_child_of_type(node, "block")
        sig_end = body.start_byte if body else node.end_byte
        sig = source[node.start_byte:sig_end].decode("utf-8", errors="replace").strip()
        is_test = _is_test(name, file_path, attrs)
        is_ep, http_method, route_path = detect_endpoint(attrs)
        tk = classify_test(file_path, attrs) if is_test else None

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
                annotations=attrs,
                is_endpoint=is_ep,
                http_method=http_method,
                route_path=route_path,
                test_kind=tk,
            )
        )

    def _process_property(
        self,
        node: Node,
        source: bytes,
        file_path: str,
        symbols: list[IndexedSymbol],
        parent: str | None,
        namespace: str | None,
    ) -> None:
        name_node = self.first_child_of_type(node, "identifier")
        if name_node is None:
            return
        name = self.node_text(name_node, source)
        qualified = f"{parent}.{name}" if parent else name

        vis = _visibility(node, source)
        attrs = _collect_attributes(node, source)
        sig = self.node_text(node, source).split("{")[0].strip()

        symbols.append(
            IndexedSymbol(
                name=name,
                qualified_name=qualified,
                kind=SymbolKind.PROPERTY,
                parent_name=parent,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                visibility=vis,
                is_test=False,
                signature=sig,
                annotations=attrs,
            )
        )


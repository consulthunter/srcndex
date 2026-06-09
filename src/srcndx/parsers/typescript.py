from pathlib import Path

import tree_sitter_typescript
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

_VISIBILITY_KEYWORDS = {"public", "private", "protected"}


def _visibility(node: Node, source: bytes) -> Visibility:
    mod = next(
        (c for c in node.children if c.type == "accessibility_modifier"), None
    )
    if mod is None:
        return Visibility.PUBLIC
    text = source[mod.start_byte:mod.end_byte].decode()
    return Visibility(text) if text in _VISIBILITY_KEYWORDS else Visibility.PUBLIC


def _is_test(name: str, file_path: str) -> bool:
    path = file_path.lower()
    return (
        ".test." in path
        or ".spec." in path
        or "/test/" in path
        or "/tests/" in path
        or name.lower().startswith("test")
    )


def _collect_decorators(node: Node, source: bytes) -> list[str]:
    return [
        source[c.start_byte:c.end_byte].decode("utf-8", errors="replace")
        for c in node.children
        if c.type == "decorator"
    ]


class TypeScriptParser(BaseParser):
    language_name = "typescript"

    def __init__(self, tsx: bool = False) -> None:
        lang = (
            Language(tree_sitter_typescript.language_tsx())
            if tsx
            else Language(tree_sitter_typescript.language_typescript())
        )
        super().__init__(lang)
        self._tsx = tsx

    def extract(self, path: Path, rel_path: str, content_hash: str) -> IndexedFile | None:
        tree = self.parse_file(path)
        if tree is None:
            return None

        source = path.read_bytes()
        symbols: list[IndexedSymbol] = []
        imports = self._extract_imports(tree.root_node, source)
        self._walk(tree.root_node, source, rel_path, symbols, parent=None)

        lang = "tsx" if self._tsx else "typescript"
        return IndexedFile(
            path=rel_path,
            language=lang,
            content_hash=content_hash,
            git_status=GitStatus.UNCHANGED,
            churn_count=0,
            symbols=symbols,
            imports=imports,
            test_framework=detect_test_framework(imports, lang),
        )

    def _extract_imports(self, root: Node, source: bytes) -> list[str]:
        imports: list[str] = []
        for child in root.children:
            if child.type == "import_statement":
                string_node = next(
                    (c for c in child.children if c.type == "string"), None
                )
                if string_node:
                    text = self.node_text(string_node, source).strip("'\"")
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
    ) -> None:
        for child in node.children:
            if child.type in ("class_declaration", "abstract_class_declaration"):
                self._process_class(child, source, file_path, symbols, parent)
            elif child.type == "interface_declaration":
                self._process_interface(child, source, file_path, symbols, parent)
            elif child.type == "function_declaration":
                self._process_function(child, source, file_path, symbols, parent)
            elif child.type == "export_statement":
                # unwrap: export class / export function / export default ...
                self._walk(child, source, file_path, symbols, parent)
            elif child.type in ("method_definition", "abstract_method_signature"):
                self._process_method(child, source, file_path, symbols, parent)
            elif child.type == "public_field_definition":
                self._process_field(child, source, file_path, symbols, parent)
            elif child.type in ("class_body", "interface_body"):
                self._walk(child, source, file_path, symbols, parent)

    def _process_class(
        self,
        node: Node,
        source: bytes,
        file_path: str,
        symbols: list[IndexedSymbol],
        parent: str | None,
    ) -> None:
        name_node = self.first_child_of_type(node, "type_identifier")
        if name_node is None:
            return
        name = self.node_text(name_node, source)
        qualified = f"{parent}.{name}" if parent else name

        sig = self.node_text(node, source).split("{")[0].strip()
        annotations = _collect_decorators(node, source)
        is_test = _is_test(name, file_path)
        is_ep, http_method, route_path = detect_endpoint(annotations)
        tk = classify_test(file_path, annotations) if is_test else None

        symbols.append(
            IndexedSymbol(
                name=name,
                qualified_name=qualified,
                kind=SymbolKind.CLASS,
                parent_name=parent,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                visibility=Visibility.PUBLIC,
                is_test=is_test,
                signature=sig,
                annotations=annotations,
                is_endpoint=is_ep,
                http_method=http_method,
                route_path=route_path,
                test_kind=tk,
            )
        )

        body = self.first_child_of_type(node, "class_body")
        if body:
            self._walk(body, source, file_path, symbols, parent=qualified)

    def _process_interface(
        self,
        node: Node,
        source: bytes,
        file_path: str,
        symbols: list[IndexedSymbol],
        parent: str | None,
    ) -> None:
        name_node = self.first_child_of_type(node, "type_identifier")
        if name_node is None:
            return
        name = self.node_text(name_node, source)
        qualified = f"{parent}.{name}" if parent else name

        sig = self.node_text(node, source).split("{")[0].strip()

        symbols.append(
            IndexedSymbol(
                name=name,
                qualified_name=qualified,
                kind=SymbolKind.INTERFACE,
                parent_name=parent,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                visibility=Visibility.PUBLIC,
                is_test=False,
                signature=sig,
            )
        )

    def _process_function(
        self,
        node: Node,
        source: bytes,
        file_path: str,
        symbols: list[IndexedSymbol],
        parent: str | None,
    ) -> None:
        name_node = self.first_child_of_type(node, "identifier")
        if name_node is None:
            return
        name = self.node_text(name_node, source)
        qualified = f"{parent}.{name}" if parent else name

        body = self.first_child_of_type(node, "statement_block")
        sig_end = body.start_byte if body else node.end_byte
        sig = source[node.start_byte:sig_end].decode("utf-8", errors="replace").strip()
        annotations = _collect_decorators(node, source)
        is_test = _is_test(name, file_path)
        is_ep, http_method, route_path = detect_endpoint(annotations)
        tk = classify_test(file_path, annotations) if is_test else None

        symbols.append(
            IndexedSymbol(
                name=name,
                qualified_name=qualified,
                kind=SymbolKind.FUNCTION,
                parent_name=parent,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                visibility=Visibility.PUBLIC,
                is_test=is_test,
                signature=sig,
                annotations=annotations,
                is_endpoint=is_ep,
                http_method=http_method,
                route_path=route_path,
                test_kind=tk,
            )
        )

    def _process_method(
        self,
        node: Node,
        source: bytes,
        file_path: str,
        symbols: list[IndexedSymbol],
        parent: str | None,
    ) -> None:
        name_node = self.first_child_of_type(node, "property_identifier")
        if name_node is None:
            return
        name = self.node_text(name_node, source)
        qualified = f"{parent}.{name}" if parent else name

        kind = SymbolKind.CONSTRUCTOR if name == "constructor" else SymbolKind.METHOD
        vis = _visibility(node, source)

        body = self.first_child_of_type(node, "statement_block")
        sig_end = body.start_byte if body else node.end_byte
        sig = source[node.start_byte:sig_end].decode("utf-8", errors="replace").strip()
        annotations = _collect_decorators(node, source)
        is_test = _is_test(name, file_path)
        is_ep, http_method, route_path = detect_endpoint(annotations)
        tk = classify_test(file_path, annotations) if is_test else None

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
                is_endpoint=is_ep,
                http_method=http_method,
                route_path=route_path,
                test_kind=tk,
            )
        )

    def _process_field(
        self,
        node: Node,
        source: bytes,
        file_path: str,
        symbols: list[IndexedSymbol],
        parent: str | None,
    ) -> None:
        name_node = self.first_child_of_type(node, "property_identifier")
        if name_node is None:
            return
        name = self.node_text(name_node, source)
        qualified = f"{parent}.{name}" if parent else name

        vis = _visibility(node, source)
        sig = self.node_text(node, source).split("=")[0].strip()

        symbols.append(
            IndexedSymbol(
                name=name,
                qualified_name=qualified,
                kind=SymbolKind.FIELD,
                parent_name=parent,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                visibility=vis,
                is_test=False,
                signature=sig,
            )
        )

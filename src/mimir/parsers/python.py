from pathlib import Path

import tree_sitter_python
from tree_sitter import Language, Node

from mimir.models import (
    GitStatus,
    IndexedFile,
    IndexedSymbol,
    SymbolKind,
    Visibility,
)
from mimir.parsers.base import BaseParser


def _visibility(name: str) -> Visibility:
    if name.startswith("__") and not name.endswith("__"):
        return Visibility.PRIVATE
    if name.startswith("_"):
        return Visibility.PROTECTED
    return Visibility.PUBLIC


def _is_test(name: str, file_path: str, decorators: list[str]) -> bool:
    path = file_path.lower().replace("\\", "/")
    parts = path.split("/")
    in_test_dir = any(p in ("test", "tests") for p in parts[:-1])
    filename = parts[-1]
    return (
        name.startswith("test_")
        or name.startswith("Test")
        or in_test_dir
        or filename.startswith("test_")
        or filename.endswith("_test.py")
        or any(d.startswith("pytest.mark") or d.startswith("unittest") for d in decorators)
    )


class PythonParser(BaseParser):
    language_name = "python"

    def __init__(self) -> None:
        super().__init__(Language(tree_sitter_python.language()))

    def extract(self, path: Path, rel_path: str, content_hash: str) -> IndexedFile | None:
        tree = self.parse_file(path)
        if tree is None:
            return None

        source = path.read_bytes()
        symbols: list[IndexedSymbol] = []
        imports = self._extract_imports(tree.root_node, source)
        self._walk(tree.root_node, source, rel_path, symbols, parent=None)

        return IndexedFile(
            path=rel_path,
            language="python",
            content_hash=content_hash,
            git_status=GitStatus.UNCHANGED,
            churn_count=0,
            symbols=symbols,
            imports=imports,
        )

    def _extract_imports(self, root: Node, source: bytes) -> list[str]:
        imports: list[str] = []
        for child in root.children:
            if child.type == "import_statement":
                for c in child.children:
                    if c.type == "dotted_name":
                        imports.append(self.node_text(c, source))
                    elif c.type == "aliased_import":
                        name = self.first_child_of_type(c, "dotted_name")
                        if name:
                            imports.append(self.node_text(name, source))
            elif child.type == "import_from_statement":
                module = self.first_child_of_type(child, "dotted_name", "relative_import")
                if module:
                    imports.append(self.node_text(module, source))
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
            if child.type == "class_definition":
                self._process_class(child, source, file_path, symbols, parent)
            elif child.type in ("function_definition", "async_function_definition"):
                self._process_function(child, source, file_path, symbols, parent, decorators=[])
            elif child.type == "decorated_definition":
                self._process_decorated(child, source, file_path, symbols, parent)

    def _process_decorated(
        self,
        node: Node,
        source: bytes,
        file_path: str,
        symbols: list[IndexedSymbol],
        parent: str | None,
    ) -> None:
        decorators = [
            self.node_text(d, source).lstrip("@")
            for d in node.children
            if d.type == "decorator"
        ]
        for child in node.children:
            if child.type == "class_definition":
                self._process_class(child, source, file_path, symbols, parent, decorators=decorators)
            elif child.type in ("function_definition", "async_function_definition"):
                self._process_function(child, source, file_path, symbols, parent, decorators=decorators)

    def _process_class(
        self,
        node: Node,
        source: bytes,
        file_path: str,
        symbols: list[IndexedSymbol],
        parent: str | None,
        decorators: list[str] | None = None,
    ) -> None:
        name_node = self.first_child_of_type(node, "identifier")
        if name_node is None:
            return
        name = self.node_text(name_node, source)
        qualified = f"{parent}.{name}" if parent else name

        sig = self.node_text(node, source).split(":")[0].strip() + ":"
        is_test = _is_test(name, file_path, decorators or [])

        symbols.append(
            IndexedSymbol(
                name=name,
                qualified_name=qualified,
                kind=SymbolKind.CLASS,
                parent_name=parent,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                visibility=_visibility(name),
                is_test=is_test,
                signature=sig,
                annotations=decorators or [],
            )
        )

        body = self.first_child_of_type(node, "block")
        if body:
            self._walk(body, source, file_path, symbols, parent=qualified)

    def _process_function(
        self,
        node: Node,
        source: bytes,
        file_path: str,
        symbols: list[IndexedSymbol],
        parent: str | None,
        decorators: list[str],
    ) -> None:
        name_node = self.first_child_of_type(node, "identifier")
        if name_node is None:
            return
        name = self.node_text(name_node, source)
        qualified = f"{parent}.{name}" if parent else name

        kind = SymbolKind.METHOD if parent else SymbolKind.FUNCTION
        if name == "__init__":
            kind = SymbolKind.CONSTRUCTOR

        body = self.first_child_of_type(node, "block")
        sig_end = body.start_byte if body else node.end_byte
        sig = source[node.start_byte:sig_end].decode("utf-8", errors="replace").rstrip().rstrip(":")

        symbols.append(
            IndexedSymbol(
                name=name,
                qualified_name=qualified,
                kind=kind,
                parent_name=parent,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                visibility=_visibility(name),
                is_test=_is_test(name, file_path, decorators),
                signature=sig,
                annotations=decorators,
            )
        )

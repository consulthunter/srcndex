import threading
from collections.abc import Generator
from pathlib import Path

import tree_sitter
from tree_sitter import Language, Node, Parser

from mimir.models import IndexedFile


class BaseParser:
    language_name: str = ""

    def __init__(self, language: Language) -> None:
        self._parser = Parser(language)
        self._lock = threading.Lock()

    def parse_file(self, path: Path) -> tree_sitter.Tree | None:
        try:
            source = path.read_bytes()
            with self._lock:
                return self._parser.parse(source)
        except OSError:
            return None

    def extract(self, path: Path, rel_path: str, content_hash: str) -> IndexedFile | None:
        raise NotImplementedError

    # --- AST helpers ---

    @staticmethod
    def node_text(node: Node, source: bytes) -> str:
        return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")

    @staticmethod
    def children_of_type(node: Node, *kinds: str) -> list[Node]:
        return [c for c in node.children if c.type in kinds]

    @staticmethod
    def first_child_of_type(node: Node, *kinds: str) -> Node | None:
        for c in node.children:
            if c.type in kinds:
                return c
        return None

    @staticmethod
    def traverse(node: Node) -> Generator[Node]:
        yield node
        for child in node.children:
            yield from BaseParser.traverse(child)

    @staticmethod
    def nodes_of_type(root: Node, kind: str) -> Generator[Node]:
        for node in BaseParser.traverse(root):
            if node.type == kind:
                yield node


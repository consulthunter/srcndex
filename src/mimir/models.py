from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class SymbolKind(StrEnum):
    CLASS = "class"
    INTERFACE = "interface"
    ENUM = "enum"
    METHOD = "method"
    CONSTRUCTOR = "constructor"
    FUNCTION = "function"
    PROPERTY = "property"
    FIELD = "field"


class Visibility(StrEnum):
    PUBLIC = "public"
    PRIVATE = "private"
    PROTECTED = "protected"
    INTERNAL = "internal"
    UNKNOWN = "unknown"


class GitStatus(StrEnum):
    NEW = "new"
    MODIFIED = "modified"
    UNCHANGED = "unchanged"
    DELETED = "deleted"


class ProjectKind(StrEnum):
    MAVEN = "maven"
    GRADLE = "gradle"
    CSPROJ = "csproj"
    PYTHON_PACKAGE = "python_package"
    UNKNOWN = "unknown"


class IndexedSymbol(BaseModel):
    name: str
    qualified_name: str
    kind: SymbolKind
    parent_name: str | None = None
    start_line: int
    end_line: int
    visibility: Visibility
    is_test: bool
    signature: str
    annotations: list[str] = Field(default_factory=list)


class IndexedFile(BaseModel):
    path: str
    language: str
    content_hash: str
    git_status: GitStatus
    churn_count: int
    symbols: list[IndexedSymbol]
    imports: list[str] = Field(default_factory=list)


class IndexedProject(BaseModel):
    path: str
    name: str
    kind: ProjectKind
    build_file: str
    files: list[IndexedFile]


class ScanResult(BaseModel):
    repo_path: str
    head_commit: str
    projects: list[IndexedProject]
    scanned_at: datetime
    files_scanned: int
    files_skipped: int

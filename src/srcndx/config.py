from __future__ import annotations

import tomllib
from pathlib import Path

from pydantic import BaseModel, Field

_CONFIG_FILE = ".srcndx.toml"


class SrcndxConfig(BaseModel):
    debounce_seconds: float = 15.0
    watch_tracked_files: bool = True
    exclude_dirs: list[str] = Field(
        default_factory=lambda: [
            ".git",
            "__pycache__",
            ".venv",
            "venv",
            "env",
            "node_modules",
            ".mypy_cache",
            ".ruff_cache",
            ".pytest_cache",
            "dist",
            "build",
            "target",
        ]
    )
    # Extends exclude_dirs without replacing the defaults.
    # Use this in .srcndx.toml to add exclusions while keeping built-in defaults.
    additional_exclude_dirs: list[str] = Field(default_factory=list)
    exclude_extensions: list[str] = Field(default_factory=list)
    exclude_files: list[str] = Field(default_factory=list)
    extra_tracked_extensions: dict[str, str] = Field(default_factory=dict)
    extra_tracked_names: dict[str, str] = Field(default_factory=dict)
    max_file_size_kb: int = 500
    persist_cache: bool = False
    cache_file: str = ".srcndx-cache.json"
    log_file: str | None = None
    log_level: str = "INFO"

    @property
    def effective_exclude_dirs(self) -> frozenset[str]:
        return frozenset(self.exclude_dirs) | frozenset(self.additional_exclude_dirs)


def load_config(repo_path: str | Path) -> SrcndxConfig:
    path = Path(repo_path) / _CONFIG_FILE
    if not path.exists():
        return SrcndxConfig()
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return SrcndxConfig(**data)

from pathlib import Path

from mimir.config import MimirConfig, load_config


def test_default_config_values() -> None:
    cfg = MimirConfig()
    assert cfg.debounce_seconds == 15.0
    assert cfg.watch_tracked_files is True
    assert ".git" in cfg.exclude_dirs
    assert "__pycache__" in cfg.exclude_dirs
    assert cfg.exclude_extensions == []
    assert cfg.exclude_files == []
    assert cfg.extra_tracked_extensions == {}
    assert cfg.extra_tracked_names == {}


def test_load_config_missing_file(tmp_path: Path) -> None:
    cfg = load_config(tmp_path)
    assert isinstance(cfg, MimirConfig)
    assert cfg.debounce_seconds == 15.0


def test_load_config_from_toml(tmp_path: Path) -> None:
    (tmp_path / ".mimir.toml").write_text(
        'debounce_seconds = 5.0\n'
        'watch_tracked_files = false\n'
        'exclude_dirs = ["node_modules", ".git"]\n'
        'exclude_extensions = [".lock"]\n'
        'exclude_files = ["package-lock.json"]\n'
    )
    cfg = load_config(tmp_path)
    assert cfg.debounce_seconds == 5.0
    assert cfg.watch_tracked_files is False
    assert "node_modules" in cfg.exclude_dirs
    assert ".lock" in cfg.exclude_extensions
    assert "package-lock.json" in cfg.exclude_files


def test_load_config_extra_tracked_extensions(tmp_path: Path) -> None:
    (tmp_path / ".mimir.toml").write_text(
        '[extra_tracked_extensions]\n'
        '".proto" = "protobuf"\n'
        '".avro" = "avro"\n'
    )
    cfg = load_config(tmp_path)
    assert cfg.extra_tracked_extensions[".proto"] == "protobuf"
    assert cfg.extra_tracked_extensions[".avro"] == "avro"


def test_load_config_extra_tracked_names(tmp_path: Path) -> None:
    (tmp_path / ".mimir.toml").write_text(
        '[extra_tracked_names]\n'
        '"Jenkinsfile" = "groovy"\n'
    )
    cfg = load_config(tmp_path)
    assert cfg.extra_tracked_names["Jenkinsfile"] == "groovy"


def test_default_excludes_are_independent_instances() -> None:
    a = MimirConfig()
    b = MimirConfig()
    a.exclude_dirs.append("custom")
    assert "custom" not in b.exclude_dirs


def test_additional_exclude_dirs_merges_with_defaults() -> None:
    cfg = MimirConfig(additional_exclude_dirs=["vendor", "fixtures"])
    effective = cfg.effective_exclude_dirs
    assert "vendor" in effective
    assert "fixtures" in effective
    assert ".git" in effective
    assert "__pycache__" in effective


def test_effective_exclude_dirs_is_union() -> None:
    cfg = MimirConfig(
        exclude_dirs=["custom"],
        additional_exclude_dirs=["extra"],
    )
    effective = cfg.effective_exclude_dirs
    assert "custom" in effective
    assert "extra" in effective
    assert ".git" not in effective  # replaced by custom exclude_dirs


def test_load_config_additional_exclude_dirs(tmp_path: Path) -> None:
    (tmp_path / ".mimir.toml").write_text(
        'additional_exclude_dirs = ["vendor", "fixtures"]\n'
    )
    cfg = load_config(tmp_path)
    assert "vendor" in cfg.additional_exclude_dirs
    assert ".git" in cfg.exclude_dirs  # defaults preserved


def test_default_max_file_size_kb() -> None:
    cfg = MimirConfig()
    assert cfg.max_file_size_kb == 500


def test_default_persist_cache() -> None:
    cfg = MimirConfig()
    assert cfg.persist_cache is False
    assert cfg.cache_file == ".mimir-cache.json"


def test_load_config_persist_cache_and_limits(tmp_path: Path) -> None:
    (tmp_path / ".mimir.toml").write_text(
        "persist_cache = true\n"
        'cache_file = "custom-cache.json"\n'
        "max_file_size_kb = 250\n"
    )
    cfg = load_config(tmp_path)
    assert cfg.persist_cache is True
    assert cfg.cache_file == "custom-cache.json"
    assert cfg.max_file_size_kb == 250

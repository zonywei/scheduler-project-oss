# config_loader.py
import warnings
from pathlib import Path


def _warn_deprecated(name: str) -> None:
    warnings.warn(
        f"scheduler.config_loader.{name} is deprecated; use scheduler.config.loader instead.",
        DeprecationWarning,
        stacklevel=3,
    )


def load_yaml(path: str | Path) -> dict:
    _warn_deprecated("load_yaml")
    from scheduler.config.loader import load_yaml_config

    return load_yaml_config(path)


def merge_section(
    io_cfg: dict | None,
    rules_cfg: dict | None,
    section: str,
) -> dict:
    """Merge a top-level section with rules.yaml taking precedence."""
    _warn_deprecated("merge_section")
    from scheduler.config.loader import merge_section as official_merge_section

    return official_merge_section(io_cfg or {}, rules_cfg or {}, section)


def load_configs(
    project_root: str | Path | None = None,
    rules_path: str | Path | None = None,
    io_path: str | Path | None = None,
):
    _warn_deprecated("load_configs")
    from scheduler.config.loader import load_yaml_config

    if project_root:
        root = Path(project_root)
        rules = load_yaml_config(root / "config" / "rules.yaml")
        io_cfg = load_yaml_config(root / "config" / "io.yaml")
        return rules, io_cfg

    if io_path is None and rules_path is None:
        raise ValueError("load_configs 需要 project_root 或 rules_path/io_path 之一。")

    if io_path is None:
        io_path = Path(rules_path).with_name("io.yaml")
    if rules_path is None:
        rules_path = Path(io_path).with_name("rules.yaml")

    rules = load_yaml_config(rules_path)
    io_cfg = load_yaml_config(io_path)
    return rules, io_cfg

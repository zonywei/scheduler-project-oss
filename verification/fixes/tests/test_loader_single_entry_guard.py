import inspect
import sys
import warnings
from pathlib import Path

from ortools.sat.python import cp_model

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import scheduler.day_schedule_entry as day_entry  # noqa: E402
import scheduler.joint_solver as joint_entry  # noqa: E402
import scheduler.main as night_entry  # noqa: E402
import scheduler.config.loader as loader_mod  # noqa: E402
import scheduler.config_loader as legacy_loader  # noqa: E402
from scheduler.config.loader import load_effective_config, runtime_solver_overrides  # noqa: E402
from scheduler.solver_params import apply_joint_solver_parameters, apply_night_solver_parameters  # noqa: E402


def _assert_entry_loader_link() -> None:
    entry_specs = [
        (day_entry, "run_day"),
        (night_entry, "run_night"),
        (joint_entry, "run_joint"),
    ]
    for module, func_name in entry_specs:
        fn = getattr(module, func_name, None)
        assert callable(fn), f"missing entry function: {module.__name__}.{func_name}"
        src = inspect.getsource(fn)
        assert "load_effective_config" in src, f"{module.__name__}.{func_name} does not call load_effective_config"


def _assert_official_loader_is_not_backed_by_legacy_module() -> None:
    src = inspect.getsource(loader_mod)
    assert "scheduler.config_loader" not in src, "official loader must not import the legacy compatibility module"
    assert "def load_yaml_config" in src, "official loader should own YAML loading"
    assert "def _merge_section_values" in src, "official loader should own section merge semantics"

    io_path = REPO_ROOT / "scheduler" / "config" / "io.yaml"
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", DeprecationWarning)
        payload = legacy_loader.load_yaml(io_path)
    assert isinstance(payload, dict)
    assert any("scheduler.config_loader.load_yaml is deprecated" in str(item.message) for item in caught)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", DeprecationWarning)
        merged = legacy_loader.merge_section({"solve": {"a": 1}}, {"solve": {"b": 2}}, "solve")
    assert merged == {"a": 1, "b": 2}
    assert any("scheduler.config_loader.merge_section is deprecated" in str(item.message) for item in caught)


def _assert_runtime_seed_reaches_solver_parameter_setter() -> None:
    io_path = REPO_ROOT / "scheduler" / "config" / "io.yaml"
    rules_path = REPO_ROOT / "scheduler" / "config" / "rules.yaml"
    paths = {"io_path": io_path, "rules_path": rules_path}

    base_joint = load_effective_config("joint", paths)
    base_io_seed = ((base_joint.io_cfg.get("joint_solve", {}) or {}).get("random_seed"))
    base_rules_seed = ((base_joint.rules_cfg.get("solve", {}) or {}).get("random_seed"))

    test_seed = 24680
    if base_io_seed == test_seed and base_rules_seed == test_seed:
        test_seed = 24681

    with runtime_solver_overrides(seed=test_seed):
        day_effective = load_effective_config("day", paths)
        night_effective = load_effective_config("night", paths)
        joint_effective = load_effective_config("joint", paths)

        assert ((day_effective.io_cfg.get("joint_solve", {}) or {}).get("random_seed")) == test_seed
        assert ((night_effective.rules_cfg.get("solve", {}) or {}).get("random_seed")) == test_seed
        assert ((joint_effective.io_cfg.get("joint_solve", {}) or {}).get("random_seed")) == test_seed

        day_solver = cp_model.CpSolver()
        apply_joint_solver_parameters(
            day_solver,
            day_effective.io_cfg.get("joint_solve", {}) or {},
            default_time_limit_seconds=600,
        )
        assert int(day_solver.parameters.random_seed) == test_seed

        night_solver = cp_model.CpSolver()
        apply_night_solver_parameters(
            night_solver,
            night_effective.rules_cfg.get("solve", {}) or {},
            default_time_limit_seconds=3000,
        )
        assert int(night_solver.parameters.random_seed) == test_seed

        joint_solver = cp_model.CpSolver()
        apply_joint_solver_parameters(
            joint_solver,
            joint_effective.io_cfg.get("joint_solve", {}) or {},
            default_time_limit_seconds=300,
        )
        assert int(joint_solver.parameters.random_seed) == test_seed

    restored_joint = load_effective_config("joint", paths)
    restored_io_seed = ((restored_joint.io_cfg.get("joint_solve", {}) or {}).get("random_seed"))
    restored_rules_seed = ((restored_joint.rules_cfg.get("solve", {}) or {}).get("random_seed"))
    assert restored_io_seed == base_io_seed
    assert restored_rules_seed == base_rules_seed


def main() -> None:
    _assert_entry_loader_link()
    _assert_official_loader_is_not_backed_by_legacy_module()
    _assert_runtime_seed_reaches_solver_parameter_setter()
    print("test_loader_single_entry_guard: PASS")

if __name__ == "__main__":
    raise SystemExit(main())

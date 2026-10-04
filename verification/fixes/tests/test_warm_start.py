from __future__ import annotations

import json
from pathlib import Path

from scheduler.warm_start import (
    WarmStartConfig,
    compute_rules_data_hash,
    save_best_solution_json,
    save_solution_json,
    select_solution_file,
)


def _meta(objective: float, *, rules_hash: str = "rules", data_hash: str = "data") -> dict:
    return {
        "timestamp": f"ts_{objective:g}",
        "status": "FEASIBLE",
        "objective": objective,
        "rules_hash": rules_hash,
        "data_hash": data_hash,
    }


def test_compute_rules_data_hash_includes_objective_implementation_signature(tmp_path: Path) -> None:
    io_path = tmp_path / "io.yaml"
    rules_path = tmp_path / "rules.yaml"
    day_rules_path = tmp_path / "day_rules.xlsx"
    teacher_table_path = tmp_path / "teachers.xlsx"
    implementation_path = tmp_path / "objective_impl.py"
    for path in (io_path, rules_path, day_rules_path, teacher_table_path):
        path.write_text(path.name, encoding="utf-8")
    implementation_path.write_text("objective = 'v1'", encoding="utf-8")

    rules_hash_v1, data_hash_v1 = compute_rules_data_hash(
        io_path,
        rules_path,
        day_rules_path,
        teacher_table_path,
        implementation_paths=(implementation_path,),
    )
    implementation_path.write_text("objective = 'v2'", encoding="utf-8")

    rules_hash_v2, data_hash_v2 = compute_rules_data_hash(
        io_path,
        rules_path,
        day_rules_path,
        teacher_table_path,
        implementation_paths=(implementation_path,),
    )

    assert rules_hash_v1 != rules_hash_v2
    assert data_hash_v1 == data_hash_v2


def test_select_solution_file_prefers_best_same_config_over_worse_last(tmp_path: Path) -> None:
    last = tmp_path / "last_solution.json"
    best = tmp_path / "best_warm_start_solution.json"
    pool = tmp_path / "pool"
    pool.mkdir()

    save_solution_json(last, _meta(206290), [["1班", "数学", "星期一", "AM", "1"]], [])
    save_solution_json(best, _meta(199520), [["1班", "数学", "星期一", "AM", "2"]], [])
    save_solution_json(pool / "solution_old.json", _meta(201690), [["1班", "数学", "星期一", "AM", "3"]], [])

    selected = select_solution_file(
        WarmStartConfig(path=last, best_path=best, pool_dir=pool),
        rules_hash="rules",
        data_hash="data",
    )

    assert selected == best


def test_select_solution_file_prefers_same_rules_over_lower_objective_when_rules_hash_drifts(tmp_path: Path) -> None:
    best = tmp_path / "best_warm_start_solution.json"
    pool = tmp_path / "pool"
    pool.mkdir()

    save_solution_json(
        best,
        _meta(193050, rules_hash="rules-before", data_hash="same-data"),
        [["1班", "数学", "星期一", "AM", "2"]],
        [],
    )
    same_rules_worse = pool / "solution_same_rules_worse.json"
    save_solution_json(
        same_rules_worse,
        _meta(200890, rules_hash="rules-after", data_hash="same-data"),
        [["1班", "数学", "星期一", "AM", "1"]],
        [],
    )

    selected = select_solution_file(
        WarmStartConfig(best_path=best, pool_dir=pool),
        rules_hash="rules-after",
        data_hash="same-data",
    )

    assert selected == same_rules_worse


def test_select_solution_file_keeps_same_data_ahead_of_lower_objective_other_data(tmp_path: Path) -> None:
    best = tmp_path / "best_warm_start_solution.json"
    pool = tmp_path / "pool"
    pool.mkdir()

    same_data = pool / "solution_same_data.json"
    save_solution_json(
        same_data,
        _meta(200890, rules_hash="rules-after", data_hash="same-data"),
        [["1班", "数学", "星期一", "AM", "1"]],
        [],
    )
    save_solution_json(
        best,
        _meta(193050, rules_hash="rules-before", data_hash="other-data"),
        [["2班", "数学", "星期一", "AM", "2"]],
        [],
    )

    selected = select_solution_file(
        WarmStartConfig(best_path=best, pool_dir=pool),
        rules_hash="rules-after",
        data_hash="same-data",
    )

    assert selected == same_data


def test_save_best_solution_json_keeps_lower_objective_for_same_config(tmp_path: Path) -> None:
    best = tmp_path / "best_warm_start_solution.json"
    save_solution_json(best, _meta(199520), [["1班", "数学", "星期一", "AM", "2"]], [])

    result = save_best_solution_json(
        best,
        _meta(206290),
        [["1班", "数学", "星期一", "AM", "1"]],
        [],
    )

    stored = json.loads(best.read_text(encoding="utf-8"))
    assert result["status"] == "kept"
    assert stored["meta"]["objective"] == 199520


def test_save_best_solution_json_updates_when_rules_hash_changes(tmp_path: Path) -> None:
    best = tmp_path / "best_warm_start_solution.json"
    save_solution_json(
        best,
        _meta(193050, rules_hash="rules-before", data_hash="same-data"),
        [["1班", "数学", "星期一", "AM", "2"]],
        [],
    )

    result = save_best_solution_json(
        best,
        _meta(200890, rules_hash="rules-after", data_hash="same-data"),
        [["1班", "数学", "星期一", "AM", "1"]],
        [],
    )

    stored = json.loads(best.read_text(encoding="utf-8"))
    assert result["status"] == "updated"
    assert result["previous_objective"] == 193050
    assert result["same_rules"] is False
    assert stored["meta"]["objective"] == 200890


def test_save_best_solution_json_updates_when_current_is_better(tmp_path: Path) -> None:
    best = tmp_path / "best_warm_start_solution.json"
    save_solution_json(best, _meta(201690), [["1班", "数学", "星期一", "AM", "3"]], [])

    result = save_best_solution_json(
        best,
        _meta(199520),
        [["1班", "数学", "星期一", "AM", "2"]],
        [],
    )

    stored = json.loads(best.read_text(encoding="utf-8"))
    assert result["status"] == "updated"
    assert stored["meta"]["objective"] == 199520

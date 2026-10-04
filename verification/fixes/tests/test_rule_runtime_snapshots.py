from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_orchestrated_optimization import create_existing_cp_model, get_existing_cp_model_operation_trace  # noqa: E402
from scheduler.app import service as service_mod  # noqa: E402
from scheduler.rules import build_default_rule_registry  # noqa: E402
from scheduler.rules.generic_bridge import generic_scheduler_rule_ids  # noqa: E402
from scheduler.rules.registry import RuleRegistry  # noqa: E402
from scheduler.rules.runtime import _make_rule_wrapper, rule_runtime_context, runtime_trace_payload  # noqa: E402
from scheduler.rules.spec import RuleSpec as SchedulerRuleSpec  # noqa: E402


def test_rule_runtime_wrapper_tags_ai_or_model_operations_with_rule_id() -> None:
    registry = RuleRegistry()

    def apply_fake_rule(model):
        x = model.NewBoolVar("x")
        model.Add(x == 1)
        return x

    registry.register(
        SchedulerRuleSpec(
            rule_id="demo.rule",
            name="Demo rule",
            category_path="demo",
            stage="constraints",
            order=1,
            tags=("demo",),
            apply_fn=apply_fake_rule,
        )
    )
    wrapped = _make_rule_wrapper(rule_id="demo.rule", fn_name="apply_fake_rule", fn=apply_fake_rule)
    trace: list[dict] = []
    model = create_existing_cp_model("runtime_rule_trace")

    with rule_runtime_context(mode="demo", run_id="run_demo", effective_cfg={}, registry=registry, trace=trace):
        wrapped(model)

    operation_trace = get_existing_cp_model_operation_trace(model)
    assert [(item.operation, item.rule_id) for item in operation_trace] == [
        ("NewBoolVar", "demo.rule"),
        ("Add", "demo.rule"),
    ]
    assert trace[0]["rule_id"] == "demo.rule"
    assert trace[0]["ai_or_operation_delta"] == 2
    assert trace[0]["ai_or_operations_by_type"] == {"Add": 1, "NewBoolVar": 1}


def _assert_runtime_snapshot_write() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        cfg_dir = root / "scheduler" / "config"
        outputs_dir = root / "outputs"
        run_dir = outputs_dir / "solutions" / "run_20260301_000000"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "best").mkdir(parents=True, exist_ok=True)

        io_path = cfg_dir / "io.yaml"
        rules_path = cfg_dir / "rules.yaml"
        io_path.write_text("io: 1\n", encoding="utf-8")
        rules_path.write_text("rules: 1\n", encoding="utf-8")

        io_cfg = {
            "output": {"dir": "outputs"},
            "teacher_table": {"path": "teachers.xlsx"},
            "joint_solve": {"time_limit_seconds": 30, "workers": 2, "random_seed": 7},
            "day": {"rules_path": "rules.xlsx", "teacher_table_path": "teachers.xlsx"},
            "web_tables": {
                "teacher_subjects": [{"班级": "1班", "班主任": "教师A", "班主任性别": "男", "语文": "教师A"}],
                "day_rules": {
                    "time_grid": [
                        {
                            "时段节次": "上午1",
                            "星期一": 1,
                            "星期二": 0,
                            "星期三": 0,
                            "星期四": 0,
                            "星期五": 0,
                            "星期六": 0,
                            "星期日": 0,
                        }
                    ],
                    "fixed_slots": [],
                    "subject_hours": [{"学科": "语文", "早自习课时": 0, "周中课时": 1, "周末课时": 0}],
                    "subject_bans": [],
                    "class_overrides": [],
                },
            },
        }
        rules_cfg = {"solve": {"time_limit_seconds": 120, "workers": 8, "random_seed": 11}}
        (root / "scheduler" / "teachers.xlsx").write_text("t", encoding="utf-8")

        registry = build_default_rule_registry()
        trace = [
            {
                "timestamp": "2026-03-01 00:00:00",
                "mode": "joint",
                "run_id": "run_20260301_000000",
                "rule_id": "night.hard_base",
                "name": "night.hard_base",
                "stage": "constraints",
                "order": 1,
                "enabled": True,
                "rule_mode": "hard",
                "weight": None,
                "callable": "apply_hard_base",
                "status": "ok",
                "ai_or_operation_delta": 3,
            }
        ]

        service_mod._write_runtime_snapshots(
            mode="joint",
            run_id="run_20260301_000000",
            outputs_dir=outputs_dir,
            run_dir=run_dir,
            effective_cfg={**io_cfg, **rules_cfg},
            io_cfg=io_cfg,
            rules_cfg=rules_cfg,
            io_path=io_path,
            rules_path=rules_path,
            registry=registry,
            trace=trace,
        )

        out_meta = outputs_dir / "meta"
        run_meta = run_dir / "_run_meta"
        for folder in (out_meta, run_meta):
            for name in (
                "effective_rules_snapshot.json",
                "solver_params_snapshot.json",
                "inputs_fingerprint.json",
                "school_problem_snapshot.json",
                "applied_rules_trace.json",
                "rule_execution_plan.json",
            ):
                path = folder / name
                assert path.exists(), f"missing snapshot: {path}"
                payload = json.loads(path.read_text(encoding="utf-8"))
                assert payload.get("timestamp"), f"timestamp missing: {path}"
                assert payload.get("run_id") == "run_20260301_000000"

        trace_payload = json.loads((out_meta / "applied_rules_trace.json").read_text(encoding="utf-8"))
        assert isinstance(trace_payload.get("trace"), list)
        assert trace_payload["trace"][0]["rule_id"] == "night.hard_base"
        assert trace_payload["ai_or_operation_summary"] == {
            "total_operation_delta": 3,
            "rules": {"night.hard_base": {"operation_delta": 3, "call_count": 1, "operations": {}}},
        }
        assert trace_payload["ai_or_migration_backlog"][0]["rule_id"] == "night.hard_base"
        assert trace_payload["ai_or_migration_backlog"][0]["operation_count"] == 3
        assert trace_payload["ai_or_migration_backlog"][0]["generic_contract_status"] == "covered_by_generic_contract"
        problem_payload = json.loads((out_meta / "school_problem_snapshot.json").read_text(encoding="utf-8"))
        assert problem_payload["source"] == "runtime_snapshot"
        assert problem_payload["solver_effect"] == "none"
        assert problem_payload["validation"]["ok"] is True
        assert problem_payload["summary"]["profile_id"] == "current_school"
        assert problem_payload["summary"]["classes"] == 1
        assert problem_payload["summary"]["class_subject_teacher_rows"] == 1
        plan_payload = json.loads((out_meta / "rule_execution_plan.json").read_text(encoding="utf-8"))
        assert plan_payload["source"] == "runtime_snapshot"
        assert plan_payload["trace_audit"]["ok"] is True
        assert "night.hard_base" in plan_payload["trace_audit"]["traced_rule_ids"]
        assert any(item["rule_id"] == "night.hard_base" for item in plan_payload["items"])
        assert (run_meta / "rule_execution_plan.json").exists()


def test_runtime_trace_payload_marks_generic_covered_rules_in_migration_backlog() -> None:
    payload = runtime_trace_payload(
        mode="audit",
        run_id="run_audit",
        git_commit=None,
        generic_rule_ids=("ready.rule",),
        trace=[
            {"rule_id": "legacy.rule", "ai_or_operation_delta": 5},
            {"rule_id": "ready.rule", "ai_or_operation_delta": 2, "ai_or_operations_by_type": {"Add": 1, "NewBoolVar": 1}},
            {"rule_id": "ready.rule", "ai_or_operation_delta": 1, "ai_or_operations_by_type": {"Add": 1}},
        ],
    )

    assert [item["rule_id"] for item in payload["ai_or_migration_backlog"]] == [
        "legacy.rule",
        "ready.rule",
    ]
    assert payload["ai_or_migration_backlog"][0]["generic_contract_status"] == "missing_generic_contract"
    assert payload["ai_or_migration_backlog"][0]["operation_types"] == ()
    assert payload["ai_or_migration_backlog"][1]["generic_contract_status"] == "covered_by_generic_contract"
    assert payload["ai_or_migration_backlog"][1]["operation_count"] == 3
    assert payload["ai_or_migration_backlog"][1]["operation_types"] == ("Add", "NewBoolVar")
    assert payload["ai_or_migration_backlog"][1]["candidate_generic_specs"] == (
        "LinearConstraintSpec",
        "VariableSpec.bool",
    )
    assert [item["rule_id"] for item in payload["ai_or_agent_migration_plan"]] == [
        "legacy.rule",
        "ready.rule",
    ]
    assert payload["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "chief_architect"
    assert payload["ai_or_agent_migration_plan"][1]["owner_agent_role"] == "code_execution"


def test_runtime_trace_payload_marks_real_generic_scheduler_rules_as_covered() -> None:
    payload = runtime_trace_payload(
        mode="joint",
        run_id="run_demo",
        git_commit=None,
        trace=[
            {
                "rule_id": "joint.night.hard_base",
                "ai_or_operation_delta": 3,
                "ai_or_operations_by_type": {"Add": 3},
            }
        ],
        generic_rule_ids=generic_scheduler_rule_ids(),
    )

    assert payload["ai_or_migration_backlog"][0]["rule_id"] == "joint.night.hard_base"
    assert payload["ai_or_migration_backlog"][0]["generic_contract_status"] == "covered_by_generic_contract"
    assert payload["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"


def test_runtime_trace_payload_marks_day_generic_scheduler_rule_as_covered() -> None:
    payload = runtime_trace_payload(
        mode="joint",
        run_id="run_demo",
        git_commit=None,
        trace=[
            {
                "rule_id": "joint.day.one_subject_per_slot",
                "ai_or_operation_delta": 6,
                "ai_or_operations_by_type": {"Add": 2, "NewBoolVar": 4},
            }
        ],
        generic_rule_ids=generic_scheduler_rule_ids(),
    )

    assert payload["ai_or_migration_backlog"][0]["rule_id"] == "joint.day.one_subject_per_slot"
    assert payload["ai_or_migration_backlog"][0]["generic_contract_status"] == "covered_by_generic_contract"
    assert payload["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"


def test_runtime_trace_payload_marks_day_subject_hours_rule_as_covered() -> None:
    payload = runtime_trace_payload(
        mode="joint",
        run_id="run_demo",
        git_commit=None,
        trace=[
            {
                "rule_id": "joint.day.subject_hour_constraints",
                "ai_or_operation_delta": 6,
                "ai_or_operations_by_type": {"Add": 6},
            }
        ],
        generic_rule_ids=generic_scheduler_rule_ids(),
    )

    assert payload["ai_or_migration_backlog"][0]["rule_id"] == "joint.day.subject_hour_constraints"
    assert payload["ai_or_migration_backlog"][0]["generic_contract_status"] == "covered_by_generic_contract"
    assert payload["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"


def test_runtime_trace_payload_marks_day_teacher_no_conflict_rule_as_covered() -> None:
    payload = runtime_trace_payload(
        mode="joint",
        run_id="run_demo",
        git_commit=None,
        trace=[
            {
                "rule_id": "joint.day.teacher_no_conflict",
                "ai_or_operation_delta": 2,
                "ai_or_operations_by_type": {"Add": 2},
            }
        ],
        generic_rule_ids=generic_scheduler_rule_ids(),
    )

    assert payload["ai_or_migration_backlog"][0]["rule_id"] == "joint.day.teacher_no_conflict"
    assert payload["ai_or_migration_backlog"][0]["generic_contract_status"] == "covered_by_generic_contract"
    assert payload["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"


def test_runtime_trace_payload_marks_day_morning_reading_rule_as_covered() -> None:
    payload = runtime_trace_payload(
        mode="joint",
        run_id="run_demo",
        git_commit=None,
        trace=[
            {
                "rule_id": "joint.day.morning_reading_constraints",
                "ai_or_operation_delta": 6,
                "ai_or_operations_by_type": {"Add": 6},
            }
        ],
        generic_rule_ids=generic_scheduler_rule_ids(),
    )

    assert payload["ai_or_migration_backlog"][0]["rule_id"] == "joint.day.morning_reading_constraints"
    assert payload["ai_or_migration_backlog"][0]["generic_contract_status"] == "covered_by_generic_contract"
    assert payload["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"


def test_runtime_trace_payload_marks_day_weekend_subject_whitelist_rule_as_covered() -> None:
    payload = runtime_trace_payload(
        mode="joint",
        run_id="run_demo",
        git_commit=None,
        trace=[
            {
                "rule_id": "joint.day.weekend_subject_whitelist",
                "ai_or_operation_delta": 3,
                "ai_or_operations_by_type": {"Add": 3},
            }
        ],
        generic_rule_ids=generic_scheduler_rule_ids(),
    )

    assert payload["ai_or_migration_backlog"][0]["rule_id"] == "joint.day.weekend_subject_whitelist"
    assert payload["ai_or_migration_backlog"][0]["generic_contract_status"] == "covered_by_generic_contract"
    assert payload["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"


def test_runtime_trace_payload_marks_day_no_am1_am4_rule_as_covered() -> None:
    payload = runtime_trace_payload(
        mode="joint",
        run_id="run_demo",
        git_commit=None,
        trace=[
            {
                "rule_id": "joint.day.no_am1_am4",
                "ai_or_operation_delta": 1,
                "ai_or_operations_by_type": {"Add": 1},
            }
        ],
        generic_rule_ids=generic_scheduler_rule_ids(),
    )

    assert payload["ai_or_migration_backlog"][0]["rule_id"] == "joint.day.no_am1_am4"
    assert payload["ai_or_migration_backlog"][0]["generic_contract_status"] == "covered_by_generic_contract"
    assert payload["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"


def test_runtime_trace_payload_marks_day_no_consecutive_same_teacher_same_class_rule_as_covered() -> None:
    payload = runtime_trace_payload(
        mode="joint",
        run_id="run_demo",
        git_commit=None,
        trace=[
            {
                "rule_id": "joint.day.no_consecutive_same_teacher_same_class",
                "ai_or_operation_delta": 2,
                "ai_or_operations_by_type": {"Add": 2},
            }
        ],
        generic_rule_ids=generic_scheduler_rule_ids(),
    )

    assert payload["ai_or_migration_backlog"][0]["rule_id"] == "joint.day.no_consecutive_same_teacher_same_class"
    assert payload["ai_or_migration_backlog"][0]["generic_contract_status"] == "covered_by_generic_contract"
    assert payload["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"


def test_runtime_trace_payload_marks_day_weekend_one_day_only_rule_as_covered() -> None:
    payload = runtime_trace_payload(
        mode="joint",
        run_id="run_demo",
        git_commit=None,
        trace=[
            {
                "rule_id": "joint.day.weekend_one_day_only",
                "ai_or_operation_delta": 28,
                "ai_or_operations_by_type": {"Add": 18, "NewBoolVar": 10},
            }
        ],
        generic_rule_ids=generic_scheduler_rule_ids(),
    )

    assert payload["ai_or_migration_backlog"][0]["rule_id"] == "joint.day.weekend_one_day_only"
    assert payload["ai_or_migration_backlog"][0]["generic_contract_status"] == "covered_by_generic_contract"
    assert payload["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"


def test_runtime_trace_payload_marks_day_weekend_halfday_rule_as_covered() -> None:
    payload = runtime_trace_payload(
        mode="joint",
        run_id="run_demo",
        git_commit=None,
        trace=[
            {
                "rule_id": "joint.day.weekend_halfday_constraint",
                "ai_or_operation_delta": 32,
                "ai_or_operations_by_type": {"Add": 20, "NewBoolVar": 12},
            }
        ],
        generic_rule_ids=generic_scheduler_rule_ids(),
    )

    assert payload["ai_or_migration_backlog"][0]["rule_id"] == "joint.day.weekend_halfday_constraint"
    assert payload["ai_or_migration_backlog"][0]["generic_contract_status"] == "covered_by_generic_contract"
    assert payload["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"


def test_runtime_trace_payload_marks_night_hard_bans_rule_as_covered() -> None:
    payload = runtime_trace_payload(
        mode="joint",
        run_id="run_demo",
        git_commit=None,
        trace=[
            {
                "rule_id": "joint.night.hard_bans",
                "ai_or_operation_delta": 10,
                "ai_or_operations_by_type": {"Add": 10},
            }
        ],
        generic_rule_ids=generic_scheduler_rule_ids(),
    )

    assert payload["ai_or_migration_backlog"][0]["rule_id"] == "joint.night.hard_bans"
    assert payload["ai_or_migration_backlog"][0]["generic_contract_status"] == "covered_by_generic_contract"
    assert payload["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"


def test_runtime_trace_payload_marks_night_hard_teacher_limits_rule_as_covered() -> None:
    payload = runtime_trace_payload(
        mode="joint",
        run_id="run_demo",
        git_commit=None,
        trace=[
            {
                "rule_id": "joint.night.hard_teacher_limits",
                "ai_or_operation_delta": 8,
                "ai_or_operations_by_type": {"Add": 8},
            }
        ],
        generic_rule_ids=generic_scheduler_rule_ids(),
    )

    assert payload["ai_or_migration_backlog"][0]["rule_id"] == "joint.night.hard_teacher_limits"
    assert payload["ai_or_migration_backlog"][0]["generic_contract_status"] == "covered_by_generic_contract"
    assert payload["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"


def test_runtime_trace_payload_marks_night_binding_rule_as_covered() -> None:
    payload = runtime_trace_payload(
        mode="joint",
        run_id="run_demo",
        git_commit=None,
        trace=[
            {
                "rule_id": "joint.night.binding_8chem_9bio",
                "ai_or_operation_delta": 4,
                "ai_or_operations_by_type": {"Add": 4},
            }
        ],
        generic_rule_ids=generic_scheduler_rule_ids(),
    )

    assert payload["ai_or_migration_backlog"][0]["rule_id"] == "joint.night.binding_8chem_9bio"
    assert payload["ai_or_migration_backlog"][0]["generic_contract_status"] == "covered_by_generic_contract"
    assert payload["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"


def test_runtime_trace_payload_marks_night_physics_math_special_rule_as_covered() -> None:
    payload = runtime_trace_payload(
        mode="joint",
        run_id="run_demo",
        git_commit=None,
        trace=[
            {
                "rule_id": "joint.night.physics_math_special",
                "ai_or_operation_delta": 14,
                "ai_or_operations_by_type": {"Add": 14},
            }
        ],
        generic_rule_ids=generic_scheduler_rule_ids(),
    )

    assert payload["ai_or_migration_backlog"][0]["rule_id"] == "joint.night.physics_math_special"
    assert payload["ai_or_migration_backlog"][0]["generic_contract_status"] == "covered_by_generic_contract"
    assert payload["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"


def test_runtime_trace_payload_marks_night_fri_sun_mutex_rule_as_covered() -> None:
    payload = runtime_trace_payload(
        mode="joint",
        run_id="run_demo",
        git_commit=None,
        trace=[
            {
                "rule_id": "joint.night.fri_sun_mutex",
                "ai_or_operation_delta": 4,
                "ai_or_operations_by_type": {"Add": 4},
            }
        ],
        generic_rule_ids=generic_scheduler_rule_ids(),
    )

    assert payload["ai_or_migration_backlog"][0]["rule_id"] == "joint.night.fri_sun_mutex"
    assert payload["ai_or_migration_backlog"][0]["generic_contract_status"] == "covered_by_generic_contract"
    assert payload["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"


def test_runtime_trace_payload_marks_night_single_class_p1_p2_split_rule_as_covered() -> None:
    payload = runtime_trace_payload(
        mode="joint",
        run_id="run_demo",
        git_commit=None,
        trace=[
            {
                "rule_id": "joint.night.single_class_p1_p2_split",
                "ai_or_operation_delta": 6,
                "ai_or_operations_by_type": {"Add": 6},
            }
        ],
        generic_rule_ids=generic_scheduler_rule_ids(),
    )

    assert payload["ai_or_migration_backlog"][0]["rule_id"] == "joint.night.single_class_p1_p2_split"
    assert payload["ai_or_migration_backlog"][0]["generic_contract_status"] == "covered_by_generic_contract"
    assert payload["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"


def test_runtime_trace_payload_marks_night_double_class_weekday_p1_p2_split_rule_as_covered() -> None:
    payload = runtime_trace_payload(
        mode="joint",
        run_id="run_demo",
        git_commit=None,
        trace=[
            {
                "rule_id": "joint.night.double_class_weekday_p1_p2_split",
                "ai_or_operation_delta": 10,
                "ai_or_operations_by_type": {"NewBoolVar": 2, "Add": 8},
            }
        ],
        generic_rule_ids=generic_scheduler_rule_ids(),
    )

    assert payload["ai_or_migration_backlog"][0]["rule_id"] == "joint.night.double_class_weekday_p1_p2_split"
    assert payload["ai_or_migration_backlog"][0]["generic_contract_status"] == "covered_by_generic_contract"
    assert payload["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"


def test_runtime_trace_payload_marks_night_checkin_rule_as_covered() -> None:
    payload = runtime_trace_payload(
        mode="joint",
        run_id="run_demo",
        git_commit=None,
        trace=[
            {
                "rule_id": "joint.night.checkin",
                "ai_or_operation_delta": 29,
                "ai_or_operations_by_type": {"Add": 29},
            }
        ],
        generic_rule_ids=generic_scheduler_rule_ids(),
    )

    assert payload["ai_or_migration_backlog"][0]["rule_id"] == "joint.night.checkin"
    assert payload["ai_or_migration_backlog"][0]["generic_contract_status"] == "covered_by_generic_contract"
    assert payload["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"


def test_runtime_trace_payload_marks_day_weekend_double_period_same_class_rule_as_covered() -> None:
    payload = runtime_trace_payload(
        mode="joint",
        run_id="run_demo",
        git_commit=None,
        trace=[
            {
                "rule_id": "joint.day.weekend_double_period_same_class",
                "ai_or_operation_delta": 36,
                "ai_or_operations_by_type": {"NewBoolVar": 10, "Add": 26},
            }
        ],
        generic_rule_ids=generic_scheduler_rule_ids(),
    )

    assert payload["ai_or_migration_backlog"][0]["rule_id"] == "joint.day.weekend_double_period_same_class"
    assert payload["ai_or_migration_backlog"][0]["generic_contract_status"] == "covered_by_generic_contract"
    assert payload["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"


def test_runtime_trace_payload_marks_day_weekend_cross_halfday_penalty_rule_as_covered() -> None:
    payload = runtime_trace_payload(
        mode="joint",
        run_id="run_demo",
        git_commit=None,
        trace=[
            {
                "rule_id": "joint.day.weekend_cross_halfday_penalty",
                "ai_or_operation_delta": 36,
                "ai_or_operations_by_type": {"NewBoolVar": 16, "Add": 20},
            }
        ],
        generic_rule_ids=generic_scheduler_rule_ids(),
    )

    assert payload["ai_or_migration_backlog"][0]["rule_id"] == "joint.day.weekend_cross_halfday_penalty"
    assert payload["ai_or_migration_backlog"][0]["generic_contract_status"] == "covered_by_generic_contract"
    assert payload["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"


def test_runtime_trace_payload_marks_day_yjc_sunday_am12_pm12_rule_as_covered() -> None:
    payload = runtime_trace_payload(
        mode="joint",
        run_id="run_demo",
        git_commit=None,
        trace=[
            {
                "rule_id": "joint.day.yjc_sunday_am12_pm12_rule",
                "ai_or_operation_delta": 19,
                "ai_or_operations_by_type": {"NewBoolVar": 5, "Add": 14},
            }
        ],
        generic_rule_ids=generic_scheduler_rule_ids(),
    )

    assert payload["ai_or_migration_backlog"][0]["rule_id"] == "joint.day.yjc_sunday_am12_pm12_rule"
    assert payload["ai_or_migration_backlog"][0]["generic_contract_status"] == "covered_by_generic_contract"
    assert payload["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"


def test_runtime_trace_payload_marks_day_binding_8chem_9bio_rule_as_covered() -> None:
    payload = runtime_trace_payload(
        mode="joint",
        run_id="run_demo",
        git_commit=None,
        trace=[
            {
                "rule_id": "joint.day.binding_8chem_9bio",
                "ai_or_operation_delta": 2,
                "ai_or_operations_by_type": {"Add": 2},
            }
        ],
        generic_rule_ids=generic_scheduler_rule_ids(),
    )

    assert payload["ai_or_migration_backlog"][0]["rule_id"] == "joint.day.binding_8chem_9bio"
    assert payload["ai_or_migration_backlog"][0]["generic_contract_status"] == "covered_by_generic_contract"
    assert payload["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"


def test_runtime_trace_payload_marks_day_am1_pm1_mutex_rule_as_covered() -> None:
    payload = runtime_trace_payload(
        mode="joint",
        run_id="run_demo",
        git_commit=None,
        trace=[
            {
                "rule_id": "joint.day.am1_pm1_mutex",
                "ai_or_operation_delta": 21,
                "ai_or_operations_by_type": {"NewBoolVar": 6, "Add": 15},
            }
        ],
        generic_rule_ids=generic_scheduler_rule_ids(),
    )

    assert payload["ai_or_migration_backlog"][0]["rule_id"] == "joint.day.am1_pm1_mutex"
    assert payload["ai_or_migration_backlog"][0]["generic_contract_status"] == "covered_by_generic_contract"
    assert payload["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"


def test_runtime_trace_payload_marks_day_two_class_am1_pm1_combo_rule_as_covered() -> None:
    payload = runtime_trace_payload(
        mode="joint",
        run_id="run_demo",
        git_commit=None,
        trace=[
            {
                "rule_id": "joint.day.two_class_am1_pm1_combo",
                "ai_or_operation_delta": 15,
                "ai_or_operations_by_type": {
                    "NewIntVar": 10,
                    "Add": 10,
                    "AddForbiddenAssignments": 5,
                },
            }
        ],
        generic_rule_ids=generic_scheduler_rule_ids(),
    )

    assert payload["ai_or_migration_backlog"][0]["rule_id"] == "joint.day.two_class_am1_pm1_combo"
    assert payload["ai_or_migration_backlog"][0]["generic_contract_status"] == "covered_by_generic_contract"
    assert payload["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"


def test_runtime_trace_payload_marks_day_am1_pm1_exclusive_rule_as_covered() -> None:
    payload = runtime_trace_payload(
        mode="joint",
        run_id="run_demo",
        git_commit=None,
        trace=[
            {
                "rule_id": "joint.day.am1_pm1_exclusive",
                "ai_or_operation_delta": 21,
                "ai_or_operations_by_type": {"NewBoolVar": 6, "Add": 15},
            }
        ],
        generic_rule_ids=generic_scheduler_rule_ids(),
    )

    assert payload["ai_or_migration_backlog"][0]["rule_id"] == "joint.day.am1_pm1_exclusive"
    assert payload["ai_or_migration_backlog"][0]["generic_contract_status"] == "covered_by_generic_contract"
    assert payload["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"


def test_runtime_trace_payload_marks_day_single_class_weekly_am1_cap_rule_as_covered() -> None:
    payload = runtime_trace_payload(
        mode="joint",
        run_id="run_demo",
        git_commit=None,
        trace=[
            {
                "rule_id": "joint.day.single_class_weekly_am1_cap",
                "ai_or_operation_delta": 37,
                "ai_or_operations_by_type": {"NewBoolVar": 9, "NewIntVar": 2, "Add": 26},
            }
        ],
        generic_rule_ids=generic_scheduler_rule_ids(),
    )

    assert payload["ai_or_migration_backlog"][0]["rule_id"] == "joint.day.single_class_weekly_am1_cap"
    assert payload["ai_or_migration_backlog"][0]["generic_contract_status"] == "covered_by_generic_contract"
    assert payload["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"


def test_runtime_trace_payload_marks_day_core_subject_teacher_day_load_rule_as_covered() -> None:
    payload = runtime_trace_payload(
        mode="joint",
        run_id="run_demo",
        git_commit=None,
        trace=[
            {
                "rule_id": "joint.day.core_subject_teacher_day_load_no_am1_am4",
                "ai_or_operation_delta": 10,
                "ai_or_operations_by_type": {"Add": 10},
            }
        ],
        generic_rule_ids=generic_scheduler_rule_ids(),
    )

    assert payload["ai_or_migration_backlog"][0]["rule_id"] == "joint.day.core_subject_teacher_day_load_no_am1_am4"
    assert payload["ai_or_migration_backlog"][0]["generic_contract_status"] == "covered_by_generic_contract"
    assert payload["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"


def test_runtime_trace_payload_marks_day_teacher_weekday_am_pm_presence_rule_as_covered() -> None:
    payload = runtime_trace_payload(
        mode="joint",
        run_id="run_demo",
        git_commit=None,
        trace=[
            {
                "rule_id": "joint.day.teacher_weekday_am_pm_presence",
                "ai_or_operation_delta": 4,
                "ai_or_operations_by_type": {"Add": 4},
            }
        ],
        generic_rule_ids=generic_scheduler_rule_ids(),
    )

    assert payload["ai_or_migration_backlog"][0]["rule_id"] == "joint.day.teacher_weekday_am_pm_presence"
    assert payload["ai_or_migration_backlog"][0]["generic_contract_status"] == "covered_by_generic_contract"
    assert payload["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"


def test_runtime_trace_payload_marks_day_head_pm1_min_rule_as_covered() -> None:
    payload = runtime_trace_payload(
        mode="joint",
        run_id="run_demo",
        git_commit=None,
        trace=[
            {
                "rule_id": "joint.day.head_pm1_min",
                "ai_or_operation_delta": 5,
                "ai_or_operations_by_type": {"Add": 5},
            }
        ],
        generic_rule_ids=generic_scheduler_rule_ids(),
    )

    assert payload["ai_or_migration_backlog"][0]["rule_id"] == "joint.day.head_pm1_min"
    assert payload["ai_or_migration_backlog"][0]["generic_contract_status"] == "covered_by_generic_contract"
    assert payload["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"


def test_runtime_trace_payload_marks_day_two_class_low_hours_rule_as_covered() -> None:
    payload = runtime_trace_payload(
        mode="joint",
        run_id="run_demo",
        git_commit=None,
        trace=[
            {
                "rule_id": "joint.day.two_class_low_hours_max_empty_days",
                "ai_or_operation_delta": 27,
                "ai_or_operations_by_type": {"NewBoolVar": 10, "Add": 17},
            }
        ],
        generic_rule_ids=generic_scheduler_rule_ids(),
    )

    assert payload["ai_or_migration_backlog"][0]["rule_id"] == "joint.day.two_class_low_hours_max_empty_days"
    assert payload["ai_or_migration_backlog"][0]["generic_contract_status"] == "covered_by_generic_contract"
    assert payload["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"


def test_runtime_trace_payload_marks_day_low_weekday_subject_rule_as_covered() -> None:
    payload = runtime_trace_payload(
        mode="joint",
        run_id="run_demo",
        git_commit=None,
        trace=[
            {
                "rule_id": "joint.day.low_weekday_subject_max1_per_day",
                "ai_or_operation_delta": 5,
                "ai_or_operations_by_type": {"Add": 5},
            }
        ],
        generic_rule_ids=generic_scheduler_rule_ids(),
    )

    assert payload["ai_or_migration_backlog"][0]["rule_id"] == "joint.day.low_weekday_subject_max1_per_day"
    assert payload["ai_or_migration_backlog"][0]["generic_contract_status"] == "covered_by_generic_contract"
    assert payload["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"


def test_runtime_trace_payload_marks_day_high_weekday_subject_rule_as_covered() -> None:
    payload = runtime_trace_payload(
        mode="joint",
        run_id="run_demo",
        git_commit=None,
        trace=[
            {
                "rule_id": "joint.day.high_weekday_subject_min1_per_day",
                "ai_or_operation_delta": 5,
                "ai_or_operations_by_type": {"Add": 5},
            }
        ],
        generic_rule_ids=generic_scheduler_rule_ids(),
    )

    assert payload["ai_or_migration_backlog"][0]["rule_id"] == "joint.day.high_weekday_subject_min1_per_day"
    assert payload["ai_or_migration_backlog"][0]["generic_contract_status"] == "covered_by_generic_contract"
    assert payload["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"


def test_runtime_trace_payload_marks_day_pe_time_window_rule_as_covered() -> None:
    payload = runtime_trace_payload(
        mode="joint",
        run_id="run_demo",
        git_commit=None,
        trace=[
            {
                "rule_id": "joint.day.pe_time_window_hard",
                "ai_or_operation_delta": 3,
                "ai_or_operations_by_type": {"Add": 3},
            }
        ],
        generic_rule_ids=generic_scheduler_rule_ids(),
    )

    assert payload["ai_or_migration_backlog"][0]["rule_id"] == "joint.day.pe_time_window_hard"
    assert payload["ai_or_migration_backlog"][0]["generic_contract_status"] == "covered_by_generic_contract"
    assert payload["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"


def test_runtime_trace_payload_marks_day_reduce_stem_am1_rule_as_covered() -> None:
    payload = runtime_trace_payload(
        mode="joint",
        run_id="run_demo",
        git_commit=None,
        trace=[
            {
                "rule_id": "joint.day.reduce_stem_am1",
                "ai_or_operation_delta": 5,
                "ai_or_operations_by_type": {"ObjectiveTerm": 5},
            }
        ],
        generic_rule_ids=generic_scheduler_rule_ids(),
    )

    assert payload["ai_or_migration_backlog"][0]["rule_id"] == "joint.day.reduce_stem_am1"
    assert payload["ai_or_migration_backlog"][0]["generic_contract_status"] == "covered_by_generic_contract"
    assert payload["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"


def test_runtime_trace_payload_marks_day_pe_reduce_am_soft_rule_as_covered() -> None:
    payload = runtime_trace_payload(
        mode="joint",
        run_id="run_demo",
        git_commit=None,
        trace=[
            {
                "rule_id": "joint.day.pe_reduce_am_soft",
                "ai_or_operation_delta": 3,
                "ai_or_operations_by_type": {"ObjectiveTerm": 3},
            }
        ],
        generic_rule_ids=generic_scheduler_rule_ids(),
    )

    assert payload["ai_or_migration_backlog"][0]["rule_id"] == "joint.day.pe_reduce_am_soft"
    assert payload["ai_or_migration_backlog"][0]["generic_contract_status"] == "covered_by_generic_contract"
    assert payload["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"


def test_runtime_trace_payload_marks_day_pref_lang_am_rule_as_covered() -> None:
    payload = runtime_trace_payload(
        mode="joint",
        run_id="run_demo",
        git_commit=None,
        trace=[
            {
                "rule_id": "joint.day.pref_lang_am",
                "ai_or_operation_delta": 4,
                "ai_or_operations_by_type": {"ObjectiveTerm": 4},
            }
        ],
        generic_rule_ids=generic_scheduler_rule_ids(),
    )

    assert payload["ai_or_migration_backlog"][0]["rule_id"] == "joint.day.pref_lang_am"
    assert payload["ai_or_migration_backlog"][0]["generic_contract_status"] == "covered_by_generic_contract"
    assert payload["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"


def test_runtime_trace_payload_marks_day_pe_tech_compact_soft_rule_as_covered() -> None:
    payload = runtime_trace_payload(
        mode="joint",
        run_id="run_demo",
        git_commit=None,
        trace=[
            {
                "rule_id": "joint.day.pe_tech_compact_soft",
                "ai_or_operation_delta": 19,
                "ai_or_operations_by_type": {"Add": 12, "NewBoolVar": 7},
            }
        ],
        generic_rule_ids=generic_scheduler_rule_ids(),
    )

    assert payload["ai_or_migration_backlog"][0]["rule_id"] == "joint.day.pe_tech_compact_soft"
    assert payload["ai_or_migration_backlog"][0]["generic_contract_status"] == "covered_by_generic_contract"
    assert payload["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"


def test_runtime_trace_payload_marks_day_teacher_am4_pm1_threshold_rule_as_covered() -> None:
    payload = runtime_trace_payload(
        mode="joint",
        run_id="run_demo",
        git_commit=None,
        trace=[
            {
                "rule_id": "joint.day.teacher_am4_pm1_threshold_penalty",
                "ai_or_operation_delta": 11,
                "ai_or_operations_by_type": {"Add": 6, "NewIntVar": 5},
            }
        ],
        generic_rule_ids=generic_scheduler_rule_ids(),
    )

    assert payload["ai_or_migration_backlog"][0]["rule_id"] == "joint.day.teacher_am4_pm1_threshold_penalty"
    assert payload["ai_or_migration_backlog"][0]["generic_contract_status"] == "covered_by_generic_contract"
    assert payload["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"


def test_runtime_trace_payload_marks_day_weekday_subject_balance_rule_as_covered() -> None:
    payload = runtime_trace_payload(
        mode="joint",
        run_id="run_demo",
        git_commit=None,
        trace=[
            {
                "rule_id": "joint.day.weekday_subject_balance",
                "ai_or_operation_delta": 30,
                "ai_or_operations_by_type": {"Add": 15, "NewIntVar": 15},
            }
        ],
        generic_rule_ids=generic_scheduler_rule_ids(),
    )

    assert payload["ai_or_migration_backlog"][0]["rule_id"] == "joint.day.weekday_subject_balance"
    assert payload["ai_or_migration_backlog"][0]["generic_contract_status"] == "covered_by_generic_contract"
    assert payload["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"


def test_runtime_trace_payload_marks_day_teacher_continuity_rule_as_covered() -> None:
    payload = runtime_trace_payload(
        mode="joint",
        run_id="run_demo",
        git_commit=None,
        trace=[
            {
                "rule_id": "joint.day.teacher_continuity_penalty",
                "ai_or_operation_delta": 19,
                "ai_or_operations_by_type": {"Add": 12, "NewBoolVar": 7},
            }
        ],
        generic_rule_ids=generic_scheduler_rule_ids(),
    )

    assert payload["ai_or_migration_backlog"][0]["rule_id"] == "joint.day.teacher_continuity_penalty"
    assert payload["ai_or_migration_backlog"][0]["generic_contract_status"] == "covered_by_generic_contract"
    assert payload["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"


def test_runtime_trace_payload_marks_day_two_class_daily_min_rule_as_covered() -> None:
    payload = runtime_trace_payload(
        mode="joint",
        run_id="run_demo",
        git_commit=None,
        trace=[
            {
                "rule_id": "joint.day.two_class_daily_min_per_class",
                "ai_or_operation_delta": 78,
                "ai_or_operations_by_type": {"Add": 53, "NewBoolVar": 25},
            }
        ],
        generic_rule_ids=generic_scheduler_rule_ids(),
    )

    assert payload["ai_or_migration_backlog"][0]["rule_id"] == "joint.day.two_class_daily_min_per_class"
    assert payload["ai_or_migration_backlog"][0]["generic_contract_status"] == "covered_by_generic_contract"
    assert payload["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"


def test_runtime_trace_payload_marks_day_teacher_m1_cap_rule_as_covered() -> None:
    payload = runtime_trace_payload(
        mode="joint",
        run_id="run_demo",
        git_commit=None,
        trace=[
            {
                "rule_id": "joint.day.teacher_m1_cap_constraint",
                "ai_or_operation_delta": 20,
                "ai_or_operations_by_type": {"Add": 12, "NewBoolVar": 6, "NewIntVar": 2},
            }
        ],
        generic_rule_ids=generic_scheduler_rule_ids(),
    )

    assert payload["ai_or_migration_backlog"][0]["rule_id"] == "joint.day.teacher_m1_cap_constraint"
    assert payload["ai_or_migration_backlog"][0]["generic_contract_status"] == "covered_by_generic_contract"
    assert payload["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"


def test_runtime_trace_payload_marks_day_teacher_am1_fragmentation_rule_as_covered() -> None:
    payload = runtime_trace_payload(
        mode="joint",
        run_id="run_demo",
        git_commit=None,
        trace=[
            {
                "rule_id": "joint.day.teacher_am1_fragmentation",
                "ai_or_operation_delta": 49,
                "ai_or_operations_by_type": {"Add": 31, "NewBoolVar": 15, "NewIntVar": 3},
            }
        ],
        generic_rule_ids=generic_scheduler_rule_ids(),
    )

    assert payload["ai_or_migration_backlog"][0]["rule_id"] == "joint.day.teacher_am1_fragmentation"
    assert payload["ai_or_migration_backlog"][0]["generic_contract_status"] == "covered_by_generic_contract"
    assert payload["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"


def test_runtime_trace_payload_marks_day_multi_class_halfday_rule_as_covered() -> None:
    payload = runtime_trace_payload(
        mode="joint",
        run_id="run_demo",
        git_commit=None,
        trace=[
            {
                "rule_id": "joint.day.multi_class_halfday_soft",
                "ai_or_operation_delta": 74,
                "ai_or_operations_by_type": {
                    "Add": 45,
                    "AddMaxEquality": 1,
                    "NewBoolVar": 26,
                    "NewIntVar": 2,
                },
            }
        ],
        generic_rule_ids=generic_scheduler_rule_ids(),
    )

    assert payload["ai_or_migration_backlog"][0]["rule_id"] == "joint.day.multi_class_halfday_soft"
    assert payload["ai_or_migration_backlog"][0]["generic_contract_status"] == "covered_by_generic_contract"
    assert payload["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"


def test_runtime_trace_payload_preserves_zero_delta_solver_parameter_rules() -> None:
    payload = runtime_trace_payload(
        mode="joint",
        run_id="run_demo",
        git_commit=None,
        trace=[
            {"rule_id": "day.solver_parameters", "ai_or_operation_delta": 0, "ai_or_operations_by_type": {}},
            {"rule_id": "night.solver_parameters", "ai_or_operation_delta": 0, "ai_or_operations_by_type": {}},
            {"rule_id": "joint.solver_parameters", "ai_or_operation_delta": 0, "ai_or_operations_by_type": {}},
        ],
        generic_rule_ids=generic_scheduler_rule_ids(),
    )

    assert [item["rule_id"] for item in payload["trace"]] == [
        "day.solver_parameters",
        "night.solver_parameters",
        "joint.solver_parameters",
    ]
    assert payload["ai_or_operation_summary"]["total_operation_delta"] == 0
    assert payload["ai_or_migration_backlog"] == []
    assert payload["ai_or_agent_migration_plan"] == []


def test_runtime_trace_payload_marks_grade_group_duty_rule_as_covered() -> None:
    payload = runtime_trace_payload(
        mode="joint",
        run_id="run_demo",
        git_commit=None,
        trace=[
            {
                "rule_id": "joint.link.grade_group_duty_constraints",
                "ai_or_operation_delta": 105,
                "ai_or_operations_by_type": {
                    "Add": 56,
                    "NewBoolVar": 30,
                    "NewConstant": 12,
                    "NewIntVar": 7,
                },
            }
        ],
        generic_rule_ids=generic_scheduler_rule_ids(),
    )

    assert payload["ai_or_migration_backlog"][0]["rule_id"] == "joint.link.grade_group_duty_constraints"
    assert payload["ai_or_migration_backlog"][0]["generic_contract_status"] == "covered_by_generic_contract"
    assert payload["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"


def test_runtime_trace_payload_marks_duty_joint_rules_as_covered() -> None:
    payload = runtime_trace_payload(
        mode="joint",
        run_id="run_demo",
        git_commit=None,
        trace=[
            {
                "rule_id": "joint.link.duty_joint_constraints",
                "ai_or_operation_delta": 136,
                "ai_or_operations_by_type": {"Add": 89, "NewBoolVar": 8, "NewIntVar": 39},
            },
            {
                "rule_id": "day.duty_joint_constraints",
                "ai_or_operation_delta": 136,
                "ai_or_operations_by_type": {"Add": 89, "NewBoolVar": 8, "NewIntVar": 39},
            },
        ],
        generic_rule_ids=generic_scheduler_rule_ids(),
    )

    by_rule = {item["rule_id"]: item for item in payload["ai_or_migration_backlog"]}
    assert by_rule["joint.link.duty_joint_constraints"]["generic_contract_status"] == "covered_by_generic_contract"
    assert by_rule["day.duty_joint_constraints"]["generic_contract_status"] == "covered_by_generic_contract"
    assert {item["owner_agent_role"] for item in payload["ai_or_agent_migration_plan"]} == {"code_execution"}


def test_runtime_trace_payload_marks_night_soft_objective_rules_as_covered() -> None:
    payload = runtime_trace_payload(
        mode="joint",
        run_id="run_demo",
        git_commit=None,
        trace=[
            {
                "rule_id": "joint.night.soft_objective",
                "ai_or_operation_delta": 133,
                "ai_or_operations_by_type": {"Add": 93, "NewBoolVar": 40},
            },
            {
                "rule_id": "night.soft_objective",
                "ai_or_operation_delta": 133,
                "ai_or_operations_by_type": {"Add": 93, "NewBoolVar": 40},
            },
        ],
        generic_rule_ids=generic_scheduler_rule_ids(),
    )

    by_rule = {item["rule_id"]: item for item in payload["ai_or_migration_backlog"]}
    assert by_rule["joint.night.soft_objective"]["generic_contract_status"] == "covered_by_generic_contract"
    assert by_rule["night.soft_objective"]["generic_contract_status"] == "covered_by_generic_contract"
    assert {item["owner_agent_role"] for item in payload["ai_or_agent_migration_plan"]} == {"code_execution"}


def test_runtime_trace_payload_marks_personalized_catalog_rules_as_covered() -> None:
    payload = runtime_trace_payload(
        mode="joint",
        run_id="run_demo",
        git_commit=None,
        trace=[
            {
                "rule_id": "shared.personalized_constraints",
                "ai_or_operation_delta": 1,
                "ai_or_operations_by_type": {"Add": 1},
            },
            {
                "rule_id": "personalized.xhd_night_no_pm3",
                "ai_or_operation_delta": 1,
                "ai_or_operations_by_type": {"Add": 1},
            },
        ],
        generic_rule_ids=generic_scheduler_rule_ids(),
    )

    by_rule = {item["rule_id"]: item for item in payload["ai_or_migration_backlog"]}
    assert by_rule["shared.personalized_constraints"]["generic_contract_status"] == "covered_by_generic_contract"
    assert by_rule["personalized.xhd_night_no_pm3"]["generic_contract_status"] == "covered_by_generic_contract"
    assert {item["owner_agent_role"] for item in payload["ai_or_agent_migration_plan"]} == {"code_execution"}


def test_runtime_trace_payload_marks_day_special_duty_catalog_rules_as_covered() -> None:
    payload = runtime_trace_payload(
        mode="joint",
        run_id="run_demo",
        git_commit=None,
        trace=[
            {
                "rule_id": "joint.day.head_duty_constraints",
                "ai_or_operation_delta": 1,
                "ai_or_operations_by_type": {"Add": 1},
            },
            {
                "rule_id": "joint.day.noon_dorm_duty_constraints",
                "ai_or_operation_delta": 1,
                "ai_or_operations_by_type": {"Add": 1},
            },
        ],
        generic_rule_ids=generic_scheduler_rule_ids(),
    )

    by_rule = {item["rule_id"]: item for item in payload["ai_or_migration_backlog"]}
    assert by_rule["joint.day.head_duty_constraints"]["generic_contract_status"] == "covered_by_generic_contract"
    assert by_rule["joint.day.noon_dorm_duty_constraints"]["generic_contract_status"] == "covered_by_generic_contract"
    assert {item["owner_agent_role"] for item in payload["ai_or_agent_migration_plan"]} == {"code_execution"}


def test_runtime_trace_payload_marks_day_teacher_whitelist_rule_as_covered() -> None:
    payload = runtime_trace_payload(
        mode="joint",
        run_id="run_demo",
        git_commit=None,
        trace=[
            {
                "rule_id": "joint.day.teacher_whitelist_hard",
                "ai_or_operation_delta": 4,
                "ai_or_operations_by_type": {"Add": 4},
            }
        ],
        generic_rule_ids=generic_scheduler_rule_ids(),
    )

    assert payload["ai_or_migration_backlog"][0]["rule_id"] == "joint.day.teacher_whitelist_hard"
    assert payload["ai_or_migration_backlog"][0]["generic_contract_status"] == "covered_by_generic_contract"
    assert payload["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"


def main() -> None:
    _assert_runtime_snapshot_write()
    print("test_rule_runtime_snapshots: PASS")

if __name__ == "__main__":
    raise SystemExit(main())

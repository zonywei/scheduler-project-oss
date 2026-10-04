# -*- coding: utf-8 -*-
from __future__ import annotations

import copy
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from scheduler.app.config_service import (
    IO_PATH,
    PROJECT_ROOT,
    RULES_PATH,
    build_effective_config_fingerprint,
    load_academic_affairs_payload,
    load_day_rule_tables,
    load_effective_payload,
    list_teacher_subject_rows,
    preview_rule_field_updates,
)
from scheduler.app.business_rules import build_business_rule_groups
from scheduler.app.conflict_detection import detect_rule_conflicts
from scheduler.app.rule_modeling import build_rule_modeling_receipt
from scheduler.calendar import ALL_DAYS, DAY_NAME_SET, DEFAULT_NIGHT_DAYS as CANONICAL_DEFAULT_NIGHT_DAYS, day_rank
from scheduler.data.teacher_table_schema import teacher_subject_columns
from scheduler.platform.runtime import runtime_organization_id, uses_sqlite_workspace


DOMAIN_ORDER = ["配置文件", "基础数据", "白天规则", "值班/查寝", "规则冲突", "规则建模", "求解历史", "教务风险"]
SEVERITY_ORDER = {"ok": 0, "info": 1, "warning": 2, "error": 3}
DEFAULT_NIGHT_DAYS = list(CANONICAL_DEFAULT_NIGHT_DAYS)
WEB_RUN_ROOT = PROJECT_ROOT / "outputs" / "web_runs"
RUN_DIR_PATTERN = re.compile(r"^run_\d{8}_\d{6}$")


def build_solve_readiness(mode: str = "joint") -> dict[str, Any]:
    normalized_mode = mode if mode in {"joint", "night"} else "joint"
    config_payload = load_effective_payload(normalized_mode)
    teacher_rows = list_teacher_subject_rows()
    day_rules = load_day_rule_tables() if normalized_mode == "joint" else {}
    academic_payload = load_academic_affairs_payload()
    conflicts = detect_rule_conflicts(config_payload.get("effective", {}), teacher_rows)
    readiness = build_readiness_payload(
        mode=normalized_mode,
        config_payload=config_payload,
        teacher_rows=teacher_rows,
        day_rule_tables=day_rules,
        academic_payload=academic_payload,
        conflict_payload=conflicts,
    )
    return _with_runtime_history_items(readiness, normalized_mode)


def build_solve_readiness_preview(mode: str = "joint", fields: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    normalized_mode = mode if mode in {"joint", "night"} else "joint"
    preview = preview_rule_field_updates(fields or [])
    config_payload = _preview_config_payload(normalized_mode, preview.get("overrides", {}))
    teacher_rows = list_teacher_subject_rows()
    day_rules = load_day_rule_tables() if normalized_mode == "joint" else {}
    academic_payload = load_academic_affairs_payload()
    conflicts = detect_rule_conflicts(config_payload.get("effective", {}), teacher_rows)
    readiness = build_readiness_payload(
        mode=normalized_mode,
        config_payload=config_payload,
        teacher_rows=teacher_rows,
        day_rule_tables=day_rules,
        academic_payload=academic_payload,
        conflict_payload=conflicts,
    )
    readiness["preview"] = {
        "persisted": False,
        "changed_fields": preview.get("changes", []),
        "changed_count": len(preview.get("changes", []) or []),
    }
    return readiness


def _with_runtime_history_items(readiness: dict[str, Any], mode: str) -> dict[str, Any]:
    try:
        current_fingerprint = build_effective_config_fingerprint(mode)
    except Exception:
        return readiness
    item = latest_matching_infeasible_item(mode, current_fingerprint)
    if not item:
        return readiness
    items = list(readiness.get("items") or [])
    items.append(item)
    readiness["items"] = items
    readiness["summary"] = _summary(items)
    readiness["stages"] = _stages(items)
    readiness["remediation_options"] = _remediation_options(items)
    readiness["next_actions"] = _next_actions(items)
    return readiness


def latest_matching_infeasible_item(
    mode: str,
    current_fingerprint: dict[str, Any],
    *,
    web_run_root: Path | None = None,
) -> dict[str, Any] | None:
    web_run_root = web_run_root or _runtime_web_run_root()
    run_dir = _latest_history_run_dir(web_run_root)
    if run_dir is None:
        return None
    status = _read_history_status(run_dir)
    if str(status.get("run_purpose") or "") == "diagnostic_trial":
        return None
    if str(status.get("mode") or "joint") != mode:
        return None
    if _fingerprint_hash(status.get("config_fingerprint")) != _fingerprint_hash(current_fingerprint):
        return None

    solver_status = str(status.get("solver_status") or "").strip()
    if not solver_status:
        solver_status = _first_match(_read_text(Path(str(status.get("log_file") or run_dir / "run.log"))), r"求解状态：([A-Z_]+)") or ""
    if solver_status != "INFEASIBLE":
        return None

    solution_count = status.get("solution_count")
    if not isinstance(solution_count, int):
        solution_raw = _first_match(_read_text(Path(str(status.get("log_file") or run_dir / "run.log"))), r"回调捕获解数量：(\d+)")
        solution_count = int(solution_raw) if str(solution_raw or "").isdigit() else 0
    run_id = str(status.get("run_id") or run_dir.name)
    completed_at = str(status.get("completed_at") or status.get("updated_at") or "")
    completed_label = f"（{completed_at}）" if completed_at else ""
    return _item(
        "error",
        "求解历史",
        "当前配置已被证明无解",
        (
            f"最近正式批次 {run_id}{completed_label} 使用相同配置，"
            f"求解器状态 {solver_status}，捕获 {solution_count} 个可行解。"
        ),
        "先查看求解结果页的排障建议，应用临时试跑方案或修改硬约束；配置变更后再重新正式求解。",
        blocking=True,
        publish_blocking=True,
        evidence=[
            {"label": "批次目录", "value": str(run_dir), "tone": "error"},
            {"label": "配置指纹", "value": _short_hash(current_fingerprint), "tone": "info"},
        ],
        remediations=_checkin_same_day_class_remediations(include_results_quick_action=True),
    )


def _runtime_web_run_root() -> Path:
    if not uses_sqlite_workspace():
        return WEB_RUN_ROOT
    organization_id = runtime_organization_id()
    safe_organization_id = re.sub(r"[^A-Za-z0-9._-]", "_", organization_id)
    return PROJECT_ROOT / "outputs" / "tenants" / safe_organization_id / "web_runs"


def _latest_history_run_dir(web_run_root: Path) -> Path | None:
    if not web_run_root.exists():
        return None
    runs = [
        path
        for path in web_run_root.iterdir()
        if path.is_dir() and RUN_DIR_PATTERN.fullmatch(path.name)
    ]
    return max(runs, key=lambda path: path.stat().st_mtime) if runs else None


def _read_history_status(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "status.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _fingerprint_hash(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("hash") or "").strip()
    return str(value or "").strip()


def _short_hash(value: Any) -> str:
    text = _fingerprint_hash(value)
    return text[:12] if text else "未记录"


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _first_match(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text)
    return match.group(1).strip() if match else None


def _preview_config_payload(mode: str, overrides: dict[str, Any]) -> dict[str, Any]:
    config_payload = copy.deepcopy(load_effective_payload(mode))
    io_override = overrides.get("io") if isinstance(overrides.get("io"), dict) else {}
    rules_override = overrides.get("rules") if isinstance(overrides.get("rules"), dict) else {}
    temporary = overrides.get("temporary_rules") if isinstance(overrides.get("temporary_rules"), dict) else None
    rules_for_merge = copy.deepcopy(rules_override)
    if temporary is not None:
        rules_for_merge["temporary_rules"] = temporary
    io_cfg = _deep_merge(config_payload.get("io", {}), io_override)
    rules_cfg = _deep_merge(config_payload.get("rules", {}), rules_for_merge)
    effective = _deep_merge(io_cfg, rules_cfg)
    config_payload["io"] = io_cfg
    config_payload["rules"] = rules_cfg
    config_payload["effective"] = effective
    config_payload["overrides_preview"] = {
        "persisted": False,
        "io": copy.deepcopy(io_override),
        "rules": copy.deepcopy(rules_override),
    }
    config_payload["business_rule_groups"] = build_business_rule_groups(effective)
    return config_payload


def build_readiness_payload(
    *,
    mode: str,
    config_payload: dict[str, Any],
    teacher_rows: list[dict[str, Any]],
    day_rule_tables: dict[str, list[dict[str, Any]]],
    academic_payload: dict[str, Any],
    conflict_payload: dict[str, Any],
) -> dict[str, Any]:
    effective = config_payload.get("effective", {}) if isinstance(config_payload, dict) else {}
    items: list[dict[str, Any]] = []
    items.extend(_config_items(config_payload))
    items.extend(_teacher_items(effective, teacher_rows, mode=mode))
    if mode == "joint":
        items.extend(_day_rule_items(day_rule_tables))
        items.extend(_duty_checkin_capacity_items(effective, teacher_rows, day_rule_tables))
    items.extend(_conflict_items(conflict_payload))
    items.extend(_academic_items(academic_payload, effective, teacher_rows))
    modeling = build_rule_modeling_receipt(
        mode,
        config_payload,
        teacher_rows=teacher_rows,
        day_rule_tables=day_rule_tables,
    )
    items.append(
        _item(
            "ok" if modeling.get("ready") else "error",
            "规则建模",
            "全部启用规则已实际建模" if modeling.get("ready") else "存在仅生成卡片但未进入模型的规则",
            str(modeling.get("message") or ""),
            "返回规则中心补全、确认或删除未建模规则后再求解。",
            blocking=not bool(modeling.get("ready")),
        )
    )

    summary = _summary(items)
    return {
        "mode": mode,
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "summary": summary,
        "stages": _stages(items),
        "items": items,
        "remediation_options": _remediation_options(items),
        "next_actions": _next_actions(items),
        "metrics": _metrics(config_payload, teacher_rows, day_rule_tables, academic_payload, conflict_payload),
        "conflicts": {
            "summary": conflict_payload.get("summary", {}) if isinstance(conflict_payload, dict) else {},
        },
        "modeling": modeling,
    }


def _deep_merge(base: Any, override: Any) -> Any:
    if isinstance(base, dict) and isinstance(override, dict):
        out = copy.deepcopy(base)
        for key, value in override.items():
            out[key] = _deep_merge(out.get(key), value) if key in out else copy.deepcopy(value)
        return out
    return copy.deepcopy(override) if override is not None else copy.deepcopy(base)


def _config_items(config_payload: dict[str, Any]) -> list[dict[str, Any]]:
    paths = config_payload.get("paths", {}) if isinstance(config_payload, dict) else {}
    io_path = Path(str(paths.get("io") or IO_PATH))
    rules_path = Path(str(paths.get("rules") or RULES_PATH))
    items = []
    for label, path in [("输入输出配置", io_path), ("规则配置", rules_path)]:
        if path.exists() and path.is_file():
            items.append(_item("ok", "配置文件", f"{label}可读取", str(path), "保持配置文件纳入版本管理。"))
        else:
            items.append(_item("error", "配置文件", f"{label}缺失", str(path), "恢复该配置文件后再启动求解。", blocking=True))
    return items


def _teacher_items(effective: dict[str, Any], rows: list[dict[str, Any]], *, mode: str) -> list[dict[str, Any]]:
    if not rows:
        return [
            _item(
                "error",
                "基础数据",
                "教师定位表没有可用数据",
                "求解需要至少一行班级、学科和任课教师关系。",
                "在“教师定位”导入 Excel 或直接录入并保存 Web 配置。",
                blocking=True,
            )
        ]

    teacher_cfg = effective.get("teacher_table", {}) if isinstance(effective, dict) else {}
    columns = teacher_cfg.get("columns", {}) if isinstance(teacher_cfg, dict) else {}
    class_col = str(columns.get("class") or "班级")
    head_col = str(columns.get("head") or "班主任")
    head_gender_col = str(columns.get("head_gender") or "班主任性别")
    subject_cols = sorted(
        {
            key
            for row in rows
            for key in teacher_subject_columns(
                row.keys(),
                class_col=class_col,
                head_col=head_col,
                gender_col=head_gender_col,
            )
        }
    )
    available_columns = sorted({key for row in rows for key in row if key != "row_index"})

    items: list[dict[str, Any]] = [
        _item("ok", "基础数据", "教师定位表已加载", f"当前可用班级行 {len(rows)} 行。", "继续检查班级列、任课教师和重复班级。")
    ]

    blank_classes = [idx for idx, row in enumerate(rows, start=1) if not str(row.get(class_col) or "").strip()]
    if blank_classes:
        items.append(
            _item(
                "error",
                "基础数据",
                "存在未填写班级的教师定位行",
                f"第 {', '.join(map(str, blank_classes[:8]))} 行缺少“{class_col}”。",
                "补齐班级名称，或删除无效空行。",
                blocking=True,
            )
        )

    class_names = [str(row.get(class_col) or "").strip() for row in rows if str(row.get(class_col) or "").strip()]
    duplicate_classes = sorted([name for name, count in Counter(class_names).items() if count > 1])
    if duplicate_classes:
        items.append(
            _item(
                "error",
                "基础数据",
                "教师定位表存在重复班级",
                "重复班级：" + "、".join(duplicate_classes[:8]),
                "一个行政班只保留一行，避免同一班级被重复建模。",
                blocking=True,
            )
        )

    head_rules_enabled = mode == "joint" and _joint_head_teacher_required(effective)
    head_names = [str(row.get(head_col) or "").strip() for row in rows if str(row.get(head_col) or "").strip()]
    if head_rules_enabled and not head_names:
        items.append(
            _item(
                "info",
                "基础数据",
                "未提供班主任信息（可选）",
                "教师定位表没有读取到班主任列或班主任姓名；这不影响课程排课，本次会跳过依赖班主任的 PM1、值班和查寝附加约束。",
                f"如需启用这些附加模块，再补充“{head_col}”及性别列；课程排课无需补充。",
            )
        )

    if not subject_cols:
        items.append(
            _item(
                "error",
                "基础数据",
                "教师定位表缺少学科列",
                "未发现除班级、班主任、性别以外的任课教师列。",
                "补充至少一列实际学科/任课教师列；系统会按本次上传表格的表头识别学科。",
                blocking=True,
            )
        )
        return items

    rows_without_teacher = [
        str(row.get(class_col) or f"第{idx}行")
        for idx, row in enumerate(rows, start=1)
        if not any(str(row.get(col) or "").strip() for col in subject_cols)
    ]
    if rows_without_teacher:
        items.append(
            _item(
                "warning",
                "基础数据",
                "部分班级没有填写任课教师",
                "涉及：" + "、".join(rows_without_teacher[:8]),
                "补齐主要学科教师，避免求解时可排课资源不足。",
            )
        )

    evening = effective.get("evening", {}) if isinstance(effective, dict) else {}
    configured_subjects = _as_str_list(evening.get("subjects"))
    required_subjects = [subject for subject in configured_subjects if subject in available_columns] if configured_subjects else subject_cols
    missing_subject_columns = [subject for subject in configured_subjects if subject not in available_columns]
    if missing_subject_columns:
        items.append(
            _item(
                "error",
                "基础数据",
                "晚自习学科列缺失",
                "缺少列：" + "、".join(missing_subject_columns[:12]),
                "在教师定位表中增加这些学科列，或调整规则配置中的晚自习学科白名单。",
                blocking=True,
            )
        )
    present_subjects = [subject for subject in required_subjects if subject in available_columns]
    total_pairs = len(rows) * len(present_subjects)
    missing_pairs = sum(
        1
        for row in rows
        for subject in present_subjects
        if not str(row.get(subject) or "").strip()
    )
    if total_pairs and missing_pairs == total_pairs:
        items.append(
            _item(
                "error",
                "基础数据",
                "晚自习学科没有任课教师",
                f"已识别 {len(present_subjects)} 个晚自习学科列，但 {len(rows)} 个班的任课教师单元全部为空。",
                "导入已填写任课教师的教师定位表，或直接在页面补齐后保存配置。",
                blocking=True,
            )
        )
    elif missing_pairs:
        items.append(
            _item(
                "warning",
                "基础数据",
                "部分晚自习学科教师缺失",
                f"缺失 {missing_pairs} 个班级-学科任课教师单元，已填 {total_pairs - missing_pairs} 个。",
                "补齐空白单元；如果某些学科本轮不排，请调整晚自习学科白名单。",
            )
        )
    return items


def _joint_head_teacher_required(effective: dict[str, Any]) -> bool:
    if not isinstance(effective, dict):
        return True
    day_cfg = effective.get("day", {})
    if not isinstance(day_cfg, dict):
        return True
    weekday_cfg = day_cfg.get("weekday_constraints", {})
    weekday_cfg = weekday_cfg if isinstance(weekday_cfg, dict) else {}
    if _cfg_bool(weekday_cfg, "enable_head_pm1_min", True):
        return True

    head_duty_cfg = day_cfg.get("head_duty_constraints", {})
    head_duty_cfg = head_duty_cfg if isinstance(head_duty_cfg, dict) else {}
    if not _cfg_bool(head_duty_cfg, "enabled", True):
        return False
    return any(
        _cfg_bool(head_duty_cfg, key, False)
        for key in ("enable_head_duty", "enable_pm1_min_if_missing", "enable_weekday_pm1_requires_duty")
    )


def _day_rule_items(tables: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    time_grid = tables.get("time_grid") or []
    subject_hours = tables.get("subject_hours") or []
    if not time_grid:
        items.append(
            _item(
                "error",
                "白天规则",
                "白天时间格子为空",
                "联合求解需要可用节次和星期矩阵。",
                "在“白天规则基础表”维护时间格子，或恢复“白天规则.xlsx”。",
                blocking=True,
            )
        )
    else:
        items.append(_item("ok", "白天规则", "白天时间格子已加载", f"当前 {len(time_grid)} 行。", "继续确认可用星期列。"))

    positive_subject_rows = [row for row in subject_hours if str(row.get("学科") or "").strip() and _row_has_positive_hours(row)]
    if not subject_hours:
        items.append(
            _item(
                "error",
                "白天规则",
                "学科课时表为空",
                "白天模型无法知道每个学科每周应排多少节。",
                "补齐“学科课时”表后再求解。",
                blocking=True,
            )
        )
    elif not positive_subject_rows:
        items.append(
            _item(
                "error",
                "白天规则",
                "学科课时没有正数需求",
                "学科课时表存在，但没有识别到正数课时。",
                "检查早自习课时、周中课时、周末课时等字段是否填写为数字。",
                blocking=True,
            )
        )
    else:
        items.append(_item("ok", "白天规则", "学科课时已加载", f"识别到 {len(positive_subject_rows)} 个有效学科课时行。", "可继续做冲突检测。"))
    return items


def _duty_checkin_capacity_items(
    effective: dict[str, Any],
    rows: list[dict[str, Any]],
    day_rule_tables: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    if not isinstance(effective, dict):
        return []
    day_cfg = effective.get("day", {}) if isinstance(effective.get("day"), dict) else {}
    head_cfg = day_cfg.get("head_duty_constraints", {}) if isinstance(day_cfg.get("head_duty_constraints"), dict) else {}
    checkin_cfg = effective.get("checkin", {}) if isinstance(effective.get("checkin"), dict) else {}
    if not head_cfg and not checkin_cfg:
        return []

    items: list[dict[str, Any]] = []
    head_enabled = _head_duty_enabled(head_cfg) if head_cfg else False
    checkin_enabled = _cfg_bool(checkin_cfg, "enabled", False) if checkin_cfg else False

    head_pool = _head_teacher_pool(effective, rows)
    night_days = _night_days(effective)
    per_day = checkin_cfg.get("per_day", {}) if isinstance(checkin_cfg.get("per_day"), dict) else {}
    male_need = max(0, _to_int(per_day.get("male"), 1))
    female_need = max(0, _to_int(per_day.get("female"), 1))
    if checkin_enabled and (
        (male_need > 0 and not head_pool.get("male"))
        or (female_need > 0 and not head_pool.get("female"))
    ):
        items.append(
            _item(
                "info",
                "值班/查寝",
                "未提供完整查寝候选字段（可选）",
                "教师定位表没有提供满足当前查寝需求的班主任性别候选池；本次只进行课程排课，晚查寝附加模块自动跳过，不会把课程模型判为无解。",
                "如需生成晚查寝，再补充班主任与性别列，或在 checkin.extra_heads 中维护经确认的候选人。",
            )
        )
        checkin_enabled = False
    if checkin_enabled:
        items.extend(_checkin_extra_head_quality_items(effective, rows, checkin_cfg))
        items.extend(_checkin_capacity_items(checkin_cfg, head_pool, night_days))

    if head_enabled:
        items.extend(_head_duty_shape_items(effective, rows, day_rule_tables))

    duty_joint_cfg = day_cfg.get("duty_joint_constraints", {}) if isinstance(day_cfg.get("duty_joint_constraints"), dict) else {}
    if duty_joint_cfg and checkin_enabled and _cfg_bool(duty_joint_cfg, "enabled", True):
        items.extend(_duty_joint_male_total_items(effective, checkin_cfg, duty_joint_cfg, head_pool, night_days, day_rule_tables))

    if head_enabled and checkin_enabled and _checkin_same_day_class_mode(checkin_cfg) == "hard":
        pm1_requires_duty_hard = (
            _cfg_bool(head_cfg, "enable_weekday_pm1_requires_duty", True)
            and str(head_cfg.get("weekday_pm1_requires_duty_mode", "hard")).strip().lower() == "hard"
        )
        if pm1_requires_duty_hard:
            items.append(
                _item(
                    "warning",
                    "值班/查寝",
                    "班主任值班与晚查寝硬联动过紧",
                    (
                        "下午课前值班要求工作日班主任下午第1节与值班同日绑定，"
                        f"晚查寝又要求查寝教师当天有晚自习；当前晚查寝覆盖 {len(night_days)} 天，"
                        "两条硬链路会同时压到同一批班主任。"
                    ),
                    "若严格求解无结果，优先把“下午课前值班必须同日PM1”或“晚查寝必须当天有晚自习”改为软约束，或使用诊断放宽方案定位后再回到正式规则重排。",
                    remediations=[
                        _remediation(
                            "head_duty.pm1_requires_duty_soft",
                            "把PM1同日值班改为软约束",
                            "保留偏好但不再让同日PM1绑定直接阻断求解。",
                            "可能出现少量班主任PM1与值班不同日，发布前需复核值班公平性。",
                            [
                                _remediation_field(
                                    "下午课前值班同日PM1模式",
                                    "day.head_duty_constraints.weekday_pm1_requires_duty_mode",
                                    "io",
                                    "str",
                                    "soft",
                                )
                            ],
                        ),
                        *_checkin_same_day_class_remediations(),
                    ],
                )
            )
    return items


def _duty_joint_male_total_items(
    effective: dict[str, Any],
    checkin_cfg: dict[str, Any],
    duty_joint_cfg: dict[str, Any],
    head_pool: dict[str, Any],
    night_days: list[str],
    day_rule_tables: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    day_cfg = effective.get("day", {}) if isinstance(effective.get("day"), dict) else {}
    noon_cfg = day_cfg.get("noon_dorm_duty", {}) if isinstance(day_cfg.get("noon_dorm_duty"), dict) else {}
    if not _cfg_bool(noon_cfg, "enabled", True):
        return []

    mode = str(duty_joint_cfg.get("male_total_target_mode", "hard")).strip().lower()
    if mode not in {"hard", "soft"}:
        mode = "hard"
    target = max(0, _to_int(duty_joint_cfg.get("male_total_target"), 2))
    excluded = set(_as_str_list(duty_joint_cfg.get("male_total_eq2_exclude_teachers")))
    male_heads = [name for name in head_pool.get("male", []) if name not in excluded]
    if not male_heads:
        return []

    day_names = _day_rule_days(day_rule_tables)
    noon_male_demand = len([day for day in day_names if day != "星期日"])
    per_day = checkin_cfg.get("per_day", {}) if isinstance(checkin_cfg.get("per_day"), dict) else {}
    night_male_demand = max(0, _to_int(per_day.get("male"), 1)) * len(night_days)
    total_demand = noon_male_demand + night_male_demand
    hard_capacity = len(male_heads) * target
    evidence = [
        {"label": "男班主任名单", "value": _compact_names(male_heads), "tone": "info"},
        {"label": "午查男寝需求", "value": f"{noon_male_demand} 次（白天日历除星期日）", "tone": "info"},
        {"label": "晚查男寝需求", "value": f"{night_male_demand} 次（{len(night_days)} 天 × 每天男寝需求）", "tone": "info"},
        {"label": "目标容量", "value": f"{hard_capacity} 次 = {len(male_heads)} 人 × 目标 {target} 次/周", "tone": "warning" if total_demand > hard_capacity else "ok"},
    ]
    if mode == "hard" and total_demand != hard_capacity and not excluded:
        recommended_target = _ceil_div(total_demand, len(male_heads)) if male_heads else target
        return [
            _item(
                "error",
                "值班/查寝",
                "男班主任午查+晚查硬目标不可满足",
                f"男寝本周合计需求 {total_demand} 次，但当前硬目标只能容纳 {hard_capacity} 次。",
                "把男班主任总次数目标改为软约束，或提高目标次数/指定可超额教师后再启动 joint 求解。",
                blocking=True,
                evidence=evidence,
                remediations=[
                    _remediation(
                        "duty_joint.male_total_target_soft",
                        "把男班主任总次数目标改为软约束",
                        "保留人均2次目标，但允许少数男班主任承担第3次，并在诊断表中记录偏离罚分。",
                        "发布前需复核男班主任查寝负荷，确认多承担一次的教师可接受。",
                        [
                            _remediation_field(
                                "男班主任总次数目标模式",
                                "day.duty_joint_constraints.male_total_target_mode",
                                "io",
                                "str",
                                "soft",
                            ),
                            _remediation_field(
                                "男班主任目标偏离罚分",
                                "day.duty_joint_constraints.w_male_total_target_deviation",
                                "io",
                                "int",
                                2500,
                            ),
                        ],
                    ),
                    _remediation(
                        "duty_joint.male_total_target_raise",
                        f"把男班主任目标提高到 {recommended_target} 次",
                        "直接扩大硬目标容量，适合学校明确要求男班主任均摊更多查寝次数的场景。",
                        "所有男班主任都可能承担更多查寝，公平但负担更重。",
                        [
                            _remediation_field(
                                "男班主任周目标次数",
                                "day.duty_joint_constraints.male_total_target",
                                "io",
                                "int",
                                recommended_target,
                            )
                        ],
                    ),
                ],
            )
        ]
    if mode == "soft" and total_demand > hard_capacity:
        return [
            _item(
                "warning",
                "值班/查寝",
                "男班主任查寝目标需软化承接",
                f"男寝本周合计需求 {total_demand} 次，高于人均 {target} 次目标容量 {hard_capacity} 次。",
                "系统会继续求解，并把超过目标的男班主任记录为软约束复核项。",
                evidence=evidence,
            )
        ]
    return []


def _checkin_same_day_class_remediations(*, include_results_quick_action: bool = False) -> list[dict[str, Any]]:
    quick_actions = []
    if include_results_quick_action:
        quick_actions.append(
            {
                "id": "open_results",
                "label": "查看排障建议",
                "action": "activate_view",
                "view": "results",
            }
        )
    return [
        _remediation(
            "checkin.same_day_class_soft",
            "把晚查寝当天有课改为软约束",
            "保留晚查寝人数和周次数上限；若查寝教师当天没有晚自习课，系统继续出解，并在诊断表中记录高权重罚分。",
            "可能出现查寝教师当天没有晚自习课，发布前需由教务确认是否允许专门返校、宿管代查或人工调班。",
            [
                _remediation_field(
                    "晚查寝当天有课模式",
                    "checkin.require_teacher_has_class_that_day_mode",
                    "rules",
                    "str",
                    "soft",
                ),
                _remediation_field(
                    "当天无课查寝罚分",
                    "checkin.w_require_teacher_has_class_that_day",
                    "rules",
                    "int",
                    3000,
                ),
            ],
            quick_actions=quick_actions,
            decision_points=[
                {
                    "label": "推荐用途",
                    "value": "先恢复可行性，同时保留当天无晚自习查寝的风险记录。",
                    "tone": "info",
                },
                {
                    "label": "发布门禁",
                    "value": "若正式结果仍有当天无课查寝，结果页会要求教务确认后再发布。",
                    "tone": "warning",
                },
            ],
            checklist=[
                "先查看预演，确认同配置无解阻断项会被清除。",
                "应用后重新正式求解，检查是否生成课表文件。",
                "在结果页查看当天无晚自习查寝的教师、日期和罚分。",
                "发布前让教务主任或年级组确认这类查寝安排是否可接受。",
            ],
        ),
        _remediation(
            "checkin.same_day_class_off",
            "关闭晚查寝当天有课要求",
            "完全取消查寝教师当天必须有晚自习课的检查，只保留人数和周次数上限。",
            "该方案不会记录当天无课查寝风险，正式采用前应由学校明确确认。",
            [
                _remediation_field(
                    "晚查寝当天有课模式",
                    "checkin.require_teacher_has_class_that_day_mode",
                    "rules",
                    "str",
                    "off",
                )
            ],
            quick_actions=quick_actions,
            decision_points=[
                {
                    "label": "适用前提",
                    "value": "学校明确允许查寝教师当天不在晚自习岗，或另有宿管/值班干部承接。",
                    "tone": "warning",
                },
                {
                    "label": "审计风险",
                    "value": "关闭后不会产生当天无课查寝罚分，后续只能靠人工抽查。",
                    "tone": "error",
                },
            ],
            checklist=[
                "先由学校确认晚查寝不需要绑定当天晚自习任课。",
                "应用后重新正式求解，重点复核晚查寝表。",
                "把该口径记录进发布说明，避免后续按旧规则追责。",
            ],
        ),
    ]


def _checkin_capacity_items(
    checkin_cfg: dict[str, Any],
    head_pool: dict[str, Any],
    night_days: list[str],
) -> list[dict[str, Any]]:
    per_day = checkin_cfg.get("per_day", {}) if isinstance(checkin_cfg.get("per_day"), dict) else {}
    male_need = max(0, _to_int(per_day.get("male"), 1))
    female_need = max(0, _to_int(per_day.get("female"), 1))
    per_teacher_max = max(0, _to_int(checkin_cfg.get("per_teacher_max_times"), 1))
    exclude_heads = set(_as_str_list(checkin_cfg.get("exclude_heads")))
    male_heads = [name for name in head_pool["male"] if name not in exclude_heads]
    female_heads = [name for name in head_pool["female"] if name not in exclude_heads]
    days_count = len(night_days)
    rows = [
        ("男", male_need, male_heads),
        ("女", female_need, female_heads),
    ]
    evidence = _checkin_capacity_evidence(
        night_days=night_days,
        per_teacher_max=per_teacher_max,
        rows=rows,
        exclude_heads=exclude_heads,
    )
    items: list[dict[str, Any]] = []
    impossible: list[str] = []
    tight: list[str] = []
    missing_genders: list[str] = []
    shortfalls: list[dict[str, Any]] = []
    required_max_times = per_teacher_max
    for gender, need, heads in rows:
        demand = need * days_count
        capacity = len(heads) * per_teacher_max
        if demand > capacity:
            impossible.append(f"{gender}班主任需 {demand} 次，容量 {capacity} 次")
            missing_genders.append(gender)
            gap = demand - capacity
            shortfalls.append(
                {
                    "gender": gender,
                    "demand": demand,
                    "capacity": capacity,
                    "gap": gap,
                    "current_candidates": len(heads),
                    "candidates_needed": _ceil_div(gap, per_teacher_max) if per_teacher_max > 0 else demand,
                }
            )
            if heads:
                required_max_times = max(required_max_times, _ceil_div(demand, len(heads)))
        elif demand == capacity and demand > 0:
            tight.append(f"{gender}班主任 {len(heads)} 人刚好承担 {demand} 次")

    if impossible:
        items.append(
            _item(
                "error",
                "值班/查寝",
                "晚查寝候选人数不足",
                "；".join(impossible) + f"；晚查寝日期：{'、'.join(night_days)}。",
                "引入对应性别的新教师/宿管/行政值守人员作为额外候选，或降低每日查寝人数、提高每人周上限、调整晚查寝日期后再求解。",
                blocking=True,
                evidence=evidence,
                remediations=_checkin_capacity_remediations(
                    required_max_times=required_max_times,
                    current_max_times=per_teacher_max,
                    missing_genders=missing_genders,
                    shortfalls=shortfalls,
                ),
            )
        )
    elif tight:
        items.append(
            _item(
                "warning",
                "值班/查寝",
                "晚查寝候选池没有余量",
                "；".join(tight) + "，任何当天无晚自习或其他值班互斥都会导致无解。",
                "建议保留至少 1 人次余量，或把“查寝教师当天必须有晚自习”改为软约束后比较课表质量。",
                evidence=evidence,
            )
        )
    else:
        detail = (
            f"男班主任 {len(male_heads)} 人、女班主任 {len(female_heads)} 人；"
            f"每天需男 {male_need} 人、女 {female_need} 人，单人周上限 {per_teacher_max} 次。"
        )
        items.append(
            _item(
                "ok",
                "值班/查寝",
                "晚查寝候选容量可用",
                detail,
                "继续检查晚查寝与白天值班的联动余量。",
                evidence=evidence,
            )
        )
    return items


def _checkin_extra_head_quality_items(
    effective: dict[str, Any],
    rows: list[dict[str, Any]],
    checkin_cfg: dict[str, Any],
) -> list[dict[str, Any]]:
    extra_heads = checkin_cfg.get("extra_heads") if isinstance(checkin_cfg.get("extra_heads"), list) else []
    if not extra_heads:
        return []

    _class_col, head_col, gender_col = _head_teacher_columns(effective)
    known_head_genders = _known_head_genders(rows, head_col=head_col, gender_col=gender_col)
    exclude_heads = set(_as_str_list(checkin_cfg.get("exclude_heads")))
    seen_pairs: Counter[tuple[str, str]] = Counter()
    extra_genders_by_name: dict[str, set[str]] = {}

    blank_names: list[str] = []
    missing_gender: list[str] = []
    invalid_gender: list[str] = []
    excluded_names: list[str] = []
    duplicate_head_names: list[str] = []
    known_gender_conflicts: list[str] = []

    for index, raw in enumerate(extra_heads, start=1):
        if not isinstance(raw, dict):
            blank_names.append(f"第{index}项格式无效")
            continue
        name = str(raw.get("name") or "").strip()
        gender = str(raw.get("gender") or "").strip()
        if not name:
            blank_names.append(f"第{index}项缺少姓名")
            continue
        if not gender:
            missing_gender.append(name)
            continue
        if gender not in {"男", "女"}:
            invalid_gender.append(f"{name}({gender})")
            continue

        seen_pairs[(name, gender)] += 1
        extra_genders_by_name.setdefault(name, set()).add(gender)

        if name in exclude_heads:
            excluded_names.append(name)

        known_genders = known_head_genders.get(name, set())
        if gender in known_genders:
            duplicate_head_names.append(f"{name}({gender})")
        elif known_genders:
            known_gender_conflicts.append(f"{name}: 教师定位表={'+'.join(sorted(known_genders))}, extra_heads={gender}")

    duplicate_pairs = [
        f"{name}({gender})×{count}"
        for (name, gender), count in sorted(seen_pairs.items())
        if count > 1
    ]
    extra_gender_conflicts = [
        f"{name}: {'+'.join(sorted(genders))}"
        for name, genders in sorted(extra_genders_by_name.items())
        if len(genders) > 1
    ]
    conflict_fragments = known_gender_conflicts + extra_gender_conflicts
    items: list[dict[str, Any]] = []
    if conflict_fragments:
        items.append(
            _item(
                "error",
                "值班/查寝",
                "额外晚查寝候选性别冲突",
                "；".join(conflict_fragments[:8]),
                "先统一教师定位表和 checkin.extra_heads 中的性别口径，避免同一教师被同时放入男女查寝候选池。",
                blocking=True,
                publish_blocking=True,
                evidence=[
                    {"label": "冲突候选", "value": "；".join(conflict_fragments[:8]), "tone": "error"},
                    {"label": "配置位置", "value": "rules.checkin.extra_heads", "tone": "info"},
                ],
                remediations=[_checkin_extra_heads_review_remediation()],
            )
        )

    warning_fragments: list[str] = []
    if blank_names:
        warning_fragments.append("格式无效：" + "、".join(blank_names[:6]))
    if missing_gender:
        warning_fragments.append("缺少性别：" + _compact_names(sorted(dict.fromkeys(missing_gender))))
    if invalid_gender:
        warning_fragments.append("性别值无效：" + "、".join(invalid_gender[:6]))
    if duplicate_pairs:
        warning_fragments.append("重复配置：" + "、".join(duplicate_pairs[:6]))
    if duplicate_head_names:
        warning_fragments.append("已是班主任候选：" + "、".join(sorted(dict.fromkeys(duplicate_head_names))[:6]))
    if excluded_names:
        warning_fragments.append("同时在排除名单：" + _compact_names(sorted(dict.fromkeys(excluded_names))))

    if warning_fragments:
        items.append(
            _item(
                "warning",
                "值班/查寝",
                "额外晚查寝候选需复核",
                "；".join(warning_fragments),
                "清理重复项、补齐性别，并确认候选人没有同时出现在排除名单中；否则这些候选可能不会真正增加排课容量。",
                evidence=[
                    {"label": "配置条目", "value": f"{len(extra_heads)} 条", "tone": "info"},
                    {"label": "复核问题", "value": "；".join(warning_fragments[:5]), "tone": "warning"},
                ],
                remediations=[_checkin_extra_heads_review_remediation()],
            )
        )
    elif not conflict_fragments:
        items.append(
            _item(
                "ok",
                "值班/查寝",
                "额外晚查寝候选配置可用",
                f"已识别 {len(extra_genders_by_name)} 名额外候选，姓名和性别格式通过基础校验。",
                "继续结合容量和发布评估复核候选是否具备真实查寝资格。",
                evidence=[
                    {"label": "额外候选", "value": _compact_names(sorted(extra_genders_by_name)), "tone": "ok"},
                ],
            )
        )
    return items


def _known_head_genders(rows: list[dict[str, Any]], *, head_col: str, gender_col: str) -> dict[str, set[str]]:
    genders: dict[str, set[str]] = {}
    for row in rows:
        name = str(row.get(head_col) or "").strip()
        gender = str(row.get(gender_col) or "").strip()
        if name and gender in {"男", "女"}:
            genders.setdefault(name, set()).add(gender)
    return genders


def _checkin_capacity_evidence(
    *,
    night_days: list[str],
    per_teacher_max: int,
    rows: list[tuple[str, int, list[str]]],
    exclude_heads: set[str],
) -> list[dict[str, str]]:
    days_count = len(night_days)
    evidence = [
        {
            "label": "晚查寝日期",
            "value": f"{days_count} 天：{'、'.join(night_days) or '未配置'}",
            "tone": "info",
        },
        {
            "label": "单人周上限",
            "value": f"{per_teacher_max} 次/周",
            "tone": "info",
        },
    ]
    for gender, need, heads in rows:
        demand = need * days_count
        capacity = len(heads) * per_teacher_max
        gap = max(0, demand - capacity)
        if demand > capacity:
            tone = "error"
        elif demand == capacity and demand > 0:
            tone = "warning"
        else:
            tone = "ok"
        evidence.extend(
            [
                {
                    "label": f"{gender}班主任供需",
                    "value": (
                        f"需求 {demand} 次 = 每天 {need} 人 × {days_count} 天；"
                        f"容量 {capacity} 次 = 候选 {len(heads)} 人 × {per_teacher_max} 次/周；"
                        f"缺口 {gap} 次"
                    ),
                    "tone": tone,
                },
                {
                    "label": f"{gender}候选名单",
                    "value": _compact_names(heads) or "无",
                    "tone": "info" if heads else "warning",
                },
            ]
        )
    if exclude_heads:
        evidence.append(
            {
                "label": "已排除名单",
                "value": _compact_names(sorted(exclude_heads)),
                "tone": "warning",
            }
        )
    return evidence


def _head_duty_shape_items(
    effective: dict[str, Any],
    rows: list[dict[str, Any]],
    day_rule_tables: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    if not rows:
        return []
    items: list[dict[str, Any]] = []
    head_rows = _head_class_rows(effective, rows)
    if not head_rows:
        return []

    day_names = _day_rule_days(day_rule_tables)
    required_days = set(ALL_DAYS)
    if day_names and set(day_names) != required_days:
        items.append(
            _item(
                "error",
                "值班/查寝",
                "班主任值班需要完整7天白天日历",
                f"当前白天日历为：{'、'.join(day_names)}。",
                "下午课前值班模块包含周六固定规则和周一到周日楼层覆盖，需要白天时间格子包含完整一周。",
                blocking=True,
            )
        )

    class9_heads = [item["head"] for item in head_rows if item["class_no"] == 9]
    if len(class9_heads) != 1:
        items.append(
            _item(
                "error",
                "值班/查寝",
                "班主任值班缺少唯一9班班主任",
                f"当前识别到 {len(class9_heads)} 位：{'、'.join(class9_heads) or '无'}。",
                "补齐且只保留一个9班班主任；当前值班规则把9班并入5F轮值，缺失会导致模型不可构建。",
                blocking=True,
            )
        )

    h4_base = [item["head"] for item in head_rows if _duty_floor_for_class(item["class_no"]) == "4F"]
    h5_merged = [item["head"] for item in head_rows if _duty_floor_for_class(item["class_no"]) == "5F"]
    h5_base = [item["head"] for item in head_rows if _teaching_floor_for_class(item["class_no"]) == "5F"]
    h3 = [item["head"] for item in head_rows if _duty_floor_for_class(item["class_no"]) == "3F"]
    shape_errors: list[str] = []
    if len(h4_base) + 1 != 7:
        shape_errors.append(f"4F基础候选 {len(h4_base)} 人，计入5F借调后应为7人")
    if len(h5_merged) - 1 != 7:
        shape_errors.append(f"5F合并候选 {len(h5_merged)} 人，扣除一次借调后应为7人")
    if len(h5_base) != 7:
        shape_errors.append(f"1-7班教学楼层候选 {len(h5_base)} 人，应为7人")
    if len(h3) < 3:
        shape_errors.append(f"3F候选 {len(h3)} 人，当前规则要求非周六每人至少覆盖多次")
    if shape_errors:
        items.append(
            _item(
                "error",
                "值班/查寝",
                "班主任楼层值班候选结构不匹配",
                "；".join(shape_errors) + "。",
                "按当前模型口径核对1-17班、班主任姓名和9班楼层归并规则；候选结构不匹配时不要直接启动长时间求解。",
                blocking=True,
            )
        )
    elif class9_heads:
        items.append(
            _item(
                "ok",
                "值班/查寝",
                "班主任楼层值班结构可建模",
                f"3F {len(h3)} 人、4F基础 {len(h4_base)} 人、5F基础 {len(h5_base)} 人，9班班主任：{class9_heads[0]}。",
                "继续关注与晚查寝、午查寝、PM1同日绑定的组合可行性。",
            )
        )
    return items


def _conflict_items(conflict_payload: dict[str, Any]) -> list[dict[str, Any]]:
    summary = conflict_payload.get("summary", {}) if isinstance(conflict_payload, dict) else {}
    errors = int(summary.get("errors") or 0)
    warnings = int(summary.get("warnings") or 0)
    total = int(summary.get("total") or 0)
    if errors:
        return [
            _item(
                "error",
                "规则冲突",
                "存在确定不可行的规则组合",
                f"冲突检测发现 {errors} 个错误级确定冲突。",
                "先进入“冲突检测”，按建议放宽或删除互斥规则。",
                blocking=True,
            )
        ]
    if warnings:
        return [
            _item(
                "warning",
                "规则冲突",
                "存在规则冲突警告",
                f"冲突检测发现 {warnings} 个警告。",
                "建议先处理警告，再启动长时间求解。",
            )
        ]
    return [_item("ok", "规则冲突", "未发现确定冲突", f"已完成确定性冲突检测，共 {total} 条。", "可以进入求解参数确认。")]


def _academic_items(
    academic_payload: dict[str, Any],
    effective: dict[str, Any] | None = None,
    teacher_rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    summary = academic_payload.get("summary", {}) if isinstance(academic_payload, dict) else {}
    risks = summary.get("risks") if isinstance(summary, dict) else []
    if not isinstance(risks, list):
        risks = []
    items = list(_academic_leave_log_substitution_items(academic_payload, effective or {}, teacher_rows or []))
    errors = [risk for risk in risks if isinstance(risk, dict) and risk.get("severity") == "error"]
    warnings = [risk for risk in risks if isinstance(risk, dict) and risk.get("severity") == "warning"]
    if errors:
        titles = "、".join(str(risk.get("title") or "错误级风险") for risk in errors[:5])
        items.append(
            _item(
                "error",
                "教务风险",
                "教务工作台存在错误级风险",
                titles,
                "发布或交付课表前处理教师冲突、请假冲突、场地冲突或人数不足。",
                publish_blocking=True,
            )
        )
        return items
    if warnings:
        items.append(
            _item(
                "warning",
                "教务风险",
                "教务工作台存在风险提示",
                f"当前有 {len(warnings)} 条教务警告。",
                "建议下载前清空待审批、补齐字段并分散教师负荷。",
            )
        )
        return items
    if items:
        return items
    health = (summary.get("metrics") or {}).get("health_score", 100) if isinstance(summary, dict) else 100
    return [_item("ok", "教务风险", "教务工作台风险较干净", f"健康分 {health}。", "后续可继续补充真实业务数据做压力验证。")]


def _academic_leave_log_substitution_items(
    academic_payload: dict[str, Any],
    effective: dict[str, Any],
    teacher_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    data = academic_payload.get("data") if isinstance(academic_payload, dict) else {}
    tables = data.get("tables") if isinstance(data, dict) else {}
    leave_rows = tables.get("teacher_leave") if isinstance(tables, dict) else []
    if not isinstance(leave_rows, list):
        return []

    assignments = _teacher_subject_assignments(effective, teacher_rows)
    evidence: list[dict[str, Any]] = []
    for row in leave_rows:
        if not isinstance(row, dict):
            continue
        teacher = str(row.get("教师") or "").strip()
        day = str(row.get("星期") or "").strip()
        status = str(row.get("状态") or "").strip()
        slot = str(row.get("时段") or "").strip()
        if not teacher or not day or not _is_confirmed_leave_status(status):
            continue
        suggestions = _leave_substitute_suggestions(teacher, assignments)
        if not suggestions:
            continue
        same_grade = suggestions.get("same_grade") or []
        other_grade = suggestions.get("other_grade") or []
        subject = str(suggestions.get("subject") or "任教学科")
        value = (
            f"{subject}；同年级同学科：{_compact_candidate_labels(same_grade) or '暂无'}；"
            f"非同年级同学科：{_compact_candidate_labels(other_grade) or '暂无'}"
        )
        evidence.append({"label": f"{teacher} {day} {slot or '全天'}", "value": value, "tone": "warning"})
    if not evidence:
        return []

    return [
        _item(
            "warning",
            "教务风险",
            "请假日志代课建议",
            f"教务日志中有 {len(evidence)} 条已审批/确认请假可根据教师定位表生成代课候选。",
            "优先安排同年级同学科教师代课；同年级无人可用时，再复核非同年级同学科教师。",
            evidence=evidence[:8],
            remediations=[
                _remediation(
                    "academic.review_leave_log_substitutes",
                    "复核请假日志代课候选",
                    "按教师定位表给出同年级同学科、非同年级同学科两级候选，供教务手动确认代课或调课。",
                    "系统先给建议，不自动写入硬禁排；确认代课教师后可在教务工作台生成局部最小影响调课并留痕。",
                    [],
                    manual_hint="进入教务工作台的请假日志局部调课工具，按候选教师生成局部方案；必要时打开教师定位表核对任课范围。",
                    quick_actions=[
                        {"id": "open_academic_affairs", "label": "打开教务工作台", "action": "activate_view", "view": "academic"},
                        {"id": "open_teacher_table", "label": "打开教师定位表", "action": "activate_view", "view": "teachers"},
                    ],
                    decision_points=[
                        {"label": "优先级", "value": "同年级同学科优先，其次非同年级同学科。", "tone": "info"},
                        {"label": "责任边界", "value": "请假日志只记录事件，不自动写入硬禁排；局部调课只更新确认后的调整版全局课表。", "tone": "warning"},
                    ],
                    checklist=[
                        "确认请假单状态、日期和节次。",
                        "联系候选教师确认是否可代课。",
                        "应用局部调课版全局课表后，把最终代课安排同步到调课变更表或校内 OA。",
                    ],
                )
            ],
        )
    ]


def _is_confirmed_leave_status(status: str) -> bool:
    text = str(status or "").strip()
    return text in {"已审批", "已确认", "已通过", "已批准", "批准", "通过", "生效", "已生效"}


def _teacher_subject_assignments(effective: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    teacher_cfg = effective.get("teacher_table", {}) if isinstance(effective, dict) else {}
    columns = teacher_cfg.get("columns", {}) if isinstance(teacher_cfg, dict) else {}
    class_col = str(columns.get("class") or "班级")
    head_col = str(columns.get("head") or "班主任")
    head_gender_col = str(columns.get("head_gender") or "班主任性别")
    evening = effective.get("evening", {}) if isinstance(effective, dict) else {}
    configured_subjects = _as_str_list(evening.get("subjects"))
    available_subjects = sorted(
        {
            key
            for row in rows
            for key in teacher_subject_columns(
                row.keys(),
                class_col=class_col,
                head_col=head_col,
                gender_col=head_gender_col,
            )
        }
    )
    subjects = configured_subjects or available_subjects
    assignments: list[dict[str, str]] = []
    for row in rows:
        class_name = str(row.get(class_col) or "").strip()
        grade = _grade_key(class_name)
        for subject in subjects:
            teacher = str(row.get(subject) or "").strip()
            if not teacher:
                continue
            assignments.append({"teacher": teacher, "subject": subject, "class": class_name, "grade": grade})
    return assignments


def _leave_substitute_suggestions(teacher: str, assignments: list[dict[str, str]]) -> dict[str, Any] | None:
    own = [item for item in assignments if item.get("teacher") == teacher]
    if not own:
        return None
    subject = str(own[0].get("subject") or "")
    grades = {str(item.get("grade") or "") for item in own if item.get("grade")}
    same_grade = []
    other_grade = []
    for item in assignments:
        if item.get("teacher") == teacher or item.get("subject") != subject:
            continue
        if item.get("grade") and item.get("grade") in grades:
            same_grade.append(item)
        else:
            other_grade.append(item)
    return {
        "subject": subject,
        "same_grade": _unique_candidate_assignments(same_grade),
        "other_grade": _unique_candidate_assignments(other_grade),
    }


def _unique_candidate_assignments(assignments: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for item in assignments:
        key = f"{item.get('teacher')}|{item.get('class')}"
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out[:6]


def _compact_candidate_labels(assignments: list[dict[str, str]], limit: int = 4) -> str:
    labels = []
    for item in assignments[:limit]:
        teacher = str(item.get("teacher") or "").strip()
        class_name = str(item.get("class") or "").strip()
        labels.append(f"{teacher}（{class_name}）" if class_name else teacher)
    if len(assignments) > limit:
        labels.append(f"等 {len(assignments)} 人")
    return "、".join(label for label in labels if label)


def _grade_key(class_name: str) -> str:
    text = str(class_name or "").strip()
    patterns = [
        r"(初[一二三123])",
        r"(高[一二三123])",
        r"([七八九]年级)",
        r"([一二三四五六]年级)",
        r"(\d+年级)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return ""


def _summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    errors = sum(1 for item in items if item["severity"] == "error")
    warnings = sum(1 for item in items if item["severity"] == "warning")
    blocking_errors = sum(1 for item in items if item["severity"] == "error" and item.get("blocking"))
    publish_blocking_errors = sum(1 for item in items if item["severity"] == "error" and item.get("publish_blocking"))
    if blocking_errors:
        status = "blocked"
        label = "需处理后再求解"
        message = f"有 {blocking_errors} 个求解阻断项。"
    elif errors or warnings:
        status = "ready"
        label = "可求解，含风险提示"
        message = f"求解可启动，但仍有 {errors} 个错误级发布风险、{warnings} 个警告。"
    else:
        status = "ready"
        label = "可启动求解"
        message = "基础数据、规则冲突和教务风险均未发现阻断项。"
    return {
        "status": status,
        "status_label": label,
        "message": message,
        "errors": errors,
        "warnings": warnings,
        "blocking_errors": blocking_errors,
        "publish_blocking_errors": publish_blocking_errors,
        "can_start_solver": blocking_errors == 0,
        "can_publish": errors == 0,
    }


def _stages(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_domain: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        by_domain.setdefault(item["domain"], []).append(item)
    stages = []
    for domain in DOMAIN_ORDER:
        rows = by_domain.get(domain, [])
        if not rows:
            continue
        severity = max((row["severity"] for row in rows), key=lambda value: SEVERITY_ORDER.get(value, 0))
        stages.append(
            {
                "domain": domain,
                "severity": severity,
                "errors": sum(1 for row in rows if row["severity"] == "error"),
                "warnings": sum(1 for row in rows if row["severity"] == "warning"),
                "total": len(rows),
            }
        )
    return stages


def _next_actions(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(items, key=lambda item: (-SEVERITY_ORDER.get(item["severity"], 0), not bool(item.get("blocking"))))
    return [
        {
            "title": item["title"],
            "domain": item["domain"],
            "severity": item["severity"],
            "suggestion": item["suggestion"],
        }
        for item in ordered
        if item["severity"] in {"error", "warning"}
    ][:5]


def _remediation_options(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        for option in item.get("remediation_options") or []:
            if not isinstance(option, dict):
                continue
            option_id = str(option.get("id") or "").strip()
            if not option_id or option_id in seen:
                continue
            seen.add(option_id)
            options.append(option)
    return options[:6]


def _metrics(
    config_payload: dict[str, Any],
    teacher_rows: list[dict[str, Any]],
    day_rule_tables: dict[str, list[dict[str, Any]]],
    academic_payload: dict[str, Any],
    conflict_payload: dict[str, Any],
) -> dict[str, Any]:
    groups = config_payload.get("business_rule_groups", []) if isinstance(config_payload, dict) else []
    rule_count = sum(len(group.get("rules", []) or []) for group in groups if isinstance(group, dict))
    academic_summary = academic_payload.get("summary", {}) if isinstance(academic_payload, dict) else {}
    academic_metrics = academic_summary.get("metrics", {}) if isinstance(academic_summary, dict) else {}
    conflict_summary = conflict_payload.get("summary", {}) if isinstance(conflict_payload, dict) else {}
    return {
        "teacher_rows": len(teacher_rows),
        "teacher_data_quality": _teacher_data_quality(config_payload, teacher_rows),
        "day_rule_rows": {key: len(value or []) for key, value in day_rule_tables.items()},
        "business_rules": rule_count,
        "conflict_errors": int(conflict_summary.get("errors") or 0),
        "conflict_warnings": int(conflict_summary.get("warnings") or 0),
        "academic_risks": len(academic_summary.get("risks") or []) if isinstance(academic_summary, dict) else 0,
        "academic_health_score": academic_metrics.get("health_score", 100),
    }


def _teacher_data_quality(config_payload: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    effective = config_payload.get("effective", {}) if isinstance(config_payload, dict) else {}
    teacher_cfg = effective.get("teacher_table", {}) if isinstance(effective, dict) else {}
    columns = teacher_cfg.get("columns", {}) if isinstance(teacher_cfg, dict) else {}
    class_col = str(columns.get("class") or "班级")
    head_col = str(columns.get("head") or "班主任")
    head_gender_col = str(columns.get("head_gender") or "班主任性别")
    evening = effective.get("evening", {}) if isinstance(effective, dict) else {}
    available_columns = sorted({key for row in rows for key in row if key != "row_index"})
    subject_columns = sorted(
        {
            key
            for row in rows
            for key in teacher_subject_columns(
                row.keys(),
                class_col=class_col,
                head_col=head_col,
                gender_col=head_gender_col,
            )
        }
    )
    configured_subjects = _as_str_list(evening.get("subjects"))
    subjects = configured_subjects or subject_columns
    missing_subject_columns = [subject for subject in subjects if subject not in available_columns]
    subject_coverage = []
    for subject in subjects:
        if subject not in available_columns:
            subject_coverage.append(
                {
                    "subject": subject,
                    "present": False,
                    "filled": 0,
                    "total": len(rows),
                    "missing": len(rows),
                    "coverage_pct": 0,
                }
            )
            continue
        filled = sum(1 for row in rows if str(row.get(subject) or "").strip())
        total = len(rows)
        subject_coverage.append(
            {
                "subject": subject,
                "present": True,
                "filled": filled,
                "total": total,
                "missing": max(0, total - filled),
                "coverage_pct": round((filled / total) * 100) if total else 0,
            }
        )
    head_filled = sum(1 for row in rows if str(row.get(head_col) or "").strip())
    head_gender_filled = sum(1 for row in rows if str(row.get(head_gender_col) or "").strip())
    row_issues = _teacher_row_issues(
        rows,
        class_col=class_col,
        head_col=head_col,
        head_gender_col=head_gender_col,
        subjects=subjects,
        available_columns=available_columns,
    )
    return {
        "columns": available_columns,
        "class_column": class_col,
        "required_subjects": subjects,
        "missing_subject_columns": missing_subject_columns,
        "issue_rows": len(row_issues),
        "missing_subject_cells": sum(len(issue.get("missing_subjects") or []) for issue in row_issues),
        "row_issues": row_issues,
        "head_teacher": {
            "column": head_col,
            "filled": head_filled,
            "total": len(rows),
            "coverage_pct": round((head_filled / len(rows)) * 100) if rows else 0,
        },
        "head_gender": {
            "column": head_gender_col,
            "filled": head_gender_filled,
            "total": len(rows),
            "coverage_pct": round((head_gender_filled / len(rows)) * 100) if rows else 0,
        },
        "subject_coverage": subject_coverage,
    }


def _teacher_row_issues(
    rows: list[dict[str, Any]],
    *,
    class_col: str,
    head_col: str,
    head_gender_col: str,
    subjects: list[str],
    available_columns: list[str],
) -> list[dict[str, Any]]:
    available = set(available_columns)
    issues: list[dict[str, Any]] = []
    for display_index, row in enumerate(rows, start=1):
        # 班主任及性别是值班/查寝元数据，不是课程排课的必填字段。
        missing_fields = [class_col] if not str(row.get(class_col) or "").strip() else []
        missing_subjects = [
            subject
            for subject in subjects
            if subject in available and not str(row.get(subject) or "").strip()
        ]
        missing_columns = [subject for subject in subjects if subject not in available]
        present_subjects = [subject for subject in subjects if subject in available]
        has_any_subject_teacher = any(str(row.get(subject) or "").strip() for subject in present_subjects)
        if not missing_fields and not missing_subjects and not missing_columns and has_any_subject_teacher:
            continue
        issue_count = len(missing_fields) + len(missing_subjects) + len(missing_columns)
        if not has_any_subject_teacher:
            issue_count += 1
        issues.append(
            {
                "row_number": display_index,
                "row_index": row.get("row_index", display_index - 1),
                "class_name": str(row.get(class_col) or "").strip() or f"第{display_index}行",
                "missing_fields": missing_fields,
                "missing_subjects": missing_subjects,
                "missing_columns": missing_columns,
                "has_any_subject_teacher": has_any_subject_teacher,
                "issue_count": issue_count,
            }
        )
    return issues


def _item(
    severity: str,
    domain: str,
    title: str,
    detail: str,
    suggestion: str,
    *,
    blocking: bool = False,
    publish_blocking: bool = False,
    evidence: list[dict[str, Any]] | None = None,
    remediations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "severity": severity,
        "domain": domain,
        "title": title,
        "detail": detail,
        "suggestion": suggestion,
        "blocking": bool(blocking),
        "publish_blocking": bool(publish_blocking),
        "evidence": evidence or [],
        "remediation_options": remediations or [],
    }


def _compact_names(names: list[str], limit: int = 12) -> str:
    cleaned = [str(name).strip() for name in names if str(name).strip()]
    if not cleaned:
        return ""
    if len(cleaned) <= limit:
        return "、".join(cleaned)
    return f"{'、'.join(cleaned[:limit])} 等 {len(cleaned)} 人"


def _checkin_capacity_remediations(
    *,
    required_max_times: int,
    current_max_times: int,
    missing_genders: list[str],
    shortfalls: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    shortfall_text = _shortfall_text(shortfalls)
    if required_max_times > current_max_times:
        options.append(
            _remediation(
                "checkin.raise_weekly_max",
                f"把晚查寝周上限调到 {required_max_times} 次",
                "用现有班主任池补足查寝人次，是最小配置改动。",
                "会增加少数班主任晚查寝次数，发布前需复核教师负荷。",
                [
                    _remediation_field(
                        "班主任每周最大晚查寝次数",
                        "checkin.per_teacher_max_times",
                        "rules",
                        "int",
                        required_max_times,
                    )
                ],
                decision_points=[
                    {
                        "label": "容量变化",
                        "value": _weekly_max_capacity_text(shortfalls, current_max_times, required_max_times),
                        "tone": "info",
                    },
                    {
                        "label": "审批关注",
                        "value": "属于负荷规则放宽，建议由年级组或教务主任确认后应用。",
                        "tone": "warning",
                    },
                ],
                checklist=[
                    "查看预演是否清除求解阻断项。",
                    "确认候选班主任接受单周多次晚查寝。",
                    "应用后重新正式求解，并在结果页复核教师负荷。",
                ],
            )
        )
    gender_label = "、".join(missing_genders) or "对应性别"
    options.append(
        _remediation(
            "checkin.add_gender_candidate",
            f"引入{gender_label}晚查寝候选人",
            f"{shortfall_text}当前是可用人数不足；在教师定位表补齐对应性别班主任，或在 checkin.extra_heads 增加新教师/宿管/行政值守人员。",
            "需要教务确认候选人资格，系统不能自动代填姓名。",
            [],
            manual_hint="进入教师定位表补充班主任性别，或在规则配置里维护 checkin.extra_heads；不要只在现有候选池里反复调整。",
            quick_actions=[
                {
                    "id": "open_teacher_table",
                    "label": "打开教师定位表",
                    "action": "activate_view",
                    "view": "teachers",
                },
                {
                    "id": "open_extra_heads_rule",
                    "label": "维护额外候选人",
                    "action": "open_rule_editor",
                    "view": "rules",
                    "rule_id": "duty.night_checkin.extra_heads",
                    "search": "额外晚查寝候选人",
                },
            ],
            decision_points=[
                {
                    "label": "最少补充",
                    "value": shortfall_text.strip("；") or "至少补充对应性别候选人。",
                    "tone": "error",
                },
                {
                    "label": "配置位置",
                    "value": "班主任走教师定位表；新教师、宿管或行政值守人员走 checkin.extra_heads。",
                    "tone": "info",
                },
            ],
            checklist=[
                "确认新增候选人的姓名、性别和查寝资格。",
                "在教师定位表补齐班主任性别，或在规则配置中维护 extra_heads 新候选。",
                "刷新求解前校验，确认晚查寝容量缺口变为 0。",
            ],
        )
    )
    return options


def _checkin_extra_heads_review_remediation() -> dict[str, Any]:
    return _remediation(
        "checkin.extra_heads_review",
        "复核额外晚查寝候选",
        "清理额外候选中的重复姓名、无效性别、性别冲突和排除名单冲突。",
        "候选配置错误会让系统高估或低估可用查寝人力，严重时会把同一教师放进男女两个候选池。",
        [],
        manual_hint="在规则总览打开“额外晚查寝候选人”，逐项确认姓名、性别和查寝资格。",
        quick_actions=[
            {
                "id": "open_extra_heads_rule",
                "label": "维护额外候选人",
                "action": "open_rule_editor",
                "view": "rules",
                "rule_id": "duty.night_checkin.extra_heads",
                "search": "额外晚查寝候选人",
            },
            {
                "id": "open_teacher_table",
                "label": "核对教师定位表",
                "action": "activate_view",
                "view": "teachers",
            },
        ],
        decision_points=[
            {
                "label": "性别口径",
                "value": "同一姓名只能进入一个性别候选池；若教师定位表已有性别，以教师定位表为准。",
                "tone": "error",
            },
            {
                "label": "排除名单",
                "value": "同时出现在 exclude_heads 的候选不会增加可用容量。",
                "tone": "warning",
            },
        ],
        checklist=[
            "删除重复或格式无效的候选。",
            "补齐每位额外候选的性别。",
            "确认候选没有同时在排除名单中。",
            "刷新求解前校验，确认候选容量和质量 gate 通过。",
        ],
    )


def _shortfall_text(shortfalls: list[dict[str, Any]]) -> str:
    fragments = []
    for item in shortfalls:
        gender = str(item.get("gender") or "对应性别")
        needed = int(item.get("candidates_needed") or 0)
        gap = int(item.get("gap") or 0)
        if needed > 0:
            fragments.append(f"至少补充{gender}候选 {needed} 人，可补足 {gap} 次缺口")
    return "；".join(fragments) + ("；" if fragments else "")


def _weekly_max_capacity_text(shortfalls: list[dict[str, Any]], current_max_times: int, required_max_times: int) -> str:
    fragments = []
    for item in shortfalls:
        gender = str(item.get("gender") or "对应性别")
        current_candidates = int(item.get("current_candidates") or 0)
        current_capacity = current_candidates * current_max_times
        new_capacity = current_candidates * required_max_times
        demand = int(item.get("demand") or 0)
        fragments.append(f"{gender}侧容量 {current_capacity} -> {new_capacity} 次，需求 {demand} 次")
    return "；".join(fragments) or f"周上限 {current_max_times} -> {required_max_times} 次"


def _remediation(
    option_id: str,
    title: str,
    detail: str,
    risk: str,
    fields: list[dict[str, Any]] | None = None,
    *,
    manual_hint: str = "",
    quick_actions: list[dict[str, Any]] | None = None,
    decision_points: list[dict[str, Any]] | None = None,
    checklist: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": option_id,
        "title": title,
        "detail": detail,
        "risk": risk,
        "fields": fields or [],
        "action_type": "configure" if fields else "manual",
        "manual_hint": manual_hint,
        "quick_actions": quick_actions or [],
        "decision_points": decision_points or [],
        "checklist": checklist or [],
    }


def _remediation_field(label: str, path: str, store: str, field_type: str, value: Any) -> dict[str, Any]:
    return {
        "label": label,
        "path": path,
        "store": store,
        "type": field_type,
        "value": value,
    }


def _ceil_div(numerator: int, denominator: int) -> int:
    if denominator <= 0:
        return 0
    return (numerator + denominator - 1) // denominator


def _row_has_positive_hours(row: dict[str, Any]) -> bool:
    for key, value in row.items():
        if str(key) in {"row_index", "学科"}:
            continue
        if _to_float(value) > 0:
            return True
    return False


def _to_float(value: Any) -> float:
    try:
        return float(str(value).strip())
    except Exception:
        return 0.0


def _to_int(value: Any, default: int = 0) -> int:
    try:
        text = str(value).strip()
        if not text:
            return int(default)
        return int(float(text))
    except Exception:
        return int(default)


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _head_duty_enabled(head_cfg: dict[str, Any]) -> bool:
    if "enable_head_duty" in head_cfg:
        return _cfg_bool(head_cfg, "enable_head_duty", True)
    return _cfg_bool(head_cfg, "enabled", True)


def _head_teacher_columns(effective: dict[str, Any]) -> tuple[str, str, str]:
    teacher_cfg = effective.get("teacher_table", {}) if isinstance(effective, dict) else {}
    columns = teacher_cfg.get("columns", {}) if isinstance(teacher_cfg, dict) else {}
    return (
        str(columns.get("class") or "班级"),
        str(columns.get("head") or "班主任"),
        str(columns.get("head_gender") or "班主任性别"),
    )


def _head_teacher_pool(effective: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    _class_col, head_col, gender_col = _head_teacher_columns(effective)
    male: list[str] = []
    female: list[str] = []
    for row in rows:
        name = str(row.get(head_col) or "").strip()
        gender = str(row.get(gender_col) or "").strip()
        if not name:
            continue
        if gender == "男":
            male.append(name)
        elif gender == "女":
            female.append(name)

    checkin_cfg = effective.get("checkin", {}) if isinstance(effective, dict) else {}
    extra_heads = checkin_cfg.get("extra_heads", []) if isinstance(checkin_cfg, dict) else []
    if isinstance(extra_heads, list):
        for item in extra_heads:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            gender = str(item.get("gender") or "").strip()
            if not name:
                continue
            if gender == "男":
                male.append(name)
            elif gender == "女":
                female.append(name)

    return {
        "male": sorted(dict.fromkeys(male)),
        "female": sorted(dict.fromkeys(female)),
    }


def _head_class_rows(effective: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    class_col, head_col, _gender_col = _head_teacher_columns(effective)
    out: list[dict[str, Any]] = []
    for row in rows:
        head = str(row.get(head_col) or "").strip()
        if not head:
            continue
        class_no = _parse_class_no(row.get(class_col))
        if class_no is None:
            continue
        out.append({"head": head, "class_no": class_no})
    return out


def _parse_class_no(value: Any) -> int | None:
    match = re.search(r"(\d+)", str(value or "").strip())
    if not match:
        return None
    try:
        return int(match.group(1))
    except Exception:
        return None


def _teaching_floor_for_class(class_no: int) -> str | None:
    if 1 <= class_no <= 7:
        return "5F"
    if 8 <= class_no <= 14:
        return "4F"
    if 15 <= class_no <= 17:
        return "3F"
    return None


def _duty_floor_for_class(class_no: int) -> str | None:
    if class_no == 9:
        return "5F"
    return _teaching_floor_for_class(class_no)


def _night_days(effective: dict[str, Any]) -> list[str]:
    calendar = effective.get("calendar", {}) if isinstance(effective, dict) else {}
    if isinstance(calendar, dict):
        days = _as_str_list(calendar.get("days"))
        if days:
            return days
    return list(DEFAULT_NIGHT_DAYS)


def _day_rule_days(tables: dict[str, list[dict[str, Any]]]) -> list[str]:
    explicit = tables.get("days") or []
    out = [str(row.get("day") or "").strip() for row in explicit if isinstance(row, dict) and str(row.get("day") or "").strip()]
    if out:
        return sorted(dict.fromkeys(out), key=_day_order)

    time_grid = tables.get("time_grid") or []
    found: set[str] = set()
    for row in time_grid:
        if not isinstance(row, dict):
            continue
        for key, value in row.items():
            day = str(key).strip()
            if day in DAY_NAME_SET and _to_float(value) > 0:
                found.add(day)
    return sorted(found, key=_day_order)


def _day_order(day: str) -> int:
    return day_rank(day)


def _cfg_bool(section: dict[str, Any], key: str, default: bool) -> bool:
    value = section.get(key, default)
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off", "否", "关闭"}
    return bool(value)


def _checkin_same_day_class_mode(checkin_cfg: dict[str, Any]) -> str:
    raw_mode = checkin_cfg.get("require_teacher_has_class_that_day_mode")
    if raw_mode is not None:
        mode = str(raw_mode or "").strip().lower()
        if mode in {"hard", "soft", "off"}:
            return mode
    return "hard" if _cfg_bool(checkin_cfg, "require_teacher_has_class_that_day", True) else "off"

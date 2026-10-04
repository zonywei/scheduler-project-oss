from __future__ import annotations

import argparse
import copy
import json
import re
import sys
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

QUALITY_GAP_REVIEW_KEY = "求解质量|可行解尚未证明全局最优"


@dataclass(frozen=True)
class AcceptanceCheck:
    id: str
    requirement: str
    artifacts: tuple[str, ...]
    status: str
    evidence: tuple[str, ...]
    gap: str = ""
    severity: str = "required"


def _rel(path: Path, repo_root: Path) -> str:
    return path.relative_to(repo_root).as_posix()


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8-sig")


def _all_exist(repo_root: Path, rel_paths: tuple[str, ...]) -> tuple[bool, tuple[str, ...]]:
    missing = [path for path in rel_paths if not (repo_root / path).exists()]
    return not missing, tuple(missing)


def _contains_all(text: str, needles: tuple[str, ...]) -> tuple[bool, tuple[str, ...]]:
    missing = [needle for needle in needles if needle not in text]
    return not missing, tuple(missing)


def _check_exists(
    repo_root: Path,
    *,
    check_id: str,
    requirement: str,
    artifacts: tuple[str, ...],
    evidence_when_ok: tuple[str, ...],
    severity: str = "required",
) -> AcceptanceCheck:
    ok, missing = _all_exist(repo_root, artifacts)
    if ok:
        return AcceptanceCheck(check_id, requirement, artifacts, "pass", evidence_when_ok, severity=severity)
    return AcceptanceCheck(
        check_id,
        requirement,
        artifacts,
        "fail",
        tuple(),
        gap=f"缺少文件：{', '.join(missing)}",
        severity=severity,
    )


def _latest_status(repo_root: Path, *, include_diagnostic: bool = True) -> dict[str, Any] | None:
    candidates = [
        path
        for path in (repo_root / "outputs" / "web_runs").glob("run_*/status.json")
        if path.is_file()
    ]
    if not candidates:
        return None
    fallback_error: dict[str, Any] | None = None
    for latest in sorted(candidates, key=_run_status_sort_key, reverse=True):
        try:
            payload = json.loads(latest.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            fallback_error = fallback_error or {"status_file": str(latest), "status_file_error": "unreadable"}
            continue
        if not isinstance(payload, dict):
            fallback_error = fallback_error or {"status_file": str(latest), "status_file_error": "not_object"}
            continue
        if not include_diagnostic and str(payload.get("run_purpose") or "") == "diagnostic_trial":
            continue
        payload.setdefault("status_file", str(latest))
        return payload
    if include_diagnostic:
        return fallback_error
    return _latest_status(repo_root, include_diagnostic=True)


def _run_status_sort_key(path: Path) -> tuple[str, float]:
    run_id = path.parent.name
    if re_match := re.fullmatch(r"run_(\d{8})_(\d{6})(?:_.+)?", run_id):
        return (f"{re_match.group(1)}{re_match.group(2)}", path.stat().st_mtime)
    return ("", path.stat().st_mtime)


def _status_for_recommended_candidate(
    status: dict[str, Any] | None,
    *,
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any] | None:
    if not isinstance(status, dict):
        return status
    recommendation = status.get("recommended_formal_candidate")
    working_status = status
    if not isinstance(recommendation, dict) or not recommendation:
        recommendation = _build_recommended_formal_candidate_for_audit(status, repo_root)
        if not recommendation:
            return status
        working_status = copy.deepcopy(status)
        working_status["recommended_formal_candidate"] = copy.deepcopy(recommendation)
    summary = recommendation.get("summary") if isinstance(recommendation.get("summary"), dict) else {}
    selected_run_id = str(summary.get("selected_run_id") or "").strip()
    current_run_id = str(summary.get("current_run_id") or working_status.get("run_id") or "").strip()
    if not selected_run_id or selected_run_id == current_run_id:
        return working_status
    candidate = recommendation.get("candidate") if isinstance(recommendation.get("candidate"), dict) else {}
    candidate_status_path = _recommended_candidate_status_path(candidate, selected_run_id=selected_run_id)
    if candidate_status_path is None:
        return working_status
    try:
        candidate_status = json.loads(candidate_status_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return working_status
    if not isinstance(candidate_status, dict):
        return working_status
    candidate_status.setdefault("status_file", str(candidate_status_path))
    _merge_latest_recommended_candidate_context(candidate_status, working_status, selected_run_id=selected_run_id)
    candidate_status["audit_latest_run_id"] = str(working_status.get("run_id") or "")
    candidate_status["audit_latest_status_file"] = str(working_status.get("status_file") or "")
    candidate_status["audit_candidate_selection"] = "recommended_formal_candidate"
    return candidate_status


def _build_recommended_formal_candidate_for_audit(status: dict[str, Any], repo_root: Path) -> dict[str, Any]:
    try:
        from scheduler.app.formal_run_history import build_recommended_formal_candidate

        recommendation = build_recommended_formal_candidate(status, repo_root)
    except Exception:
        return {}
    return recommendation if isinstance(recommendation, dict) else {}


def _merge_latest_recommended_candidate_context(
    candidate_status: dict[str, Any],
    latest_status: dict[str, Any],
    *,
    selected_run_id: str,
) -> None:
    recommendation = latest_status.get("recommended_formal_candidate")
    if isinstance(recommendation, dict):
        summary = recommendation.get("summary") if isinstance(recommendation.get("summary"), dict) else {}
        if str(summary.get("selected_run_id") or "").strip() == selected_run_id:
            candidate_status["recommended_formal_candidate"] = copy.deepcopy(recommendation)

    latest_diag = latest_status.get("solve_diagnostics")
    if not isinstance(latest_diag, dict):
        return
    latest_adjusted = latest_diag.get("business_floor_adjusted_quality")
    if not isinstance(latest_adjusted, dict) or not latest_adjusted:
        return
    if not _adjusted_quality_applies_to_candidate(latest_adjusted, candidate_status):
        return
    candidate_diag = candidate_status.get("solve_diagnostics")
    if not isinstance(candidate_diag, dict):
        candidate_diag = {}
        candidate_status["solve_diagnostics"] = candidate_diag
    candidate_diag["business_floor_adjusted_quality"] = copy.deepcopy(latest_adjusted)

    quality_plan = candidate_diag.get("quality_plan")
    if isinstance(quality_plan, dict):
        current = quality_plan.get("current")
        if isinstance(current, dict):
            current["business_floor_adjusted_quality"] = copy.deepcopy(latest_adjusted)


def _adjusted_quality_applies_to_candidate(adjusted: dict[str, Any], candidate_status: dict[str, Any]) -> bool:
    candidate_objective = _quality_float(candidate_status.get("objective_value"))
    adjusted_objective = _quality_float(adjusted.get("objective_value"))
    if (
        candidate_objective is not None
        and adjusted_objective is not None
        and not _quality_float_equal(candidate_objective, adjusted_objective)
    ):
        return False

    candidate_gap = _quality_float(candidate_status.get("objective_gap"))
    adjusted_raw_gap = _quality_float(adjusted.get("raw_objective_gap"))
    if candidate_gap is not None and adjusted_raw_gap is not None and adjusted_raw_gap > candidate_gap + 1e-6:
        return False

    candidate_bound = _quality_float(candidate_status.get("best_bound"))
    adjusted_bound = _quality_float(adjusted.get("best_bound"))
    if candidate_bound is not None and adjusted_bound is not None and adjusted_bound + 1e-6 < candidate_bound:
        return False

    return True


def _recommended_candidate_status_path(candidate: dict[str, Any], *, selected_run_id: str) -> Path | None:
    raw_status = str(candidate.get("status_file") or "").strip()
    if raw_status:
        path = Path(raw_status)
        if path.exists() and path.is_file():
            return path
    raw_dir = str(candidate.get("run_dir") or "").strip()
    if raw_dir:
        path = Path(raw_dir) / "status.json"
        if path.exists() and path.is_file():
            return path
    path = REPO_ROOT / "outputs" / "web_runs" / selected_run_id / "status.json"
    return path if path.exists() and path.is_file() else None


def _read_log_tail(status: dict[str, Any]) -> str:
    raw = status.get("log_file")
    if raw:
        path = Path(str(raw))
    else:
        run_dir = status.get("run_dir")
        path = Path(str(run_dir)) / "run.log" if run_dir else Path()
    if not path.exists() or not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[-6000:]
    except OSError:
        return ""


def _with_runtime_context(status: dict[str, Any]) -> dict[str, Any]:
    hydrated = copy.deepcopy(status)
    if not hydrated.get("log_tail"):
        tail = _read_log_tail(hydrated)
        if tail:
            hydrated["log_tail"] = tail
    mode = str(hydrated.get("mode") or "joint")
    if mode not in {"joint", "night"}:
        mode = "joint"
    try:
        from scheduler.app.config_service import build_effective_config_fingerprint

        current = build_effective_config_fingerprint(mode)
        hydrated["current_config_fingerprint"] = current
        run_hash = _fingerprint_hash(hydrated.get("config_fingerprint"))
        current_hash = _fingerprint_hash(current)
        if run_hash:
            matched = bool(current_hash and run_hash == current_hash)
            hydrated["config_fingerprint_match"] = matched
            hydrated["config_changed_after_run"] = not matched
            hydrated["config_freshness"] = {
                "status": "matched" if matched else "stale",
                "run_hash": run_hash,
                "current_hash": current_hash,
                "message": "当前配置与求解时一致。" if matched else "当前配置已在本批次求解后发生变化。",
            }
    except Exception:
        pass
    return hydrated


def _fingerprint_hash(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("hash") or "").strip()
    return str(value or "").strip()


def _publish_summary(status: dict[str, Any]) -> dict[str, Any]:
    publish = status.get("publish_assessment")
    publish_summary = publish.get("summary") if isinstance(publish, dict) else {}
    if isinstance(publish_summary, dict) and "can_publish" in publish_summary:
        return publish_summary
    try:
        from scheduler.app.publish_assessment import build_publish_assessment
        from scheduler.app.readiness import build_solve_readiness

        mode = str(status.get("mode") or "joint")
        readiness = build_solve_readiness(mode if mode in {"joint", "night"} else "joint")
        rebuilt = build_publish_assessment(status, readiness)
        summary = rebuilt.get("summary") if isinstance(rebuilt, dict) else {}
        return summary if isinstance(summary, dict) else {}
    except Exception:
        return {}


def _review_confirmed(status: dict[str, Any]) -> bool:
    publish = status.get("publish_assessment")
    confirmation = publish.get("review_confirmation") if isinstance(publish, dict) else {}
    return bool(confirmation.get("confirmed")) if isinstance(confirmation, dict) else False


def _business_floor_adjusted_quality(status: dict[str, Any]) -> dict[str, Any]:
    diagnostics = status.get("solve_diagnostics")
    if not isinstance(diagnostics, dict):
        return {}
    adjusted = diagnostics.get("business_floor_adjusted_quality")
    if isinstance(adjusted, dict) and adjusted:
        return adjusted
    quality_plan = diagnostics.get("quality_plan")
    if not isinstance(quality_plan, dict):
        return {}
    current = quality_plan.get("current")
    if not isinstance(current, dict):
        return {}
    adjusted = current.get("business_floor_adjusted_quality")
    return adjusted if isinstance(adjusted, dict) else {}


def _business_floor_gap_detail(status: dict[str, Any]) -> str:
    adjusted = _business_floor_adjusted_quality(status)
    if not adjusted:
        return ""
    parts: list[str] = []
    basis_gap = adjusted.get("basis_objective_gap")
    if basis_gap not in (None, ""):
        text = f"同配置更强证明界缺口 {basis_gap}"
        basis_percent = adjusted.get("basis_gap_percent")
        if basis_percent not in (None, ""):
            try:
                text += f"（约 {float(basis_percent):.2f}%）"
            except (TypeError, ValueError):
                pass
        parts.append(text)
    explained = adjusted.get("business_floor_gap_explained")
    if explained not in (None, ""):
        parts.append(f"业务下限已解释 {explained}")
    adjusted_gap = adjusted.get("adjusted_objective_gap")
    if adjusted_gap not in (None, ""):
        text = f"业务调整后剩余缺口 {adjusted_gap}"
        adjusted_percent = adjusted.get("adjusted_gap_percent")
        if adjusted_percent not in (None, ""):
            try:
                text += f"（约 {float(adjusted_percent):.2f}%）"
            except (TypeError, ValueError):
                pass
        parts.append(text)
    return "；".join(parts)


def _business_floor_quality_evidence(status: dict[str, Any]) -> tuple[str, ...]:
    adjusted = _business_floor_adjusted_quality(status)
    if not adjusted:
        return tuple()
    evidence: list[str] = []
    if "gap_basis" in adjusted:
        evidence.append(f"business_floor_gap_basis={adjusted.get('gap_basis')}")
    if "basis_objective_gap" in adjusted:
        evidence.append(f"business_floor_basis_gap={adjusted.get('basis_objective_gap')}")
    if "basis_gap_percent" in adjusted:
        evidence.append(f"business_floor_basis_gap_percent={adjusted.get('basis_gap_percent')}")
    proof = adjusted.get("stronger_bound_proof")
    if isinstance(proof, dict):
        if proof.get("run_id"):
            evidence.append(f"business_floor_proof_run={proof.get('run_id')}")
        if "best_bound" in proof:
            evidence.append(f"business_floor_proof_best_bound={proof.get('best_bound')}")
    if "business_floor_gap_explained" in adjusted:
        evidence.append(f"business_floor_gap_explained={adjusted.get('business_floor_gap_explained')}")
    if "adjusted_objective_gap" in adjusted:
        evidence.append(f"business_floor_adjusted_gap={adjusted.get('adjusted_objective_gap')}")
    if "adjusted_gap_percent" in adjusted:
        evidence.append(f"business_floor_adjusted_gap_percent={adjusted.get('adjusted_gap_percent')}")
    return tuple(evidence)


def _solver_quality_review_gap(status: dict[str, Any]) -> str:
    return ""


def _formal_run_comparison_evidence(status: dict[str, Any]) -> tuple[str, ...]:
    comparison = status.get("formal_run_comparison")
    if not isinstance(comparison, dict):
        return ("formal_run_comparison=-",)
    summary = comparison.get("summary") if isinstance(comparison.get("summary"), dict) else {}
    current = comparison.get("current") if isinstance(comparison.get("current"), dict) else {}
    best_prior = comparison.get("best_prior") if isinstance(comparison.get("best_prior"), dict) else {}
    evidence = [f"formal_run_comparison={str(summary.get('status') or '-')}"]
    if current:
        evidence.append(f"formal_current_run={str(current.get('run_id') or '-')}")
        evidence.append(f"formal_current_objective={str(current.get('objective_value') if 'objective_value' in current else '-')}")
    if best_prior:
        evidence.append(f"formal_best_prior_run={str(best_prior.get('run_id') or '-')}")
        evidence.append(
            f"formal_best_prior_objective={str(best_prior.get('objective_value') if 'objective_value' in best_prior else '-')}"
        )
    if "delta_objective" in comparison:
        evidence.append(f"formal_delta_objective={str(comparison.get('delta_objective'))}")
    recommendation = str(summary.get("recommendation") or "").strip()
    if recommendation:
        evidence.append(f"formal_recommendation={recommendation}")
    return tuple(evidence)


def _formal_run_regression_gap(status: dict[str, Any]) -> str:
    comparison = status.get("formal_run_comparison")
    if not isinstance(comparison, dict):
        return ""
    summary = comparison.get("summary") if isinstance(comparison.get("summary"), dict) else {}
    if str(summary.get("status") or "") != "regressed":
        return ""
    current = comparison.get("current") if isinstance(comparison.get("current"), dict) else {}
    best_prior = comparison.get("best_prior") if isinstance(comparison.get("best_prior"), dict) else {}
    current_run = str(current.get("run_id") or status.get("run_id") or "-")
    best_run = str(best_prior.get("run_id") or "-")
    current_objective = str(current.get("objective_value") if "objective_value" in current else status.get("objective_value", "-"))
    best_objective = str(best_prior.get("objective_value") if "objective_value" in best_prior else "-")
    delta = str(comparison.get("delta_objective") if "delta_objective" in comparison else "-")
    return (
        "最新正式批次较同配置历史最好批次退化，不能自动作为当前可发布候选。"
        f" 当前批次={current_run}, objective={current_objective};"
        f" 历史最好批次={best_run}, objective={best_objective};"
        f" delta_objective={delta}。"
        " 应保留历史最好正式批次，或完成一次不退化的新正式求解后再替换候选。"
    )


def _recommended_formal_candidate_evidence(status: dict[str, Any]) -> tuple[str, ...]:
    recommendation = status.get("recommended_formal_candidate")
    if not isinstance(recommendation, dict):
        return ("recommended_formal_candidate=-",)
    summary = recommendation.get("summary") if isinstance(recommendation.get("summary"), dict) else {}
    candidate = recommendation.get("candidate") if isinstance(recommendation.get("candidate"), dict) else {}
    evidence = [f"recommended_formal_candidate={str(summary.get('status') or '-')}"]
    if candidate:
        evidence.append(f"recommended_formal_run={str(candidate.get('run_id') or '-')}")
        evidence.append(
            f"recommended_formal_objective={str(candidate.get('objective_value') if 'objective_value' in candidate else '-')}"
        )
    selected = str(summary.get("selected_run_id") or "").strip()
    if selected:
        evidence.append(f"recommended_selected_run={selected}")
    quality = recommendation.get("quality_evidence") if isinstance(recommendation.get("quality_evidence"), dict) else {}
    quality_summary = quality.get("summary") if isinstance(quality.get("summary"), dict) else {}
    if quality_summary:
        evidence.append(f"recommended_quality_evidence={str(quality_summary.get('status') or '-')}")
        if str(quality_summary.get("proof_run_id") or "").strip():
            evidence.append(f"recommended_proof_run={str(quality_summary.get('proof_run_id') or '-')}")
        if "candidate_objective_gap" in quality_summary:
            evidence.append(f"recommended_candidate_gap={str(quality_summary.get('candidate_objective_gap'))}")
    return tuple(evidence)


def _audit_candidate_selection_evidence(status: dict[str, Any]) -> tuple[str, ...]:
    selected = str(status.get("audit_candidate_selection") or "").strip()
    if not selected:
        return tuple()
    return (
        f"audit_candidate_selection={selected}",
        f"audit_latest_run={str(status.get('audit_latest_run_id') or '-')}",
        f"audit_latest_status_file={str(status.get('audit_latest_status_file') or '-')}",
    )


def _package_path_for_status(status: dict[str, Any] | None) -> Path | None:
    if not isinstance(status, dict):
        return None
    raw = str(status.get("package_file") or "").strip()
    if raw:
        return Path(raw)
    status_file = str(status.get("status_file") or "").strip()
    if status_file:
        status_path = Path(status_file)
        if status_path.name == "status.json":
            return status_path.parent / "result_package.zip"
    run_dir = str(status.get("run_dir") or "").strip()
    return Path(run_dir) / "result_package.zip" if run_dir else None


def _current_package_contract(status: dict[str, Any] | None) -> tuple[bool, tuple[str, ...], str]:
    package = _package_path_for_status(status)
    evidence: list[str] = [f"package_file={str(package) if package else ''}"]
    if package is None:
        return False, tuple(evidence), "未发现当前结果包路径，无法证明交付包结构。"
    if not package.exists() or not package.is_file():
        return False, tuple(evidence), "当前结果包不存在；请重新生成结果包。"
    try:
        with zipfile.ZipFile(package) as zf:
            names = [str(name).replace("\\", "/") for name in zf.namelist()]
            name_set = set(names)
            status_entries = [name for name in names if name.endswith("status.json")]
            evidence.extend(
                (
                    f"zip_entry_count={len(names)}",
                    f"status_entries={','.join(status_entries) or '-'}",
                )
            )
            required = ("delivery_manifest.json", "status.json")
            missing = [name for name in required if name not in name_set]
            if missing:
                return False, tuple(evidence), f"结果包根目录缺少入口文件：{', '.join(missing)}。"
            if status_entries != ["status.json"]:
                return False, tuple(evidence), "结果包必须只有一个根目录 status.json 状态入口。"
            manifest = json.loads(zf.read("delivery_manifest.json").decode("utf-8-sig"))
            packaged_status = json.loads(zf.read("status.json").decode("utf-8-sig"))
    except (OSError, zipfile.BadZipFile, KeyError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return False, tuple(evidence), f"结果包无法读取或根目录入口文件格式异常：{exc}"

    manifest_integrity = {}
    if isinstance(manifest, dict):
        manifest_integrity = manifest.get("package_integrity") if isinstance(manifest.get("package_integrity"), dict) else {}
    manifest_status = str(manifest_integrity.get("status") or "")
    publish = packaged_status.get("publish_assessment") if isinstance(packaged_status, dict) else {}
    publish_summary = publish.get("summary") if isinstance(publish, dict) else {}
    status_preflight = publish.get("release_preflight") if isinstance(publish, dict) else {}
    status_preflight = status_preflight if isinstance(status_preflight, dict) else {}
    packaged_publish_status = str(publish_summary.get("status") or "")
    release_decision = manifest.get("release_decision") if isinstance(manifest, dict) else {}
    release_decision = release_decision if isinstance(release_decision, dict) else {}
    manifest_release_state = manifest.get("release_state") if isinstance(manifest.get("release_state"), dict) else {}
    status_release_state = packaged_status.get("release_state") if isinstance(packaged_status, dict) and isinstance(packaged_status.get("release_state"), dict) else {}
    manifest_publish = manifest.get("publish_assessment") if isinstance(manifest.get("publish_assessment"), dict) else {}
    manifest_run = manifest.get("run") if isinstance(manifest, dict) else {}
    manifest_run = manifest_run if isinstance(manifest_run, dict) else {}
    manifest_solver = manifest.get("solver") if isinstance(manifest.get("solver"), dict) else {}
    status_availability = packaged_status.get("result_availability") if isinstance(packaged_status, dict) else {}
    status_availability = status_availability if isinstance(status_availability, dict) else {}
    manifest_availability = manifest.get("result_availability") if isinstance(manifest, dict) else {}
    manifest_availability = manifest_availability if isinstance(manifest_availability, dict) else {}
    solve_diagnostics_gap, solve_diagnostics_evidence = _solve_diagnostics_package_gap(
        packaged_status=packaged_status if isinstance(packaged_status, dict) else {},
        manifest=manifest if isinstance(manifest, dict) else {},
    )
    manifest_release_status = str(release_decision.get("status") or "")
    manifest_can_publish = release_decision.get("can_publish")
    status_can_publish = publish_summary.get("can_publish") if isinstance(publish_summary, dict) else None
    formal_ready_present = "formal_release_ready" in release_decision
    formal_release_ready = bool(release_decision.get("formal_release_ready"))
    manifest_message = str(manifest_run.get("message") or "")
    status_message = str(packaged_status.get("message") or "") if isinstance(packaged_status, dict) else ""
    diagnostic_gap, diagnostic_evidence = _diagnostic_relaxation_package_gap(
        packaged_status=packaged_status,
        manifest_run=manifest_run,
    )
    solver_quality_gap, solver_quality_evidence = _solver_quality_package_gap(
        packaged_status=packaged_status,
        manifest=manifest if isinstance(manifest, dict) else {},
        publish_status=packaged_publish_status,
    )
    objective_reconciliation_gap, objective_reconciliation_evidence = _objective_reconciliation_package_gap(
        packaged_status=packaged_status if isinstance(packaged_status, dict) else {},
        manifest_solver=manifest_solver,
    )
    formal_candidate_gap, formal_candidate_evidence = _formal_candidate_package_gap(
        packaged_status=packaged_status if isinstance(packaged_status, dict) else {},
        manifest_solver=manifest_solver,
    )
    evidence.extend(
        (
            f"manifest_package_integrity={manifest_status or '-'}",
            f"packaged_publish_status={packaged_publish_status or '-'}",
            f"manifest_release_status={manifest_release_status or '-'}",
            f"formal_release_ready={formal_release_ready}",
            f"release_state={str(status_release_state.get('status') or '-')}",
            f"result_availability={str(status_availability.get('label') or '-')}",
            f"result_schedule_files={str(status_availability.get('schedule_file_count') if 'schedule_file_count' in status_availability else '-')}",
            *solver_quality_evidence,
            *objective_reconciliation_evidence,
            *formal_candidate_evidence,
            *diagnostic_evidence,
            *solve_diagnostics_evidence,
        )
    )
    if manifest_status != "ok":
        return False, tuple(evidence), "根目录 delivery_manifest.json 未记录 package_integrity.status=ok。"
    if not packaged_publish_status:
        return False, tuple(evidence), "根目录 status.json 缺少 publish_assessment.summary.status。"
    if not status_release_state:
        return False, tuple(evidence), "根目录 status.json 缺少 release_state；外部集成无法直接判断正式发布状态。"
    if not manifest_release_state:
        return False, tuple(evidence), "根目录 delivery_manifest.json 缺少 release_state；交付清单无法直接表达正式发布状态。"
    if manifest_release_status != packaged_publish_status:
        return (
            False,
            tuple(evidence),
            f"根目录 delivery_manifest.json 与 status.json 的发布状态不一致：{manifest_release_status or '-'} != {packaged_publish_status}。",
        )
    if str(status_release_state.get("status") or "") != packaged_publish_status:
        return False, tuple(evidence), "根目录 status.json 的 release_state.status 与发布状态不一致。"
    if str(manifest_release_state.get("status") or "") != packaged_publish_status:
        return False, tuple(evidence), "根目录 delivery_manifest.json 的 release_state.status 与发布状态不一致。"
    if manifest_can_publish is not None and status_can_publish is not None and bool(manifest_can_publish) != bool(status_can_publish):
        return False, tuple(evidence), "根目录 delivery_manifest.json 与 status.json 的 can_publish 不一致。"
    if not formal_ready_present:
        return False, tuple(evidence), "根目录 delivery_manifest.json 缺少 release_decision.formal_release_ready。"
    expected_formal_ready = packaged_publish_status == "ready"
    if formal_release_ready != expected_formal_ready:
        return False, tuple(evidence), "根目录 delivery_manifest.json 的 formal_release_ready 与发布状态不一致。"
    for state_name, release_state in (("status.json", status_release_state), ("delivery_manifest.json", manifest_release_state)):
        if bool(release_state.get("formal_release_ready")) != expected_formal_ready:
            return False, tuple(evidence), f"根目录 {state_name} 的 release_state.formal_release_ready 与发布状态不一致。"
        if not str(release_state.get("package_label") or "").strip():
            return False, tuple(evidence), f"根目录 {state_name} 的 release_state 缺少 package_label。"
        if str(release_state.get("run_message") or "") != status_message:
            return False, tuple(evidence), f"根目录 {state_name} 的 release_state.run_message 与 status.json message 不一致。"
    availability_gap = _result_availability_contract_gap(
        packaged_status,
        status_availability=status_availability,
        manifest_availability=manifest_availability,
        status_release_state=status_release_state,
        expected_formal_ready=expected_formal_ready,
    )
    if availability_gap:
        return False, tuple(evidence), availability_gap
    if not manifest_message or not status_message:
        return False, tuple(evidence), "根目录 status.json 或 delivery_manifest.json 缺少运行说明 message。"
    if manifest_message != status_message:
        return False, tuple(evidence), "根目录 status.json 与 delivery_manifest.json 的运行说明 message 不一致。"
    if diagnostic_gap:
        return False, tuple(evidence), diagnostic_gap
    if solve_diagnostics_gap:
        return False, tuple(evidence), solve_diagnostics_gap
    return True, tuple(evidence), ""


def _solver_quality_package_gap(
    *,
    packaged_status: dict[str, Any],
    manifest: dict[str, Any],
    publish_status: str,
) -> tuple[str, tuple[str, ...]]:
    manifest_solver = manifest.get("solver") if isinstance(manifest.get("solver"), dict) else {}
    status_solver_status = str(packaged_status.get("solver_status") or "").strip()
    manifest_solver_status = str(manifest_solver.get("solver_status") or "").strip()
    solver_status = (status_solver_status or manifest_solver_status).upper()
    status_schedule_count = _availability_int(packaged_status.get("schedule_file_count"))
    manifest_schedule_count = _availability_int(manifest_solver.get("schedule_file_count"))
    quality_keys = ("objective_value", "best_bound", "objective_gap", "gap_percent", "optimality_status")
    evidence = (
        f"status_optimality_status={str(packaged_status.get('optimality_status') or '-')}",
        f"manifest_optimality_status={str(manifest_solver.get('optimality_status') or '-')}",
        f"status_objective_gap={_quality_evidence_value(packaged_status.get('objective_gap'))}",
        f"manifest_objective_gap={_quality_evidence_value(manifest_solver.get('objective_gap'))}",
    )
    requires_quality = solver_status in {"FEASIBLE", "OPTIMAL"} or status_schedule_count > 0 or manifest_schedule_count > 0
    if not requires_quality:
        return "", evidence
    if not manifest_solver:
        return "根目录 delivery_manifest.json 缺少 solver 求解质量摘要，无法证明交付包对应的求解状态和最优性。", evidence
    missing_status = [key for key in quality_keys if key not in packaged_status]
    missing_manifest = [key for key in quality_keys if key not in manifest_solver]
    if missing_status:
        return f"根目录 status.json 缺少求解质量字段：{', '.join(missing_status)}。", evidence
    if missing_manifest:
        return f"根目录 delivery_manifest.json 的 solver 缺少求解质量字段：{', '.join(missing_manifest)}。", evidence
    comparisons = (
        ("solver_status", "str"),
        ("solution_count", "int"),
        ("schedule_file_count", "int"),
        ("objective_value", "float"),
        ("best_bound", "float"),
        ("objective_gap", "float"),
        ("gap_percent", "float"),
        ("optimality_status", "str"),
    )
    for key, kind in comparisons:
        if key not in packaged_status or key not in manifest_solver:
            continue
        left = packaged_status.get(key)
        right = manifest_solver.get(key)
        if kind == "int" and _availability_int(left) != _availability_int(right):
            return f"根目录 delivery_manifest.json 与 status.json 的 solver.{key} 不一致。", evidence
        if kind == "float" and not _quality_float_equal(left, right):
            return f"根目录 delivery_manifest.json 与 status.json 的 solver.{key} 不一致。", evidence
        if kind == "str" and str(left or "") != str(right or ""):
            return f"根目录 delivery_manifest.json 与 status.json 的 solver.{key} 不一致。", evidence
    try:
        from scheduler.solver_quality import solver_quality_fields

        expected = solver_quality_fields(
            packaged_status.get("objective_value"),
            packaged_status.get("best_bound"),
            solver_status=solver_status,
        )
    except Exception:
        expected = {}
    if expected:
        for key in ("objective_gap", "gap_percent"):
            expected_value = expected.get(key)
            if expected_value is not None and not _quality_float_equal(packaged_status.get(key), expected_value):
                return f"根目录 status.json 的 {key} 与 objective_value/best_bound 重新计算结果不一致。", evidence
        expected_optimality = str(expected.get("optimality_status") or "")
        if expected_optimality and str(packaged_status.get("optimality_status") or "") != expected_optimality:
            return "根目录 status.json 的 optimality_status 与 objective_value/best_bound 重新计算结果不一致。", evidence
    if publish_status == "ready" and str(packaged_status.get("optimality_status") or "") == "gap_remaining":
        evidence = (*evidence, "quality_gap_advisory=True")
    return "", evidence


def _objective_reconciliation_package_gap(
    *,
    packaged_status: dict[str, Any],
    manifest_solver: dict[str, Any],
) -> tuple[str, tuple[str, ...]]:
    status_breakdown = packaged_status.get("objective_breakdown") if isinstance(packaged_status.get("objective_breakdown"), dict) else {}
    manifest_breakdown = manifest_solver.get("objective_breakdown") if isinstance(manifest_solver.get("objective_breakdown"), dict) else {}
    status_summary = status_breakdown.get("summary") if isinstance(status_breakdown.get("summary"), dict) else {}
    manifest_summary = manifest_breakdown.get("summary") if isinstance(manifest_breakdown.get("summary"), dict) else {}
    status_reconciliation = str(status_summary.get("objective_reconciliation_status") or "")
    manifest_reconciliation = str(manifest_summary.get("objective_reconciliation_status") or "")
    evidence = [
        f"status_objective_reconciliation={status_reconciliation or '-'}",
        f"manifest_objective_reconciliation={manifest_reconciliation or '-'}",
        f"status_objective_explain_delta={_quality_evidence_value(status_summary.get('objective_explain_delta'))}",
        f"manifest_objective_explain_delta={_quality_evidence_value(manifest_summary.get('objective_explain_delta'))}",
    ]
    status_top = status_breakdown.get("top") if isinstance(status_breakdown.get("top"), list) else []
    manifest_top = manifest_breakdown.get("top") if isinstance(manifest_breakdown.get("top"), list) else []
    status_top_rule = next((item for item in status_top if isinstance(item, dict) and item.get("penalty_sum")), {})
    manifest_top_rule = next((item for item in manifest_top if isinstance(item, dict) and item.get("penalty_sum")), {})
    status_examples = status_top_rule.get("example_events") if isinstance(status_top_rule.get("example_events"), list) else []
    manifest_examples = manifest_top_rule.get("example_events") if isinstance(manifest_top_rule.get("example_events"), list) else []
    evidence.extend(
        [
            f"status_objective_examples={len(status_examples)}",
            f"manifest_objective_examples={len(manifest_examples)}",
        ]
    )
    if not status_breakdown and not manifest_breakdown:
        return "", tuple(evidence)
    required = (
        "total_penalty",
        "reward_credit",
        "net_event_penalty",
        "solver_objective_value",
        "objective_explain_delta",
        "objective_reconciliation_status",
    )
    missing_status = [key for key in required if key not in status_summary]
    missing_manifest = [key for key in required if key not in manifest_summary]
    if missing_status:
        return f"根目录 status.json 的 objective_breakdown.summary 缺少目标对账字段：{', '.join(missing_status)}。", tuple(evidence)
    if missing_manifest:
        return f"根目录 delivery_manifest.json 的 solver.objective_breakdown.summary 缺少目标对账字段：{', '.join(missing_manifest)}。", tuple(evidence)
    for key in ("total_penalty", "reward_credit", "net_event_penalty", "solver_objective_value", "objective_explain_delta"):
        if not _quality_float_equal(status_summary.get(key), manifest_summary.get(key)):
            return f"根目录 delivery_manifest.json 与 status.json 的 objective_breakdown.summary.{key} 不一致。", tuple(evidence)
    if status_reconciliation != manifest_reconciliation:
        return "根目录 delivery_manifest.json 与 status.json 的 objective_reconciliation_status 不一致。", tuple(evidence)
    if status_top_rule:
        if "potential_penalty_reduction" not in status_top_rule:
            return "根目录 status.json 的 objective_breakdown.top 缺少 potential_penalty_reduction，无法量化主导罚分整改收益。", tuple(evidence)
        if not status_examples:
            return "根目录 status.json 的 objective_breakdown.top 缺少 example_events，无法定位主导罚分的具体教师、日期或岗位。", tuple(evidence)
    if manifest_top_rule:
        if "potential_penalty_reduction" not in manifest_top_rule:
            return "根目录 delivery_manifest.json 的 solver.objective_breakdown.top 缺少 potential_penalty_reduction。", tuple(evidence)
        if not manifest_examples:
            return "根目录 delivery_manifest.json 的 solver.objective_breakdown.top 缺少 example_events。", tuple(evidence)
    if status_examples and manifest_examples:
        for key in ("teacher", "day", "period", "penalty"):
            if str(status_examples[0].get(key) or "") != str(manifest_examples[0].get(key) or ""):
                return f"根目录 delivery_manifest.json 与 status.json 的 objective_breakdown.top[0].example_events[0].{key} 不一致。", tuple(evidence)
    return "", tuple(evidence)


def _formal_candidate_package_gap(
    *,
    packaged_status: dict[str, Any],
    manifest_solver: dict[str, Any],
) -> tuple[str, tuple[str, ...]]:
    status_comparison = packaged_status.get("formal_run_comparison") if isinstance(packaged_status.get("formal_run_comparison"), dict) else {}
    manifest_comparison = (
        manifest_solver.get("formal_run_comparison") if isinstance(manifest_solver.get("formal_run_comparison"), dict) else {}
    )
    status_candidate = (
        packaged_status.get("recommended_formal_candidate")
        if isinstance(packaged_status.get("recommended_formal_candidate"), dict)
        else {}
    )
    manifest_candidate = (
        manifest_solver.get("recommended_formal_candidate")
        if isinstance(manifest_solver.get("recommended_formal_candidate"), dict)
        else {}
    )
    status_comparison_key = _summary_key(status_comparison)
    manifest_comparison_key = _summary_key(manifest_comparison)
    status_candidate_key = _summary_key(status_candidate)
    manifest_candidate_key = _summary_key(manifest_candidate)
    status_selected = _summary_selected_run(status_candidate)
    manifest_selected = _summary_selected_run(manifest_candidate)
    evidence = (
        f"status_formal_comparison={status_comparison_key or '-'}",
        f"manifest_formal_comparison={manifest_comparison_key or '-'}",
        f"status_recommended_candidate={status_candidate_key or '-'}",
        f"manifest_recommended_candidate={manifest_candidate_key or '-'}",
        f"status_recommended_selected_run={status_selected or '-'}",
        f"manifest_recommended_selected_run={manifest_selected or '-'}",
    )
    comparison_key = status_comparison_key or manifest_comparison_key
    if comparison_key != "regressed":
        return "", evidence
    if not status_selected:
        return "根目录 status.json 已记录正式批次退化，但缺少 recommended_formal_candidate.selected_run_id。", evidence
    if not manifest_selected:
        return "根目录 delivery_manifest.json 已记录正式批次退化，但缺少 solver.recommended_formal_candidate.selected_run_id。", evidence
    if status_selected != manifest_selected:
        return "根目录 status.json 与 delivery_manifest.json 的推荐正式候选批次不一致。", evidence
    return "", evidence


def _summary_key(value: dict[str, Any]) -> str:
    summary = value.get("summary") if isinstance(value.get("summary"), dict) else {}
    return str(summary.get("status") or "")


def _summary_selected_run(value: dict[str, Any]) -> str:
    summary = value.get("summary") if isinstance(value.get("summary"), dict) else {}
    return str(summary.get("selected_run_id") or "")


def _quality_evidence_value(value: Any) -> str:
    if value is None:
        return "-"
    return str(value)


def _quality_float_equal(left: Any, right: Any) -> bool:
    left_value = _quality_float(left)
    right_value = _quality_float(right)
    if left_value is None or right_value is None:
        return left_value is None and right_value is None
    return abs(left_value - right_value) <= 1e-6


def _quality_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _diagnostic_relaxation_package_gap(
    *,
    packaged_status: dict[str, Any],
    manifest_run: dict[str, Any],
) -> tuple[str, tuple[str, ...]]:
    status_relaxations = _relaxation_signature(packaged_status.get("active_diagnostic_relaxations"))
    manifest_relaxations = _relaxation_signature(manifest_run.get("active_diagnostic_relaxations"))
    run_purpose = str(packaged_status.get("run_purpose") or manifest_run.get("run_purpose") or "")
    title = str(packaged_status.get("diagnostic_plan_title") or manifest_run.get("diagnostic_plan_title") or "")
    evidence = (
        f"diagnostic_run_purpose={run_purpose or '-'}",
        f"status_active_diagnostic_relaxations={len(status_relaxations)}",
        f"manifest_active_diagnostic_relaxations={len(manifest_relaxations)}",
    )
    expects_relaxation_evidence = (
        bool(status_relaxations)
        or bool(manifest_relaxations)
        or (run_purpose == "diagnostic_trial" and "已应用临时放宽方案" in title)
    )
    if not expects_relaxation_evidence:
        return "", evidence
    if not status_relaxations:
        return "根目录 status.json 缺少 active_diagnostic_relaxations，无法追溯诊断试跑放宽了哪些规则。", evidence
    if not manifest_relaxations:
        return "根目录 delivery_manifest.json 缺少 run.active_diagnostic_relaxations，交付清单无法追溯诊断放宽项。", evidence
    if status_relaxations != manifest_relaxations:
        return "根目录 status.json 与 delivery_manifest.json 的 active_diagnostic_relaxations 不一致。", evidence
    return "", evidence


def _solve_diagnostics_package_gap(
    *,
    packaged_status: dict[str, Any],
    manifest: dict[str, Any],
) -> tuple[str, tuple[str, ...]]:
    status_diag = packaged_status.get("solve_diagnostics") if isinstance(packaged_status.get("solve_diagnostics"), dict) else {}
    manifest_diag = manifest.get("solve_diagnostics") if isinstance(manifest.get("solve_diagnostics"), dict) else {}
    status_summary = status_diag.get("summary") if isinstance(status_diag.get("summary"), dict) else {}
    manifest_summary = manifest_diag.get("summary") if isinstance(manifest_diag.get("summary"), dict) else {}
    status_issues = status_diag.get("issues") if isinstance(status_diag.get("issues"), list) else []
    status_plans = status_diag.get("relaxation_plans") if isinstance(status_diag.get("relaxation_plans"), list) else []
    status_quality_plan = status_diag.get("quality_plan") if isinstance(status_diag.get("quality_plan"), dict) else {}
    manifest_quality_plan = manifest_diag.get("quality_plan") if isinstance(manifest_diag.get("quality_plan"), dict) else {}
    manifest_actions = manifest_diag.get("next_actions") if isinstance(manifest_diag.get("next_actions"), list) else []
    status_floor_action_notes = _business_floor_action_note_count(status_quality_plan)
    manifest_floor_action_notes = _business_floor_action_note_count(manifest_quality_plan)
    evidence = (
        f"status_solve_diagnostics={str(status_summary.get('status') or '-')}",
        f"manifest_solve_diagnostics={str(manifest_summary.get('status') or '-')}",
        f"solve_diagnostic_issues={len(status_issues)}",
        f"solve_diagnostic_plans={len(status_plans)}",
        f"status_quality_plan={str(status_quality_plan.get('status') or '-')}",
        f"manifest_quality_plan={str(manifest_quality_plan.get('status') or '-')}",
        f"status_business_floor_action_notes={status_floor_action_notes}",
        f"manifest_business_floor_action_notes={manifest_floor_action_notes}",
    )

    solver_status = str(packaged_status.get("solver_status") or "").strip().upper()
    schedule_count = _availability_int(packaged_status.get("schedule_file_count"))
    requires_diagnostics = str(packaged_status.get("status") or "") == "completed" or solver_status or schedule_count > 0
    if not requires_diagnostics:
        return "", evidence
    if not status_diag:
        return "根目录 status.json 缺少 solve_diagnostics，无法解释当前批次的求解质量、软约束代价或排障建议。", evidence
    if not manifest_diag:
        return "根目录 delivery_manifest.json 缺少 solve_diagnostics；交付清单无法携带求解诊断摘要。", evidence
    if not str(status_summary.get("status") or "").strip():
        return "根目录 status.json 的 solve_diagnostics 缺少 summary.status。", evidence
    if str(status_summary.get("status") or "") != str(manifest_summary.get("status") or ""):
        return "根目录 delivery_manifest.json 与 status.json 的 solve_diagnostics.summary.status 不一致。", evidence

    if str(packaged_status.get("optimality_status") or "") == "gap_remaining":
        if not any(isinstance(issue, dict) and str(issue.get("domain") or "") == "求解质量" for issue in status_issues):
            return "根目录 status.json 显示仍有最优性缺口，但 solve_diagnostics 未列出求解质量复核项。", evidence
        if not manifest_actions:
            return "根目录 delivery_manifest.json 的 solve_diagnostics.next_actions 为空，无法指导结果交付前检查。", evidence
        if str(status_quality_plan.get("status") or "") != "recommended":
            return "根目录 status.json 显示仍有最优性缺口，但 solve_diagnostics.quality_plan 未提供求解质量复跑计划。", evidence
        if str(manifest_quality_plan.get("status") or "") != "recommended":
            return "根目录 delivery_manifest.json 缺少 solve_diagnostics.quality_plan；交付清单无法携带求解质量复跑计划。", evidence
        status_steps = status_quality_plan.get("steps") if isinstance(status_quality_plan.get("steps"), list) else []
        manifest_steps = manifest_quality_plan.get("steps") if isinstance(manifest_quality_plan.get("steps"), list) else []
        if not status_steps or not manifest_steps:
            return "solve_diagnostics.quality_plan 缺少可执行复跑步骤。", evidence
        status_step_ids = [str(step.get("id") or "") for step in status_steps if isinstance(step, dict)]
        if "quality.improve_incumbent" not in status_step_ids or "quality.prove_bound" not in status_step_ids:
            return "solve_diagnostics.quality_plan 必须同时包含 incumbent 改善和 bound 证明复跑步骤。", evidence
        if "quality.resolve_business_floor" in status_step_ids:
            if status_floor_action_notes <= 0:
                return "根目录 status.json 的业务下限质量步骤缺少 manual_action.business_floor_note_summaries。", evidence
            if manifest_floor_action_notes <= 0:
                return "根目录 delivery_manifest.json 的业务下限质量步骤缺少 manual_action.business_floor_note_summaries；交付包无法指导候选确认。", evidence

    breakdown = packaged_status.get("objective_breakdown") if isinstance(packaged_status.get("objective_breakdown"), dict) else {}
    manifest_solver = manifest.get("solver") if isinstance(manifest.get("solver"), dict) else {}
    if not breakdown:
        breakdown = manifest_solver.get("objective_breakdown") if isinstance(manifest_solver.get("objective_breakdown"), dict) else {}
    top = breakdown.get("top") if isinstance(breakdown.get("top"), list) else []
    top_rules = [
        str(item.get("rule_name") or item.get("rule_id") or "").strip()
        for item in top[:3]
        if isinstance(item, dict) and str(item.get("rule_name") or item.get("rule_id") or "").strip()
    ]
    if top_rules:
        issue_text = "\n".join(str(issue.get("title") or "") + "\n" + str(issue.get("detail") or "") for issue in status_issues if isinstance(issue, dict))
        missing = [rule for rule in top_rules if rule not in issue_text]
        if missing:
            return f"根目录 status.json 的 solve_diagnostics 未覆盖主导软约束代价：{', '.join(missing[:3])}。", evidence
        if not status_plans:
            return "根目录 status.json 的 objective_breakdown 存在主导软约束代价，但 solve_diagnostics 未提供诊断试跑或调参方案。", evidence
    return "", evidence


def _business_floor_action_note_count(quality_plan: dict[str, Any]) -> int:
    steps = quality_plan.get("steps") if isinstance(quality_plan.get("steps"), list) else []
    for step in steps:
        if not isinstance(step, dict) or str(step.get("id") or "") != "quality.resolve_business_floor":
            continue
        manual_action = step.get("manual_action") if isinstance(step.get("manual_action"), dict) else {}
        summaries = (
            manual_action.get("business_floor_note_summaries")
            if isinstance(manual_action.get("business_floor_note_summaries"), list)
            else []
        )
        return len([item for item in summaries if isinstance(item, dict)])
    return 0


def _relaxation_signature(value: Any) -> tuple[tuple[str, str, tuple[str, ...]], ...]:
    if not isinstance(value, list):
        return tuple()
    rows: list[tuple[str, str, tuple[str, ...]]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        patches = item.get("patches") if isinstance(item.get("patches"), list) else []
        patch_labels = tuple(
            sorted(
                str(patch.get("path_label") or "").strip()
                for patch in patches
                if isinstance(patch, dict) and str(patch.get("path_label") or "").strip()
            )
        )
        rows.append(
            (
                str(item.get("id") or "").strip(),
                str(item.get("title") or item.get("description") or "").strip(),
                patch_labels,
            )
        )
    return tuple(sorted(rows))


def _result_availability_contract_gap(
    packaged_status: dict[str, Any],
    *,
    status_availability: dict[str, Any],
    manifest_availability: dict[str, Any],
    status_release_state: dict[str, Any],
    expected_formal_ready: bool,
) -> str:
    if not status_availability:
        return "根目录 status.json 缺少 result_availability；外部集成无法直接判断结果文件是否生成。"
    if not manifest_availability:
        return "根目录 delivery_manifest.json 缺少 result_availability；交付清单无法直接表达结果文件可用性。"
    status_schedule_count = _availability_int(status_availability.get("schedule_file_count"))
    packaged_schedule_count = _availability_int(packaged_status.get("schedule_file_count"))
    if "schedule_file_count" not in packaged_status:
        return "根目录 status.json 缺少 schedule_file_count；无法校验结果文件可用性摘要。"
    if status_schedule_count != packaged_schedule_count:
        return (
            "根目录 status.json 的 result_availability.schedule_file_count "
            "与 status.json.schedule_file_count 不一致。"
        )
    if bool(status_availability.get("has_schedule_files")) != (status_schedule_count > 0):
        return "根目录 status.json 的 result_availability.has_schedule_files 与课表文件数量不一致。"
    if bool(status_availability.get("has_result_package")) is not True:
        return "根目录 status.json 的 result_availability 未确认当前结果包已生成。"
    if str(status_availability.get("package_label") or "") != str(status_release_state.get("package_label") or ""):
        return "根目录 status.json 的 result_availability.package_label 与 release_state.package_label 不一致。"
    if bool(status_availability.get("formal_release_ready")) != expected_formal_ready:
        return "根目录 status.json 的 result_availability.formal_release_ready 与发布状态不一致。"
    if str(status_availability.get("status") or "") == "available":
        primary = status_availability.get("primary_schedule_files")
        if not isinstance(primary, list) or not primary:
            return "根目录 status.json 的 result_availability 未列出主要课表文件。"
    comparisons = (
        ("status", "str"),
        ("label", "str"),
        ("package_label", "str"),
        ("schedule_file_count", "int"),
        ("has_result_package", "bool"),
        ("formal_release_ready", "bool"),
    )
    for key, kind in comparisons:
        left = status_availability.get(key)
        right = manifest_availability.get(key)
        if kind == "int" and _availability_int(left) != _availability_int(right):
            return f"根目录 delivery_manifest.json 与 status.json 的 result_availability.{key} 不一致。"
        if kind == "bool" and bool(left) != bool(right):
            return f"根目录 delivery_manifest.json 与 status.json 的 result_availability.{key} 不一致。"
        if kind == "str" and str(left or "") != str(right or ""):
            return f"根目录 delivery_manifest.json 与 status.json 的 result_availability.{key} 不一致。"
    return ""


def _availability_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _status_publishable(
    status: dict[str, Any] | None,
    *,
    strict_release: bool = False,
) -> tuple[bool, tuple[str, ...], str, bool]:
    if status is None:
        return False, tuple(), "未发现最近 Web 求解状态，无法证明当前有可发布课表。", False
    status = _with_runtime_context(status)
    publish_summary = _publish_summary(status)
    can_publish = bool(publish_summary.get("can_publish")) if isinstance(publish_summary, dict) else False
    publish_status = str(publish_summary.get("status") or "")
    solver_status = str(status.get("solver_status") or "")
    solution_count = int(status.get("solution_count") or 0)
    schedule_file_count = int(status.get("schedule_file_count") or 0)
    run_purpose = str(status.get("run_purpose") or "")
    formal_regression_gap = _formal_run_regression_gap(status)
    evidence = (
        f"status_file={status.get('status_file', '')}",
        f"solver_status={solver_status or '-'}",
        f"solution_count={solution_count}",
        f"schedule_file_count={schedule_file_count}",
        f"run_purpose={run_purpose or '-'}",
        f"config_fingerprint_match={str(status.get('config_fingerprint_match'))}",
        f"can_publish={can_publish}",
        f"publish_status={publish_status or '-'}",
        f"optimality_status={str(status.get('optimality_status') or '-')}",
        f"objective_gap={str(status.get('objective_gap') if 'objective_gap' in status else '-')}",
        *_business_floor_quality_evidence(status),
        *_audit_candidate_selection_evidence(status),
        *_formal_run_comparison_evidence(status),
        *_recommended_formal_candidate_evidence(status),
    )
    if run_purpose == "diagnostic_trial":
        return (
            False,
            evidence,
            "最近批次是诊断试跑，包含临时放宽规则；必须撤销临时规则后完成正式可行求解。",
            False,
        )
    if status.get("config_changed_after_run") is True or status.get("config_fingerprint_match") is False:
        freshness = status.get("config_freshness") if isinstance(status.get("config_freshness"), dict) else {}
        message = str(freshness.get("message") or "当前配置已在本批次求解后发生变化。")
        return False, evidence, f"{message} 必须使用当前配置重新完成正式求解，旧批次只能作为历史或排障材料。", False
    if formal_regression_gap:
        return False, evidence, formal_regression_gap, False
    has_candidate_schedule = can_publish and solution_count > 0 and schedule_file_count > 0
    formal_release_ready = has_candidate_schedule and publish_status in {"ready", "review"}
    if strict_release and has_candidate_schedule and publish_status not in {"ready", "review"}:
        label = publish_status or "unknown"
        if label == "blocked":
            reason = "当前发布校验仍被阻断，课表只能用于排障复核。"
        else:
            reason = "当前发布状态未明确为 ready，不能作为正式交付证据。"
        return False, evidence, f"严格发布要求 publish_assessment.summary.status=ready；当前为 {label}。{reason}", False
    if has_candidate_schedule:
        return True, evidence, "", formal_release_ready
    gap = "当前没有可发布课表；商业交付前必须完成一次正式可行求解并通过发布评估。"
    if solver_status:
        gap += f" 最近状态：{solver_status}。"
    return False, evidence, gap, False


def build_audit(
    repo_root: Path = REPO_ROOT,
    *,
    current_status: dict[str, Any] | None = None,
    strict_release: bool = False,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    research = _read_text(repo_root / "docs" / "commercial_k12_scheduler_research.md")
    app_js = _read_text(repo_root / "scheduler" / "app" / "static" / "app.js")
    app_css = _read_text(repo_root / "scheduler" / "app" / "static" / "styles.css")
    app_html = _read_text(repo_root / "scheduler" / "app" / "static" / "index.html")
    web_py = _read_text(repo_root / "scheduler" / "app" / "web.py")
    service_py = _read_text(repo_root / "scheduler" / "app" / "service.py")
    config_service = _read_text(repo_root / "scheduler" / "app" / "config_service.py")
    solve_service = _read_text(repo_root / "scheduler" / "app" / "solve_service.py")
    joint_solver = _read_text(repo_root / "scheduler" / "joint_solver.py")
    delivery_manifest = _read_text(repo_root / "scheduler" / "app" / "delivery_manifest.py")
    publish_assessment = _read_text(repo_root / "scheduler" / "app" / "publish_assessment.py")
    result_preview = _read_text(repo_root / "scheduler" / "app" / "result_preview.py")
    rule_explain = _read_text(repo_root / "scheduler" / "app" / "rule_explain.py")
    readiness = _read_text(repo_root / "scheduler" / "app" / "readiness.py")
    manual_adjustment = _read_text(repo_root / "scheduler" / "app" / "local_timetable_adjustment.py")
    academic_io = _read_text(repo_root / "scheduler" / "app" / "academic_affairs_io.py")
    access_control = _read_text(repo_root / "scheduler" / "app" / "access_control.py")
    access_control_tests = _read_text(repo_root / "verification" / "fixes" / "tests" / "test_access_control.py")
    academic_doc = _read_text(repo_root / "docs" / "k12_academic_affairs_expansion.md")
    gate_manifest = _read_text(repo_root / "verification" / "fixes" / "gate_manifest.py")

    checks: list[AcceptanceCheck] = []

    ok, missing = _contains_all(
        research,
        (
            "真实中国 K12 学校教务人员",
            "外部信号",
            "学什么",
            "舍弃什么",
            "来源",
        ),
    )
    checks.append(
        AcceptanceCheck(
            "target_user_and_market_research",
            "先完成面向真实中国 K12 教务人员的现状梳理、竞品/采购/需求研究，并记录取舍。",
            ("docs/commercial_k12_scheduler_research.md",),
            "pass" if ok else "fail",
            ("调研文档包含目标用户、外部信号、学习点、舍弃点和来源。",) if ok else tuple(),
            gap="" if ok else f"调研文档缺少：{', '.join(missing)}",
        )
    )

    checks.append(
        _check_exists(
            repo_root,
            check_id="backend_commercial_services",
            requirement="后端应具备求解前校验、发布评估、结果预览、诊断放宽、交付清单和教务对象服务。",
            artifacts=(
                "scheduler/app/readiness.py",
                "scheduler/app/publish_assessment.py",
                "scheduler/app/result_preview.py",
                "scheduler/app/rule_explain.py",
                "scheduler/app/solve_diagnostics.py",
                "scheduler/app/diagnostic_relaxation.py",
                "scheduler/app/delivery_manifest.py",
                "scheduler/app/academic_affairs.py",
            ),
            evidence_when_ok=("商业化后端服务模块已拆分存在，含机器清单和教务对象服务。",),
        )
    )

    ok, missing = _contains_all(
        app_html + "\n" + app_js,
        (
            "教师定位",
            "规则设置",
            "口头规则",
            "冲突检测",
            "求解运行",
            "求解结果",
            "教务工作台",
            "课表风险评估",
            "课表数据驾驶舱",
            "课表微调沙盘",
            "课表在线预览",
            "建议试运行方案",
        ),
    )
    checks.append(
        AcceptanceCheck(
            "web_frontend_workflows",
            "Web 前端应覆盖教务人员从录入、规则、冲突、求解、结果统计、微调到教务工作台的主流程。",
            ("scheduler/app/static/index.html", "scheduler/app/static/app.js", "scheduler/app/static/styles.css"),
            "pass" if ok else "fail",
            ("前端文本覆盖录入、规则、求解、结果统计、课表风险、在线预览和诊断试运行。",) if ok else tuple(),
            gap="" if ok else f"前端缺少流程文本：{', '.join(missing)}",
        )
    )

    ok, missing = _contains_all(
        app_html + "\n" + app_css,
        (
            "--sidebar-width: clamp(128px, 8vw, 154px)",
            "height: 100dvh",
            "repeat(auto-fit, minmax(min(100%, 142px), 1fr))",
            "grid-template-columns: repeat(2, minmax(0, 1fr));",
            "grid-template-columns: repeat(4, minmax(0, 1fr));",
            "@media (max-height: 760px) and (min-width: 821px)",
            "@media (max-width: 560px)",
            ".checkin-ledger-head",
            "display: none;",
            "20260513-affairs-console-1",
        ),
    )
    checks.append(
        AcceptanceCheck(
            "web_responsive_window_adaptation",
            "Web UI 应随浏览器窗口宽高自适应，桌面、窄屏、移动宽度和低高度窗口不能出现页面级横向溢出或关键区域压塌。",
            ("scheduler/app/static/index.html", "scheduler/app/static/styles.css"),
            "pass" if ok else "fail",
            ("前端具备动态视口高度、弹性侧栏、自动换列、窄屏表格重排和缓存版本标识。",) if ok else tuple(),
            gap="" if ok else f"响应式窗口适配缺少：{', '.join(missing)}",
        )
    )

    statistics_source = "\n".join((result_preview, rule_explain, app_html, app_js, app_css))
    ok, missing = _contains_all(
        statistics_source,
        (
            "scheduler.result_schedule_statistics.v1",
            "_build_schedule_statistics",
            "课表数据驾驶舱",
            "renderScheduleStatistics",
            "renderScheduleAdjustmentQueue",
            "renderScheduleAdjustmentSuggestion",
            "scheduler.result_rule_explain.v1",
            "build_rule_explain",
            "_preferred_event_log_path",
            "renderRuleExplain",
            "renderRuleExplainItem",
            "规则影响解释",
            "event_log.csv",
            "source_label",
            "renderScheduleStatBars",
            "renderScheduleInsights",
            "renderInsightRelated",
            "openPreviewFromInsight",
            "data-insight-preview-kind",
            "data-stat-preview-kind",
            "班级课量",
            "班级日课量",
            "教师日负荷",
            "连续课风险",
            "renderScheduleClassDayLoadList",
            "renderScheduleTeacherDayLoadList",
            "renderScheduleTeacherStreakList",
            "prefillManualAdjustmentFromScheduleSuggestion",
            "prefillManualAdjustmentFromConsecutiveSuggestion",
            "data-schedule-adjustment",
            "data-schedule-adjustment-label",
            "data-consecutive-adjustment",
            ".schedule-stat-grid",
            ".schedule-adjustment-board",
            ".schedule-adjustment-list",
            ".rule-explain-board",
            ".rule-explain-list",
            ".schedule-stat-adjust",
            ".schedule-stat-load button",
            ".schedule-insight-list",
            ".schedule-insight-related",
            "subject_distribution",
            "teacher_load",
            "teacher_day_balance",
            "teacher_day_load_balance",
            "class_day_load",
            "class_day_load_balance",
            "teacher_consecutive_load",
            "micro_adjustment",
            "adjustment_suggestions",
            "insights",
            "可执行微调建议",
            "教师日负荷均衡",
            "课表健康洞察",
        ),
    )
    checks.append(
        AcceptanceCheck(
            "result_schedule_statistics_dashboard",
            "求解结果页应围绕已排课表提供班级、教师、学科、星期、节次和局部微调影响统计。",
            (
                "scheduler/app/result_preview.py",
                "scheduler/app/rule_explain.py",
                "scheduler/app/static/index.html",
                "scheduler/app/static/app.js",
                "scheduler/app/static/styles.css",
            ),
            "pass" if ok else "fail",
            ("结果预览接口返回统计驾驶舱数据，前端结果页展示课表填充率、教师负荷、学科结构、时段分布和局部微调影响。",) if ok else tuple(),
            gap="" if ok else f"课表统计驾驶舱缺少：{', '.join(missing)}",
        )
    )

    ok, missing = _contains_all(
        "\n".join((result_preview, app_html, app_js, app_css)),
        (
            "scheduler.result_schedule_versions.v1",
            "_build_schedule_versions",
            "_schedule_version_history",
            "local_timetable_adjustments",
            "local_timetable_repairs",
            "课表版本时间线",
            "renderScheduleVersions",
            "renderScheduleVersionItem",
            ".schedule-version-list",
            ".schedule-version-changes",
            "changed_cell_count",
        ),
    )
    checks.append(
        AcceptanceCheck(
            "result_schedule_version_timeline",
            "结果页应展示原始求解课表、请假代课局部调整和人工微调形成的版本时间线，帮助教务人员理解当前全局课表从哪里来、改了哪些课格。",
            (
                "scheduler/app/result_preview.py",
                "scheduler/app/static/index.html",
                "scheduler/app/static/app.js",
                "scheduler/app/static/styles.css",
            ),
            "pass" if ok else "fail",
            ("结果预览接口返回课表版本时间线，前端展示当前版本、调整批次、累计变动课格和课格差异摘要。",) if ok else tuple(),
            gap="" if ok else f"课表版本时间线缺少：{', '.join(missing)}",
        )
    )

    checkin_layout_source = "\n".join((publish_assessment, readiness, app_js, app_css))
    ok, missing = _contains_all(
        checkin_layout_source,
        (
            "现有人力不足，需引入新候选",
            "待确认名单不能视为已确认可用人力",
            "引入新晚查候选",
            "引入对应性别的新教师/宿管/行政值守人员",
            "capacity_note",
            "candidate_data_requirements",
            "renderPublishGateCandidateRequirements",
            "需补齐候选资料",
            "#teachers > .split.tall",
            "#academic > .split.tall",
            "height: clamp(520px, 58vh, 680px)",
            "grid-auto-rows: auto",
            "min-height: 420px",
        ),
    )
    checks.append(
        AcceptanceCheck(
            "checkin_supply_shortage_guidance_and_layout",
            "晚查寝同日无晚自习风险提示应按实际事件提示人力不足、引入新候选，并保证前端数据区、求解区和结果区不能被布局压塌。",
            (
                "scheduler/app/publish_assessment.py",
                "scheduler/app/readiness.py",
                "scheduler/app/static/app.js",
                "scheduler/app/static/styles.css",
            ),
            "pass" if ok else "fail",
            ("晚查寝风险提示明确区分待确认名单与已确认人力，主要 Web 工作区具备稳定宽高约束。",) if ok else tuple(),
            gap="" if ok else f"晚查寝人力缺口或前端布局保护缺少：{', '.join(missing)}",
        )
    )

    checks.append(
        _check_exists(
            repo_root,
            check_id="core_solver_and_outputs",
            requirement="核心排课能力应保留 OR-Tools 联合求解、输出路径统一、Excel 导出策略和模块拆分边界。",
            artifacts=(
                "scheduler/joint_solver.py",
                "scheduler/joint_runtime.py",
                "scheduler/output_paths.py",
                "scheduler/output/excel_writer.py",
                "scheduler/model/constraints/day_weekday_reports.py",
                "scheduler/diagnostics/display_catalog.py",
            ),
            evidence_when_ok=("核心求解、运行时拆分、输出路径和导出策略模块存在。",),
        )
    )

    ok, missing = _contains_all(
        academic_doc,
        (
            "本轮落地的 50 项",
            "调代课管理",
            "考务监考管理",
            "走班选科管理",
            "场地资源管理",
            "教师请假管理",
            "课表发布变更",
            "健康分输出",
        ),
    )
    checks.append(
        AcceptanceCheck(
            "k12_academic_affairs_scope",
            "系统应面向真实 K12 教务对象，而不只是单一排课脚本。",
            ("docs/k12_academic_affairs_expansion.md", "scheduler/app/academic_affairs.py"),
            "pass" if ok else "fail",
            ("K12 教务扩展文档记录 50 项能力和核心教务对象。",) if ok else tuple(),
            gap="" if ok else f"K12 教务扩展说明缺少：{', '.join(missing)}",
        )
    )

    ok, missing = _contains_all(
        academic_io + "\n" + web_py + "\n" + app_html + "\n" + app_js,
        (
            "build_academic_table_template_csv",
            "build_academic_table_template_xlsx",
            "parse_academic_table_csv",
            "parse_academic_table_xlsx",
            "/api/academic-affairs/template",
            "/api/academic-affairs/import-csv",
            "/api/academic-affairs/import-file",
            "/api/academic-affairs/preview",
            "下载 Excel 模板",
            "导入表格",
            "persisted",
            "False",
        ),
    )
    checks.append(
        AcceptanceCheck(
            "academic_affairs_bulk_io",
            "教务扩展表应支持学校常见 Excel/CSV 表格流转：可下载当前表模板、导入当前表到页面核对并即时预览风险，且导入不能绕过人工保存确认。",
            (
                "scheduler/app/academic_affairs_io.py",
                "scheduler/app/web.py",
                "scheduler/app/static/index.html",
                "scheduler/app/static/app.js",
            ),
            "pass" if ok else "fail",
            ("教务工作台提供 Excel/CSV 模板下载、导入预览和未保存风险预览，后端返回 persisted=false。",) if ok else tuple(),
            gap="" if ok else f"教务 Excel/CSV 模板/导入闭环缺少：{', '.join(missing)}",
        )
    )

    ok, missing = _contains_all(
        academic_io + "\n" + web_py + "\n" + app_html + "\n" + app_js,
        (
            "build_academic_workbook_template_xlsx",
            "parse_academic_workbook_xlsx",
            "import_summary",
            "/api/academic-affairs/workbook-template",
            "/api/academic-affairs/import-workbook",
            "downloadAcademicWorkbookTemplate",
            "importAcademicWorkbook",
            "buildAcademicWorkbookImportImpact",
            "academicWorkbookImportNotice",
            "academic-import-impact",
            "风险变化",
            "保存后才会进入正式配置",
            "table_count",
            "row_count",
            "persisted",
            "False",
        ),
    )
    checks.append(
        AcceptanceCheck(
            "academic_affairs_workbook_io",
            "教务工作台应支持多张业务表在同一个 Excel 工作簿中迁移：可下载全量工作簿模板、批量导入多表到页面核对并重算风险，且导入不能自动保存。",
            (
                "scheduler/app/academic_affairs_io.py",
                "scheduler/app/web.py",
                "scheduler/app/static/index.html",
                "scheduler/app/static/app.js",
            ),
            "pass" if ok else "fail",
            ("教务工作台提供全量工作簿模板和多表导入预览，后端返回 persisted=false。",) if ok else tuple(),
            gap="" if ok else f"教务全量工作簿导入闭环缺少：{', '.join(missing)}",
        )
    )

    ok, missing = _contains_all(
        access_control + "\n" + web_py + "\n" + app_html + "\n" + app_js + "\n" + app_css + "\n" + access_control_tests,
        (
            "ROLE_DEFINITIONS",
            "academic_admin",
            "grade_lead",
            "dorm_supervisor",
            "viewer",
            "PermissionDenied",
            "assert_request_allowed",
            "/api/access/context",
            "X-Scheduler-Role",
            "accessRoleSelect",
            "只读查看",
            "applyAccessPermissions",
            "campus_scope",
            "campuses",
            "test_viewer_is_read_only_for_write_endpoints",
        ),
    )
    checks.append(
        AcceptanceCheck(
            "school_role_access_control",
            "商业化部署应具备学校/校区范围和角色权限边界：至少能区分教务管理员、年级组、宿管值周和只读查看，并阻止低权限角色误保存核心配置或启动求解。",
            (
                "scheduler/app/access_control.py",
                "scheduler/app/web.py",
                "scheduler/app/static/index.html",
                "scheduler/app/static/app.js",
                "verification/fixes/tests/test_access_control.py",
            ),
            "pass" if ok else "fail",
            ("Web 增加工作台身份上下文，请求头携带角色，后端按角色阻止越权写入并暴露校区范围。",) if ok else tuple(),
            gap="" if ok else f"角色权限/校区范围闭环缺少：{', '.join(missing)}",
        )
    )

    solve_readiness_tests = _read_text(repo_root / "verification" / "fixes" / "tests" / "test_solve_readiness.py")
    ok, missing = _contains_all(
        readiness + "\n" + solve_readiness_tests,
        (
            "_academic_leave_log_substitution_items",
            "请假日志代课建议",
            "academic.review_leave_log_substitutes",
            "同年级同学科",
            "非同年级同学科",
            "请假日志只记录事件",
            "局部调课只更新确认后的调整版全局课表",
            "test_readiness_recommends_substitutes_from_leave_log_without_blocking_solver",
        ),
    )
    checks.append(
        AcceptanceCheck(
            "academic_affairs_leave_log_substitution",
            "教务工作台中的教师请假应作为教务日志记录项，触发同年级同学科优先的代课建议，但不能自动写入硬禁排或触发全量重排。",
            (
                "scheduler/app/readiness.py",
                "verification/fixes/tests/test_solve_readiness.py",
            ),
            "pass" if ok else "fail",
            ("已审批/已确认请假日志会给出同年级同学科、非同年级同学科两级代课候选，且不阻断求解。",) if ok else tuple(),
            gap="" if ok else f"请假日志代课建议缺少：{', '.join(missing)}",
        )
    )

    local_repair = _read_text(repo_root / "scheduler" / "app" / "local_timetable_repair.py")
    local_repair_tests = _read_text(repo_root / "verification" / "fixes" / "tests" / "test_leave_log_local_repair.py")
    ok, missing = _contains_all(
        local_repair + "\n" + web_py + "\n" + solve_service + "\n" + app_js + "\n" + local_repair_tests,
        (
            "preview_leave_substitution_repair",
            "apply_leave_substitution_repair",
            "请假代课局部最小影响调课",
            "affected_teacher_schedules",
            "local_timetable_repairs",
            "/api/academic-affairs/leave-repair/preview",
            "/api/academic-affairs/leave-repair/apply",
            "应用到全局课表",
            "test_leave_log_local_repair_moves_substitute_conflict_with_minimal_teacher_impact",
        ),
    )
    checks.append(
        AcceptanceCheck(
            "leave_log_local_timetable_repair",
            "请假日志确认代课教师后，应能在代课教师撞课时给出局部最小影响调课方案，展示涉及教师变更前后课表，并生成调整后的全局课表。",
            (
                "scheduler/app/local_timetable_repair.py",
                "scheduler/app/solve_service.py",
                "scheduler/app/web.py",
                "scheduler/app/static/app.js",
                "verification/fixes/tests/test_leave_log_local_repair.py",
            ),
            "pass" if ok else "fail",
            ("系统能移动代课教师自身冲突课、输出涉及教师课表，并把局部调课版全局课表挂回当前结果。",) if ok else tuple(),
            gap="" if ok else f"请假日志局部调课闭环缺少：{', '.join(missing)}",
        )
    )

    manual_adjustment_tests = _read_text(repo_root / "verification" / "fixes" / "tests" / "test_manual_timetable_adjustment.py")
    ok, missing = _contains_all(
        manual_adjustment + "\n" + web_py + "\n" + solve_service + "\n" + result_preview + "\n" + app_html + "\n" + app_js + "\n" + app_css + "\n" + manual_adjustment_tests,
        (
            "preview_manual_timetable_adjustment",
            "apply_manual_timetable_adjustment",
            "scheduler.manual_timetable_adjustment.v1",
            "affected_class_schedules",
            "affected_teacher_schedules",
            "local_timetable_adjustments",
            "local_timetable_adjustment",
            "/api/academic-affairs/timetable-adjustment/preview",
            "/api/academic-affairs/timetable-adjustment/apply",
            "课表微调沙盘",
            "renderManualAdjustmentTool",
            "test_manual_timetable_adjustment_swaps_occupied_slot_and_updates_global_schedule",
        ),
    )
    checks.append(
        AcceptanceCheck(
            "manual_timetable_adjustment_sandbox",
            "普通调课单也应形成预览影响、最小改动、涉及班级/教师课表对比和更新全局课表的闭环，而不是只停留在记录和风险提示。",
            (
                "scheduler/app/local_timetable_adjustment.py",
                "scheduler/app/solve_service.py",
                "scheduler/app/web.py",
                "scheduler/app/result_preview.py",
                "scheduler/app/static/index.html",
                "scheduler/app/static/app.js",
                "scheduler/app/static/styles.css",
                "verification/fixes/tests/test_manual_timetable_adjustment.py",
            ),
            "pass" if ok else "fail",
            ("课表微调沙盘支持选择调课单或直接填课位，预览并应用同班换课/移课，更新活动全局课表。",) if ok else tuple(),
            gap="" if ok else f"普通课表微调闭环缺少：{', '.join(missing)}",
        )
    )

    ok, missing = _contains_all(
        config_service + "\n" + web_py + "\n" + app_js,
        (
            "_build_academic_affairs_changes",
            "academic_affairs.save",
            'store="academic_affairs"',
            'path=["tables", str(table_key)]',
            "row_count_before",
            "row_count_after",
            "formatAuditChangeValue",
            "actor",
            "reason",
        ),
    )
    checks.append(
        AcceptanceCheck(
            "academic_affairs_change_audit",
            "教务扩展表正式保存应进入可追溯、可撤回的变更记录，避免真实学校表格流转后无法定位责任和回退误操作。",
            (
                "scheduler/app/config_service.py",
                "scheduler/app/web.py",
                "scheduler/app/static/app.js",
            ),
            "pass" if ok else "fail",
            ("教务保存写入 change_audit，记录 actor/source/reason、表级前后行数，并复用配置撤回链路。",) if ok else tuple(),
            gap="" if ok else f"教务保存审计闭环缺少：{', '.join(missing)}",
        )
    )

    ok, missing = _contains_all(
        config_service + "\n" + web_py + "\n" + app_js,
        (
            "base_data.teacher_subjects.save",
            "base_data.day_rules.save",
            "教师定位表",
            "白天规则表",
            'path=["web_tables", "teacher_subjects"]',
            'path=["web_tables", "day_rules", table_key]',
            "row_count_before",
            "formatAuditChangeValue",
        ),
    )
    checks.append(
        AcceptanceCheck(
            "base_data_change_audit",
            "教师定位表和白天规则基础表保存应进入可追溯、可撤回的变更记录，避免排课基础数据误改后无法定位责任或恢复。",
            (
                "scheduler/app/config_service.py",
                "scheduler/app/web.py",
                "scheduler/app/static/app.js",
            ),
            "pass" if ok else "fail",
            ("教师定位表和白天规则表保存写入 change_audit，记录表级前后行数，并复用配置撤回链路。",) if ok else tuple(),
            gap="" if ok else f"基础数据保存审计闭环缺少：{', '.join(missing)}",
        )
    )

    ok, missing = _contains_all(
        config_service + "\n" + web_py + "\n" + app_html + "\n" + app_js,
        (
            "build_teacher_subject_template_csv",
            "parse_teacher_subject_csv",
            "parse_teacher_subject_xlsx",
            "/api/teacher-subjects/template",
            "/api/teacher-subjects/import-file",
            "downloadTeacherCsvTemplate",
            "importTeacherFile",
            "teacherImportNotice",
            "persisted",
            "False",
        ),
    )
    checks.append(
        AcceptanceCheck(
            "teacher_subject_bulk_io",
            "教师定位表应支持学校常见 Excel/CSV 表格流转：可下载模板、导入到页面核对，且导入不能绕过人工保存确认。",
            (
                "scheduler/app/config_service.py",
                "scheduler/app/web.py",
                "scheduler/app/static/index.html",
                "scheduler/app/static/app.js",
            ),
            "pass" if ok else "fail",
            ("教师定位表提供 Excel/CSV 模板下载和导入预览，后端返回 persisted=false。",) if ok else tuple(),
            gap="" if ok else f"教师定位表 Excel/CSV 模板/导入闭环缺少：{', '.join(missing)}",
        )
    )

    ok, missing = _contains_all(
        service_py + "\n" + web_py + "\n" + joint_solver,
        (
            "BEST_SOLUTION_FILENAMES",
            "最终全局最优解_正式版.xlsx",
            "多解诊断报告.xlsx",
            "DAY_SCHEDULE_PATTERN",
            "RESULT_PREVIEW_PATHS",
            "/api/result-preview",
            'grade_prefix: str = "高二"',
            "上午1",
            "下午1",
        ),
    )
    checks.append(
        AcceptanceCheck(
            "legacy_result_lookup_compatibility",
            "旧后端和旧页面入口不能在结果真实存在时因为中文文件名、旧预览路由或乱码默认值误报没有结果文件。",
            (
                "scheduler/app/service.py",
                "scheduler/app/web.py",
                "scheduler/joint_solver.py",
            ),
            "pass" if ok else "fail",
            ("旧 RunResult 识别中文课表/诊断文件，结果预览保留兼容路由，遗留中文默认值可读。",) if ok else tuple(),
            gap="" if ok else f"旧结果路径兼容闭环缺少：{', '.join(missing)}",
        )
    )

    ok, missing = _contains_all(
        config_service + "\n" + web_py + "\n" + app_html + "\n" + app_js,
        (
            "build_day_rule_table_template_csv",
            "build_day_rule_table_template_xlsx",
            "parse_day_rule_table_csv",
            "parse_day_rule_table_xlsx",
            "/api/day-rules/template",
            "/api/day-rules/import-file",
            "downloadDayRuleTemplate",
            "importDayRuleFile",
            "dayRuleImportNotice",
            "persisted",
            "False",
        ),
    )
    checks.append(
        AcceptanceCheck(
            "day_rule_bulk_io",
            "白天规则基础表应支持学校常见 Excel/CSV 表格流转：可下载当前表模板、导入当前表到页面核对，且导入不能绕过人工保存确认。",
            (
                "scheduler/app/config_service.py",
                "scheduler/app/web.py",
                "scheduler/app/static/index.html",
                "scheduler/app/static/app.js",
            ),
            "pass" if ok else "fail",
            ("白天规则表提供 Excel/CSV 模板下载和导入预览，后端返回 persisted=false。",) if ok else tuple(),
            gap="" if ok else f"白天规则 Excel/CSV 模板/导入闭环缺少：{', '.join(missing)}",
        )
    )

    checks.append(
        _check_exists(
            repo_root,
            check_id="delivery_safety_and_release_docs",
            requirement="商业交付应避免把排障材料误当正式课表，并保留当前项目说明、平台计划和工程卫生记录。",
            artifacts=(
                "README.md",
                "ARCHITECTURE.md",
                "docs/k12_platform_execution_plan.md",
                "verification/fixes/output_path_policy.md",
                "verification/fixes/excel_export_policy.md",
                "verification/fixes/engineering_hygiene.md",
            ),
            evidence_when_ok=("当前项目说明、架构说明、平台计划、输出路径、Excel 策略和工程卫生记录存在。",),
        )
    )

    ok, missing = _contains_all(
        gate_manifest,
        (
            "test_solve_readiness.py",
            "test_publish_assessment.py",
            "test_delivery_manifest.py",
            "test_result_preview.py",
            "test_manual_timetable_adjustment.py",
            "test_access_control.py",
            "test_ai_or_framework.py",
            "test_diagnostic_relaxation.py",
            "test_k12_academic_affairs_expansion.py",
            "test_engineering_hygiene.py",
            "test_module_decomposition.py",
        ),
    )
    checks.append(
        AcceptanceCheck(
            "verification_gate_coverage",
            "验证门禁应覆盖求解前校验、发布评估、交付清单、结果预览、诊断放宽、教务对象、工程卫生和模块拆分。",
            ("verification/fixes/gate_manifest.py", "verification/fixes/run_dev_gate.ps1"),
            "pass" if ok else "fail",
            ("开发门禁清单覆盖商业化关键回归测试。",) if ok else tuple(),
            gap="" if ok else f"开发门禁缺少：{', '.join(missing)}",
        )
    )

    status = current_status if current_status is not None else _status_for_recommended_candidate(_latest_status(repo_root, include_diagnostic=False))
    ok, evidence, gap, formal_release_ready = _status_publishable(status, strict_release=strict_release)
    checks.append(
        AcceptanceCheck(
            "current_publishable_schedule",
            "商业交付前必须有当前配置下的正式可行课表、至少一个可行解、至少一个课表文件，并通过发布评估。"
            + ("严格发布模式沿用当前发布评估；风险提示不再单独阻断。" if strict_release else ""),
            ("outputs/web_runs/*/status.json",),
            "pass" if ok else "blocked",
            evidence,
            gap=gap,
            severity="release_blocker",
        )
    )

    package_ok, package_evidence, package_gap = _current_package_contract(status)
    checks.append(
        AcceptanceCheck(
            "current_result_package_contract",
            "当前结果包必须能作为学校交付包使用：ZIP 根目录包含 delivery_manifest.json 和唯一 status.json，携带 result_availability 与 solve_diagnostics，并通过包完整性校验。",
            ("outputs/web_runs/*/result_package.zip",),
            "pass" if package_ok else "blocked",
            package_evidence,
            gap=package_gap,
            severity="release_blocker",
        )
    )

    structural_failures = [check for check in checks if check.status == "fail"]
    release_blockers = [check for check in checks if check.status == "blocked"]
    if structural_failures:
        overall = "fail"
    elif release_blockers:
        overall = "blocked"
    else:
        overall = "pass"
    capability_goal_complete = overall == "pass"
    formal_release_complete = not structural_failures and formal_release_ready

    return {
        "overall": overall,
        "summary": {
            "total": len(checks),
            "pass": sum(1 for check in checks if check.status == "pass"),
            "fail": len(structural_failures),
            "blocked": len(release_blockers),
            "capability_goal_complete": capability_goal_complete,
            "formal_release_complete": formal_release_complete,
            "commercial_goal_complete": capability_goal_complete if not strict_release else formal_release_complete,
            "strict_release": strict_release,
        },
        "checks": [asdict(check) for check in checks],
    }


def _format_text(report: dict[str, Any]) -> str:
    lines = [
        "# Commercial Acceptance Audit",
        f"overall: {report['overall']}",
        (
            "summary: "
            f"{report['summary']['pass']} pass, "
            f"{report['summary']['fail']} fail, "
            f"{report['summary']['blocked']} blocked"
        ),
        (
            "completion: "
            f"capability_goal_complete={str(report['summary'].get('capability_goal_complete', False)).lower()}, "
            f"formal_release_complete={str(report['summary'].get('formal_release_complete', False)).lower()}, "
            f"commercial_goal_complete={str(report['summary'].get('commercial_goal_complete', False)).lower()}"
        ),
        "",
    ]
    for check in report["checks"]:
        lines.append(f"- [{check['status']}] {check['id']}")
        lines.append(f"  requirement: {check['requirement']}")
        if check["evidence"]:
            lines.append(f"  evidence: {'; '.join(check['evidence'])}")
        if check["gap"]:
            lines.append(f"  gap: {check['gap']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit commercial readiness against project artifacts.")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of text.")
    parser.add_argument(
        "--strict-release",
        action="store_true",
        help="Return non-zero when the current run is not publishable.",
    )
    args = parser.parse_args(argv)
    report = build_audit(REPO_ROOT, strict_release=args.strict_release)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(_format_text(report))
    if report["overall"] == "fail":
        return 1
    if args.strict_release and report["overall"] != "pass":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

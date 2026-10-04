# Output Path Policy Audit (R-05)

## Scan Scope
- Commands:
  - `rg -n 'Path\\("outputs"\\)|base_dir\\.parent / output_cfg|outputs/' scheduler -S`
  - `python -m scheduler.smoke_check`
  - `Test-Path scheduler\\outputs`

## Policy
- Project runtime artifacts use the project-root `outputs/` directory.
- Relative output paths from YAML, Web runtime overrides, smoke checks, snapshot export, solution archive, warm-start files, and result file names must be resolved from the project root.
- `scheduler/outputs/` is not a valid runtime output root. It is rejected by path policy helpers and by pre-run cleanup safety checks.

## Implementation Evidence
- `scheduler/output_paths.py` owns:
  - `project_output_dir()` for the canonical project-root output folder.
  - `resolve_project_path(...)` for project-root resolution of relative output-like paths.
  - `resolve_output_dir(...)` for `io.output.dir` resolution.
  - `is_scheduler_outputs_path(...)` for explicit rejection of package-local outputs.
- Core runtime entrypoints now use the policy helpers:
  - `scheduler/app/service.py`
  - `scheduler/main.py`
  - `scheduler/joint_solver.py`
  - `scheduler/day_reader_smoke_test.py`
  - `scheduler/smoke_check.py`
  - `scheduler/solver_callbacks/timed_snapshot_callback.py`
- Tiny diagnostic smoke scripts now use `project_output_dir()` instead of `Path("outputs")`.

## Verification
- `pytest -q verification/fixes/tests/test_output_path_policy.py verification/fixes/tests/test_pre_run_cleanup_guard.py ...`
  - Result: path-policy subset passed.
- `python scheduler/tests/governance_regression.py`
  - Result: passed.
- `python -m scheduler.smoke_check`
  - Result: passed.
- `Test-Path scheduler\\outputs`
  - Result: absent in the current workspace after smoke check.

## Conclusion
- `outputs/` remains the single canonical runtime artifact root.
- `scheduler/outputs/` is guarded against future accidental writes or cleanup targeting.

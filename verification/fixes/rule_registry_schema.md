# Rule Registry And Snapshot Schema

## Scope
- The rule registry is an audit and trace registry only.
- It records effective enable switches, modes, weights, stages, order, and callable symbols for snapshots and migration audits.
- It does not decide whether solver constraints execute. Current solver entrypoints still call constraint functions directly, and those call sites remain the execution source of truth.
- `select_enabled_rules_for_audit(...)` is the preferred helper name for audit row selection. `apply_enabled_rules(...)` remains as a compatibility alias and must not be interpreted as runtime gating.

## RuleSpec
- `rule_id`: stable immutable identifier.
- `name`: display label.
- `category_path`: taxonomy path.
- `tags`: mode/group tags for filtering.
- `default_mode`: `hard|soft`.
- `default_weight`: default penalty weight.
- `config_key`: config reference.
- `enabled_path`: effective-config path for enable switch.
- `mode_path`: effective-config path for `hard|soft` override.
- `weight_path`: effective-config path for weight override.
- `explanation_template`: human-readable summary template.
- `stage`: assembly stage (`vars|constraints|objective_post`).
- `order`: stage-local execution order.
- `apply_fn_ref`: callable symbol name.

## Effective Rule Row (`effective_rules_snapshot.json`)
- `timestamp`
- `mode`
- `run_id`
- `git_commit`
- `rules`: list of
  - `rule_id`
  - `name`
  - `category_path`
  - `stage`
  - `order`
  - `tags`
  - `config_key`
  - `enabled`
  - `mode`
  - `weight`
  - `explanation_template`
  - `apply_fn_name`
  - `enabled_path`
  - `mode_path`
  - `weight_path`

## Applied Rule Trace (`applied_rules_trace.json`)
- `timestamp`
- `mode`
- `run_id`
- `git_commit`
- `trace`: call-order list, each item includes
  - `timestamp`
  - `mode`
  - `run_id`
  - `rule_id`
  - `name`
  - `stage`
  - `order`
  - `enabled`
  - `rule_mode`
  - `weight`
  - `callable`
  - `status` (`ok|error`)
  - `error` (only when status is `error`)

## Solver Params Snapshot (`solver_params_snapshot.json`)
- `timestamp`
- `mode`
- `run_id`
- `git_commit`
- `solver_params`
  - `active_for_mode`
  - `day_joint.time_limit_seconds/workers/random_seed`
  - `night.time_limit_seconds/workers/random_seed`

## Inputs Fingerprint (`inputs_fingerprint.json`)
- `timestamp`
- `mode`
- `run_id`
- `git_commit`
- `inputs`: list of
  - `label`
  - `path`
  - `exists`
  - `size_bytes`
  - `mtime`
  - `sha256`

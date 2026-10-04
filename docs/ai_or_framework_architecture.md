# AI-first OR Framework Architecture

## Purpose

This repository is being moved from a scheduler-specific project to a rule-first optimization framework for AI agents. Scheduling remains a reference domain, but the generic API must be able to represent any CP-SAT-friendly discrete optimization problem.

## Required Agent Flow

```text
Business Expert Agent (human)
  -> Chief Architect Agent
    -> Mathematical Modeling Agent
    -> Mathematical Reduction and Optimization Agent
      -> Code Generation and Execution Agent
        -> Log Diagnostics Debug Agent
```

The machine-readable default is implemented by `build_default_agent_architecture()`.

## Rule-first Contract

Every model artifact must be attached to a rule:

- hard rules define feasibility;
- soft rules define objective terms, penalties, or tie-breakers;
- constraints reference `rule_id`;
- objectives reference `rule_id`;
- solver execution records the rule order before adding model terms.

This keeps AI-generated code auditable. A Debug Agent can point a bad result back to a business rule instead of reverse-engineering anonymous OR-Tools constraints.

## Current Generic Kernel

`ai_orchestrated_optimization/` currently includes:

- `agents.py`: canonical Agent roles and handoffs.
- `contracts.py`: variables, intervals, rules, linear constraints/domains, enforced linear constraints, boolean logic, table constraints, Element, Automaton, Inverse, Circuit, MultipleCircuit, AllDifferent, NoOverlap, NoOverlap2D, Cumulative, Reservoir, arithmetic equality constraints, objectives, solver controls, and problem specs.
- `orchestration.py`: human natural-language brief, Agent handoff artifacts, required-handoff validation, rule-first solve execution, generated OR-Tools log handoff, and Debug Agent report.
- `planning.py`: rule-first ordering.
- `cp_sat_backend.py`: OR-Tools CP-SAT backend for bool/int variables, linear constraints/domains, enforced linear constraints, boolean logic, Allowed/Forbidden Assignments, Element, Automaton, Inverse, Circuit, MultipleCircuit, AllDifferent, Interval, NoOverlap, NoOverlap2D, Cumulative, Reservoir, arithmetic equality constraints, linear objectives, solver parameters, hints, assumptions, decision strategies, response stats, and infeasible assumption cores.

The first non-scheduling proofs are in `test_ai_or_framework.py`: assignment uses bool variables and linear constraints, while additional examples use boolean logic, tables, Element, Automaton, Inverse, Circuit, MultipleCircuit, AllDifferent, Interval, NoOverlap, NoOverlap2D, Cumulative, Reservoir, arithmetic equality constraints, hints, assumptions, decision strategies, and solver parameters through the same rule-first plan.

`test_ai_or_orchestration.py` proves the AI workflow layer: a human-language `BusinessBrief` and required Agent handoff artifacts produce a CP-SAT solve report with rule traces and a generated `ortools_run_logs` artifact; incomplete Agent handoffs block execution before OR-Tools runs.

## Migration Path

1. Keep `scheduler/` as an example domain while the generic kernel stabilizes.
2. Use `scheduler.rules.generic_bridge` to lift existing `RuleExecutionPlan` artifacts into generic `RuleSpec`, `RuleFirstPlan`, and `OptimizationProblemSpec` shadow models.
3. Route legacy scheduler solver controls through `CpSatSolveConfig` and `apply_cp_sat_solve_config`, so real `CpSolver` runs use the same AI OR control surface as generic problems.
4. Migrate small direct CP-SAT subsystems first; `scheduler.app.conflict_detection` now uses generic `OptimizationProblemSpec` plus enforced linear constraints for assumption-core conflict diagnosis.
5. Move legacy scheduler constraint call sites from audit-only rule metadata toward executable generic constraints.
6. Add more generic examples: knapsack/bin packing, coverage, routing-like decompositions, optional intervals with active reservoirs, and 2D/VRP-scale decomposition models that CP-SAT can express.
7. Teach Agent prompts to generate only through the contract and orchestration layers, never by editing solver internals first.

## Scheduler Bridge Contract Strength

The scheduler bridge deliberately exposes two coverage strengths:

- `exact_cp_sat_shape_contract`: a legacy rule has an executable generic CP-SAT contract with parity-style tests for its constraint/objective shape.
- `catalog_contract`: a legacy rule family is present in the rule-first registry/config catalog, but the bridge is a migration catalog and does not claim exact CP-SAT constraint parity yet.

Release audits report both counts. AI agents must treat `catalog_contract` as a migration target, not as proof that the old scheduler branch can be removed.

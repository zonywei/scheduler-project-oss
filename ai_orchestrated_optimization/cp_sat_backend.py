# -*- coding: utf-8 -*-
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Iterator, Mapping

from ortools.sat.python import cp_model

from ai_orchestrated_optimization.contracts import (
    AbsEqualityConstraintSpec,
    AllDifferentConstraintSpec,
    AllowedAssignmentsConstraintSpec,
    AtLeastOneConstraintSpec,
    AtMostOneConstraintSpec,
    AutomatonConstraintSpec,
    BoolAndConstraintSpec,
    BoolLiteral,
    BoolLiteralSpec,
    BoolOrConstraintSpec,
    BoolXorConstraintSpec,
    CircuitConstraintSpec,
    ConstraintSpec,
    CpSatSolveConfig,
    CumulativeConstraintSpec,
    DecisionStrategySpec,
    DivisionEqualityConstraintSpec,
    ElementConstraintSpec,
    ExactlyOneConstraintSpec,
    ForbiddenAssignmentsConstraintSpec,
    ImplicationConstraintSpec,
    IntervalSpec,
    InverseConstraintSpec,
    LinearConstraintSpec,
    LinearExpressionInDomainConstraintSpec,
    LinearExpression,
    MapDomainConstraintSpec,
    MaxEqualityConstraintSpec,
    MinEqualityConstraintSpec,
    ModuloEqualityConstraintSpec,
    MultipleCircuitConstraintSpec,
    MultiplicationEqualityConstraintSpec,
    NoOverlap2DConstraintSpec,
    NoOverlapConstraintSpec,
    OptimizationProblemSpec,
    ReservoirConstraintSpec,
    SolutionHintSpec,
    SolverParameterSpec,
    SolverParameterValue,
)
from ai_orchestrated_optimization.planning import build_rule_first_plan


_CP_MODEL_RULE_CONTEXT: ContextVar[dict[str, Any] | None] = ContextVar(
    "ai_or_cp_model_rule_context",
    default=None,
)


@dataclass(frozen=True)
class CpSatSolution:
    status_name: str
    objective_value: float | None
    values: dict[str, int]
    applied_constraints: tuple[str, ...]
    rule_application_order: tuple[str, ...]
    solver_parameters: dict[str, SolverParameterValue] = field(default_factory=dict)
    solution_hints: dict[str, int] = field(default_factory=dict)
    assumptions: tuple[str, ...] = ()
    assumption_core: tuple[str, ...] = ()
    decision_strategy_count: int = 0
    response_stats: str = ""
    wall_time_seconds: float = 0.0
    num_conflicts: int = 0
    num_branches: int = 0
    best_objective_bound: float | None = None


@dataclass(frozen=True)
class ExistingCpModelSolveResult:
    solver: Any
    # Keep the native OR-Tools status object.  New releases return a
    # CpSolverStatus enum and StatusName() needs that enum rather than int().
    status: Any
    status_name: str
    solver_parameters: dict[str, SolverParameterValue] = field(default_factory=dict)
    operation_trace: tuple["ExistingCpModelOperation", ...] = ()
    operation_summary_by_rule: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class ExistingCpModelOperation:
    sequence: int
    operation: str
    rule_id: str | None = None
    role_id: str | None = None
    source: str | None = None
    model_id: str | None = None


class RuleAwareCpModelAdapter:
    """Delegating CpModel adapter that records legacy operations by rule context."""

    _TRACE_PREFIXES = ("Add", "New")
    _TRACE_NAMES = {"Minimize", "Maximize", "ClearObjective"}

    def __init__(self, model_id: str | None = None) -> None:
        self._ai_or_inner_model = cp_model.CpModel()
        self._ai_or_operation_trace: list[ExistingCpModelOperation] = []
        self.ai_or_model_factory = "existing_cp_model"
        self.ai_or_model_id = str(model_id) if model_id is not None else None

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._ai_or_inner_model, name)
        if callable(attr) and self._should_trace(name):
            def _tracked(*args: Any, **kwargs: Any) -> Any:
                result = attr(*args, **kwargs)
                self._record_operation(name)
                return result

            return _tracked
        return attr

    def __repr__(self) -> str:
        return f"RuleAwareCpModelAdapter(model_id={self.ai_or_model_id!r})"

    def _should_trace(self, name: str) -> bool:
        return name in self._TRACE_NAMES or any(name.startswith(prefix) for prefix in self._TRACE_PREFIXES)

    def _record_operation(self, operation: str) -> None:
        context = _CP_MODEL_RULE_CONTEXT.get() or {}
        self._ai_or_operation_trace.append(
            ExistingCpModelOperation(
                sequence=len(self._ai_or_operation_trace) + 1,
                operation=str(operation),
                rule_id=_optional_text(context.get("rule_id")),
                role_id=_optional_text(context.get("role_id")),
                source=_optional_text(context.get("source")),
                model_id=self.ai_or_model_id,
            )
        )


@contextmanager
def ai_or_model_rule_context(
    rule_id: str,
    *,
    role_id: str | None = None,
    source: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> Iterator[dict[str, Any]]:
    context = {
        "rule_id": str(rule_id),
        "role_id": role_id,
        "source": source,
        "metadata": dict(metadata or {}),
    }
    token = _CP_MODEL_RULE_CONTEXT.set(context)
    try:
        yield context
    finally:
        _CP_MODEL_RULE_CONTEXT.reset(token)


def create_existing_cp_model(model_id: str | None = None) -> RuleAwareCpModelAdapter:
    return RuleAwareCpModelAdapter(model_id)


def unwrap_existing_cp_model(model: Any) -> Any:
    return getattr(model, "_ai_or_inner_model", model)


def get_existing_cp_model_operation_trace(model: Any) -> tuple[ExistingCpModelOperation, ...]:
    trace = getattr(model, "_ai_or_operation_trace", None)
    if trace is None:
        return ()
    return tuple(trace)


def get_existing_cp_model_operation_count(model: Any) -> int:
    return len(get_existing_cp_model_operation_trace(model))


def summarize_existing_cp_model_operations_by_rule(model: Any) -> dict[str, dict[str, Any]]:
    summary: dict[str, dict[str, Any]] = {}
    for item in get_existing_cp_model_operation_trace(model):
        rule_id = item.rule_id or "__unscoped__"
        row = summary.setdefault(rule_id, {"operation_count": 0, "operations": {}})
        row["operation_count"] += 1
        operations = row["operations"]
        operations[item.operation] = int(operations.get(item.operation, 0)) + 1
    return {
        rule_id: {
            "operation_count": int(row["operation_count"]),
            "operations": dict(sorted(row["operations"].items())),
        }
        for rule_id, row in sorted(summary.items())
    }


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def solve_cp_sat_problem(problem: OptimizationProblemSpec, *, time_limit_seconds: int | float = 30) -> CpSatSolution:
    model = cp_model.CpModel()
    variables = _create_variables(model, problem)
    intervals = _create_intervals(model, problem.intervals, variables)
    objective_rule_id = problem.objective.rule_id if problem.objective is not None else None
    plan = build_rule_first_plan(
        rules=problem.rules,
        constraints=problem.constraints,
        objective_rule_id=objective_rule_id,
    )

    applied_constraints: list[str] = []
    for item in plan.constraint_order:
        _add_constraint(model, item.constraint, variables, intervals)
        applied_constraints.append(item.constraint.name)

    if problem.objective is not None:
        objective = _linear_expression(problem.objective.expression, variables)
        if problem.objective.sense == "minimize":
            model.Minimize(objective)
        elif problem.objective.sense == "maximize":
            model.Maximize(objective)
        else:
            raise ValueError(f"unsupported objective sense {problem.objective.sense!r}")

    solve_config = problem.solve_config
    solution_hints = _apply_solution_hints(model, solve_config.hints, variables)
    assumptions = _apply_assumptions(model, solve_config.assumptions, variables)
    decision_strategy_count = _apply_decision_strategies(
        model,
        solve_config.decision_strategies,
        variables,
    )
    solver = cp_model.CpSolver()
    solver_parameters = apply_cp_sat_solve_config(
        solver,
        solve_config,
        time_limit_seconds=time_limit_seconds,
    )
    status = solver.Solve(model)
    status_name = solver.StatusName(status)
    values = {}
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        values = {name: int(solver.Value(var)) for name, var in variables.items()}
    objective_value: float | None = None
    if problem.objective is not None and values:
        objective_value = float(solver.ObjectiveValue())
    return CpSatSolution(
        status_name=status_name,
        objective_value=objective_value,
        values=values,
        applied_constraints=tuple(applied_constraints),
        rule_application_order=tuple(item.rule_id for item in plan.rule_order),
        solver_parameters=solver_parameters,
        solution_hints=solution_hints,
        assumptions=assumptions,
        assumption_core=_assumption_core_names(solver, solve_config.assumptions, variables),
        decision_strategy_count=decision_strategy_count,
        response_stats=solver.ResponseStats(),
        wall_time_seconds=float(solver.WallTime()),
        num_conflicts=int(solver.NumConflicts()),
        num_branches=int(solver.NumBranches()),
        best_objective_bound=_best_objective_bound(solver, problem),
    )


def solve_existing_cp_model(
    model: Any,
    solve_config: CpSatSolveConfig | None = None,
    *,
    time_limit_seconds: int | float | None = None,
    solution_callback: Any | None = None,
) -> ExistingCpModelSolveResult:
    solver = cp_model.CpSolver()
    solver_parameters = apply_cp_sat_solve_config(
        solver,
        solve_config,
        time_limit_seconds=time_limit_seconds,
    )
    setattr(solver, "ai_or_execution_adapter", "existing_cp_model")
    solver_model = unwrap_existing_cp_model(model)
    # OR-Tools 9.15 removed ``SolveWithSolutionCallback`` from CpSolver and
    # folded callback support into ``solve(model, callback)``.  Prefer the
    # current API while retaining compatibility with older supported builds.
    solve_method = getattr(solver, "solve", None)
    if callable(solve_method):
        status = solve_method(solver_model, solution_callback)
    elif solution_callback is None:
        status = solver.Solve(solver_model)
    else:  # pragma: no cover - exercised only by older OR-Tools releases.
        status = solver.SolveWithSolutionCallback(solver_model, solution_callback)
    return ExistingCpModelSolveResult(
        solver=solver,
        status=status,
        status_name=solver.StatusName(status),
        solver_parameters=solver_parameters,
        operation_trace=get_existing_cp_model_operation_trace(model),
        operation_summary_by_rule=summarize_existing_cp_model_operations_by_rule(model),
    )


def apply_cp_sat_solve_config(
    solver: cp_model.CpSolver,
    solve_config: CpSatSolveConfig | None = None,
    *,
    time_limit_seconds: int | float | None = None,
) -> dict[str, SolverParameterValue]:
    config = solve_config or CpSatSolveConfig()
    solver_parameters: dict[str, SolverParameterValue] = {}
    if time_limit_seconds is not None:
        solver.parameters.max_time_in_seconds = float(time_limit_seconds)
        solver_parameters["max_time_in_seconds"] = float(time_limit_seconds)
    solver_parameters.update(_apply_solver_parameters(solver, config.parameters))
    setattr(solver, "ai_or_applied_solver_parameters", dict(solver_parameters))
    return solver_parameters


def _apply_solver_parameters(
    solver: cp_model.CpSolver,
    parameter_specs: tuple[SolverParameterSpec, ...],
) -> dict[str, SolverParameterValue]:
    applied: dict[str, SolverParameterValue] = {}
    for spec in parameter_specs:
        name = str(spec.name or "").strip()
        if not name:
            raise ValueError("solver parameter name is required")
        if not hasattr(solver.parameters, name):
            raise ValueError(f"unsupported solver parameter {name!r}")
        setattr(solver.parameters, name, _solver_parameter_value(spec.value))
        applied[name] = spec.value
    return applied


def _solver_parameter_value(value: SolverParameterValue) -> Any:
    if isinstance(value, str):
        text = value.strip()
        if hasattr(cp_model, text):
            return getattr(cp_model, text)
        if text.lower() == "true":
            return True
        if text.lower() == "false":
            return False
        return value
    return value


def _apply_solution_hints(
    model: cp_model.CpModel,
    hints: tuple[SolutionHintSpec, ...],
    variables: dict[str, Any],
) -> dict[str, int]:
    applied: dict[str, int] = {}
    for hint in hints:
        variable_name = str(hint.variable or "").strip()
        if not variable_name:
            raise ValueError("solution hint variable name is required")
        model.AddHint(_variable_ref(variable_name, variables), int(hint.value))
        applied[variable_name] = int(hint.value)
    return applied


def _apply_assumptions(
    model: cp_model.CpModel,
    assumptions: tuple[BoolLiteral, ...],
    variables: dict[str, Any],
) -> tuple[str, ...]:
    if assumptions:
        model.AddAssumptions(tuple(_literal_ref(literal, variables) for literal in assumptions))
    return tuple(_literal_name(literal) for literal in assumptions)


def _apply_decision_strategies(
    model: cp_model.CpModel,
    strategies: tuple[DecisionStrategySpec, ...],
    variables: dict[str, Any],
) -> int:
    for strategy in strategies:
        if not strategy.variables:
            raise ValueError("decision strategy variables are required")
        model.AddDecisionStrategy(
            tuple(_variable_ref(name, variables) for name in strategy.variables),
            _cp_model_constant(strategy.variable_selection, "variable selection"),
            _cp_model_constant(strategy.domain_reduction, "domain reduction"),
        )
    return len(strategies)


def _cp_model_constant(name: str, label: str) -> Any:
    text = str(name or "").strip()
    if not text:
        raise ValueError(f"{label} strategy is required")
    if not hasattr(cp_model, text):
        raise ValueError(f"unsupported {label} strategy {text!r}")
    return getattr(cp_model, text)


def _assumption_core_names(
    solver: cp_model.CpSolver,
    assumptions: tuple[BoolLiteral, ...],
    variables: dict[str, Any],
) -> tuple[str, ...]:
    if not assumptions:
        return ()
    core_indices = {int(index) for index in solver.SufficientAssumptionsForInfeasibility()}
    names: list[str] = []
    for literal in assumptions:
        if int(_literal_ref(literal, variables).Index()) in core_indices:
            names.append(_literal_name(literal))
    return tuple(names)


def _best_objective_bound(solver: cp_model.CpSolver, problem: OptimizationProblemSpec) -> float | None:
    if problem.objective is None:
        return None
    try:
        return float(solver.BestObjectiveBound())
    except RuntimeError:
        return None


def _create_variables(model: cp_model.CpModel, problem: OptimizationProblemSpec) -> dict[str, Any]:
    variables: dict[str, Any] = {}
    for spec in problem.variables:
        name = str(spec.name or "").strip()
        if not name:
            raise ValueError("variable name is required")
        if name in variables:
            raise ValueError(f"duplicate variable name {name!r}")
        kind = str(spec.kind or "int").strip().lower()
        if kind == "bool":
            variables[name] = model.NewBoolVar(name)
        elif kind == "int":
            variables[name] = model.NewIntVar(int(spec.lower_bound), int(spec.upper_bound), name)
        else:
            raise ValueError(f"unsupported variable kind {spec.kind!r}")
    return variables


def _create_intervals(
    model: cp_model.CpModel,
    specs: tuple[IntervalSpec, ...],
    variables: dict[str, Any],
) -> dict[str, Any]:
    intervals: dict[str, Any] = {}
    for spec in specs:
        name = str(spec.name or "").strip()
        if not name:
            raise ValueError("interval name is required")
        if name in intervals:
            raise ValueError(f"duplicate interval name {name!r}")
        start = _value_ref(spec.start, variables)
        size = _value_ref(spec.size, variables)
        end = _value_ref(spec.end, variables)
        if spec.presence is None:
            intervals[name] = model.NewIntervalVar(start, size, end, name)
            continue
        presence_name = str(spec.presence or "").strip()
        if presence_name not in variables:
            raise ValueError(f"unknown interval presence variable {presence_name!r}")
        intervals[name] = model.NewOptionalIntervalVar(start, size, end, variables[presence_name], name)
    return intervals


def _add_constraint(
    model: cp_model.CpModel,
    constraint: ConstraintSpec,
    variables: dict[str, Any],
    intervals: dict[str, Any],
) -> None:
    if isinstance(constraint, LinearConstraintSpec):
        expr = _linear_expression(constraint.expression, variables)
        if constraint.sense == "==":
            cp_constraint = model.Add(expr == int(constraint.rhs))
        elif constraint.sense == "<=":
            cp_constraint = model.Add(expr <= int(constraint.rhs))
        elif constraint.sense == ">=":
            cp_constraint = model.Add(expr >= int(constraint.rhs))
        else:
            raise ValueError(f"unsupported constraint sense {constraint.sense!r}")
        _apply_enforcement(cp_constraint, constraint.enforcement_literals, variables)
        return
    if isinstance(constraint, LinearExpressionInDomainConstraintSpec):
        model.AddLinearExpressionInDomain(
            _linear_expression(constraint.expression, variables),
            cp_model.Domain.FromIntervals(
                tuple((int(start), int(end)) for start, end in constraint.intervals)
            ),
        )
        return
    if isinstance(constraint, BoolOrConstraintSpec):
        model.AddBoolOr(tuple(_literal_ref(literal, variables) for literal in constraint.literals))
        return
    if isinstance(constraint, BoolAndConstraintSpec):
        model.AddBoolAnd(tuple(_literal_ref(literal, variables) for literal in constraint.literals))
        return
    if isinstance(constraint, BoolXorConstraintSpec):
        model.AddBoolXOr(tuple(_literal_ref(literal, variables) for literal in constraint.literals))
        return
    if isinstance(constraint, AtLeastOneConstraintSpec):
        model.AddAtLeastOne(tuple(_literal_ref(literal, variables) for literal in constraint.literals))
        return
    if isinstance(constraint, AtMostOneConstraintSpec):
        model.AddAtMostOne(tuple(_literal_ref(literal, variables) for literal in constraint.literals))
        return
    if isinstance(constraint, ExactlyOneConstraintSpec):
        model.AddExactlyOne(tuple(_literal_ref(literal, variables) for literal in constraint.literals))
        return
    if isinstance(constraint, ImplicationConstraintSpec):
        model.AddImplication(
            _literal_ref(constraint.antecedent, variables),
            _literal_ref(constraint.consequent, variables),
        )
        return
    if isinstance(constraint, AllowedAssignmentsConstraintSpec):
        model.AddAllowedAssignments(
            tuple(_variable_ref(name, variables) for name in constraint.variables),
            tuple(tuple(int(value) for value in row) for row in constraint.tuples),
        )
        return
    if isinstance(constraint, ForbiddenAssignmentsConstraintSpec):
        model.AddForbiddenAssignments(
            tuple(_variable_ref(name, variables) for name in constraint.variables),
            tuple(tuple(int(value) for value in row) for row in constraint.tuples),
        )
        return
    if isinstance(constraint, ElementConstraintSpec):
        model.AddElement(
            _value_ref(constraint.index, variables),
            tuple(_value_ref(value, variables) for value in constraint.values),
            _value_ref(constraint.target, variables),
        )
        return
    if isinstance(constraint, AutomatonConstraintSpec):
        model.AddAutomaton(
            tuple(_variable_ref(name, variables) for name in constraint.variables),
            int(constraint.starting_state),
            tuple(int(state) for state in constraint.final_states),
            tuple(tuple(int(value) for value in row) for row in constraint.transitions),
        )
        return
    if isinstance(constraint, InverseConstraintSpec):
        model.AddInverse(
            tuple(_variable_ref(name, variables) for name in constraint.variables),
            tuple(_variable_ref(name, variables) for name in constraint.inverse_variables),
        )
        return
    if isinstance(constraint, AbsEqualityConstraintSpec):
        model.AddAbsEquality(
            _value_ref(constraint.target, variables),
            _value_ref(constraint.expression, variables),
        )
        return
    if isinstance(constraint, MaxEqualityConstraintSpec):
        model.AddMaxEquality(
            _value_ref(constraint.target, variables),
            tuple(_value_ref(expr, variables) for expr in constraint.expressions),
        )
        return
    if isinstance(constraint, MinEqualityConstraintSpec):
        model.AddMinEquality(
            _value_ref(constraint.target, variables),
            tuple(_value_ref(expr, variables) for expr in constraint.expressions),
        )
        return
    if isinstance(constraint, MultiplicationEqualityConstraintSpec):
        model.AddMultiplicationEquality(
            _value_ref(constraint.target, variables),
            tuple(_value_ref(expr, variables) for expr in constraint.expressions),
        )
        return
    if isinstance(constraint, DivisionEqualityConstraintSpec):
        model.AddDivisionEquality(
            _value_ref(constraint.target, variables),
            _value_ref(constraint.numerator, variables),
            _value_ref(constraint.denominator, variables),
        )
        return
    if isinstance(constraint, ModuloEqualityConstraintSpec):
        model.AddModuloEquality(
            _value_ref(constraint.target, variables),
            _value_ref(constraint.expression, variables),
            _value_ref(constraint.modulo, variables),
        )
        return
    if isinstance(constraint, MapDomainConstraintSpec):
        model.AddMapDomain(
            _variable_ref(constraint.variable, variables),
            tuple(_variable_ref(name, variables) for name in constraint.bool_variables),
            int(constraint.offset),
        )
        return
    if isinstance(constraint, AllDifferentConstraintSpec):
        model.AddAllDifferent(tuple(_variable_ref(name, variables) for name in constraint.variables))
        return
    if isinstance(constraint, NoOverlapConstraintSpec):
        model.AddNoOverlap(tuple(_interval_ref(name, intervals) for name in constraint.intervals))
        return
    if isinstance(constraint, CumulativeConstraintSpec):
        if len(constraint.intervals) != len(constraint.demands):
            raise ValueError(f"constraint {constraint.name!r} has mismatched intervals and demands")
        model.AddCumulative(
            tuple(_interval_ref(name, intervals) for name in constraint.intervals),
            tuple(_value_ref(demand, variables) for demand in constraint.demands),
            _value_ref(constraint.capacity, variables),
        )
        return
    if isinstance(constraint, NoOverlap2DConstraintSpec):
        if len(constraint.x_intervals) != len(constraint.y_intervals):
            raise ValueError(f"constraint {constraint.name!r} has mismatched x and y intervals")
        model.AddNoOverlap2D(
            tuple(_interval_ref(name, intervals) for name in constraint.x_intervals),
            tuple(_interval_ref(name, intervals) for name in constraint.y_intervals),
        )
        return
    if isinstance(constraint, CircuitConstraintSpec):
        model.AddCircuit(
            tuple(
                (int(arc.tail), int(arc.head), _literal_ref(arc.literal, variables))
                for arc in constraint.arcs
            )
        )
        return
    if isinstance(constraint, MultipleCircuitConstraintSpec):
        model.AddMultipleCircuit(
            tuple(
                (int(arc.tail), int(arc.head), _literal_ref(arc.literal, variables))
                for arc in constraint.arcs
            )
        )
        return
    if isinstance(constraint, ReservoirConstraintSpec):
        if len(constraint.times) != len(constraint.level_changes):
            raise ValueError(f"constraint {constraint.name!r} has mismatched reservoir times and level changes")
        if constraint.active_literals:
            if len(constraint.active_literals) != len(constraint.times):
                raise ValueError(f"constraint {constraint.name!r} has mismatched reservoir active literals")
            model.AddReservoirConstraintWithActive(
                tuple(_value_ref(time, variables) for time in constraint.times),
                tuple(_value_ref(change, variables) for change in constraint.level_changes),
                tuple(_literal_ref(literal, variables) for literal in constraint.active_literals),
                int(constraint.min_level),
                int(constraint.max_level),
            )
        else:
            model.AddReservoirConstraint(
                tuple(_value_ref(time, variables) for time in constraint.times),
                tuple(_value_ref(change, variables) for change in constraint.level_changes),
                int(constraint.min_level),
                int(constraint.max_level),
            )
        return
    raise TypeError(f"unsupported constraint type {type(constraint).__name__}")


def _apply_enforcement(cp_constraint: Any, literals: tuple[BoolLiteral, ...], variables: dict[str, Any]) -> None:
    if literals:
        cp_constraint.OnlyEnforceIf(tuple(_literal_ref(literal, variables) for literal in literals))


def _linear_expression(expression: LinearExpression, variables: dict[str, Any]) -> Any:
    expr: Any = int(expression.constant)
    for term in expression.terms:
        expr += int(term.coefficient) * _variable_ref(str(term.variable), variables)
    return expr


def _value_ref(value: str | int, variables: dict[str, Any]) -> Any:
    if isinstance(value, str):
        return _variable_ref(value, variables)
    return int(value)


def _literal_ref(literal: BoolLiteral, variables: dict[str, Any]) -> Any:
    if isinstance(literal, BoolLiteralSpec):
        variable = _variable_ref(literal.variable, variables)
        return variable.Not() if literal.negated else variable
    text = str(literal).strip()
    if text.startswith("~"):
        return _variable_ref(text[1:], variables).Not()
    if text.startswith("not:"):
        return _variable_ref(text[4:], variables).Not()
    return _variable_ref(text, variables)


def _literal_name(literal: BoolLiteral) -> str:
    if isinstance(literal, BoolLiteralSpec):
        prefix = "~" if literal.negated else ""
        return f"{prefix}{literal.variable}"
    text = str(literal).strip()
    if text.startswith("not:"):
        return f"~{text[4:]}"
    return text


def _variable_ref(name: str, variables: dict[str, Any]) -> Any:
    variable_name = str(name)
    if variable_name not in variables:
        raise ValueError(f"unknown variable {variable_name!r}")
    return variables[variable_name]


def _interval_ref(name: str, intervals: dict[str, Any]) -> Any:
    interval_name = str(name)
    if interval_name not in intervals:
        raise ValueError(f"unknown interval {interval_name!r}")
    return intervals[interval_name]

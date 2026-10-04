# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class VariableSpec:
    name: str
    lower_bound: int
    upper_bound: int
    kind: str = "int"

    @classmethod
    def bool(cls, name: str) -> "VariableSpec":
        return cls(name=str(name), lower_bound=0, upper_bound=1, kind="bool")


@dataclass(frozen=True)
class LinearTerm:
    variable: str
    coefficient: int


@dataclass(frozen=True)
class LinearExpression:
    terms: tuple[LinearTerm, ...] = ()
    constant: int = 0


@dataclass(frozen=True)
class RuleSpec:
    rule_id: str
    description: str
    enforcement: str = "hard"
    priority: int = 100
    source: str = "human_or_agent"


@dataclass(frozen=True)
class LinearConstraintSpec:
    name: str
    expression: LinearExpression
    sense: str
    rhs: int
    rule_id: str
    enforcement_literals: tuple[BoolLiteral, ...] = ()


@dataclass(frozen=True)
class LinearExpressionInDomainConstraintSpec:
    name: str
    expression: LinearExpression
    intervals: tuple[tuple[int, int], ...]
    rule_id: str


@dataclass(frozen=True)
class BoolLiteralSpec:
    variable: str
    negated: bool = False


BoolLiteral = str | BoolLiteralSpec
ValueRef = str | int
SolverParameterValue = bool | int | float | str


@dataclass(frozen=True)
class BoolOrConstraintSpec:
    name: str
    literals: tuple[BoolLiteral, ...]
    rule_id: str


@dataclass(frozen=True)
class BoolAndConstraintSpec:
    name: str
    literals: tuple[BoolLiteral, ...]
    rule_id: str


@dataclass(frozen=True)
class BoolXorConstraintSpec:
    name: str
    literals: tuple[BoolLiteral, ...]
    rule_id: str


@dataclass(frozen=True)
class AtLeastOneConstraintSpec:
    name: str
    literals: tuple[BoolLiteral, ...]
    rule_id: str


@dataclass(frozen=True)
class AtMostOneConstraintSpec:
    name: str
    literals: tuple[BoolLiteral, ...]
    rule_id: str


@dataclass(frozen=True)
class ExactlyOneConstraintSpec:
    name: str
    literals: tuple[BoolLiteral, ...]
    rule_id: str


@dataclass(frozen=True)
class ImplicationConstraintSpec:
    name: str
    antecedent: BoolLiteral
    consequent: BoolLiteral
    rule_id: str


@dataclass(frozen=True)
class AllowedAssignmentsConstraintSpec:
    name: str
    variables: tuple[str, ...]
    tuples: tuple[tuple[int, ...], ...]
    rule_id: str


@dataclass(frozen=True)
class ForbiddenAssignmentsConstraintSpec:
    name: str
    variables: tuple[str, ...]
    tuples: tuple[tuple[int, ...], ...]
    rule_id: str


@dataclass(frozen=True)
class ElementConstraintSpec:
    name: str
    index: ValueRef
    values: tuple[ValueRef, ...]
    target: ValueRef
    rule_id: str


@dataclass(frozen=True)
class AutomatonConstraintSpec:
    name: str
    variables: tuple[str, ...]
    starting_state: int
    final_states: tuple[int, ...]
    transitions: tuple[tuple[int, int, int], ...]
    rule_id: str


@dataclass(frozen=True)
class InverseConstraintSpec:
    name: str
    variables: tuple[str, ...]
    inverse_variables: tuple[str, ...]
    rule_id: str


@dataclass(frozen=True)
class AbsEqualityConstraintSpec:
    name: str
    target: ValueRef
    expression: ValueRef
    rule_id: str


@dataclass(frozen=True)
class MaxEqualityConstraintSpec:
    name: str
    target: ValueRef
    expressions: tuple[ValueRef, ...]
    rule_id: str


@dataclass(frozen=True)
class MinEqualityConstraintSpec:
    name: str
    target: ValueRef
    expressions: tuple[ValueRef, ...]
    rule_id: str


@dataclass(frozen=True)
class MultiplicationEqualityConstraintSpec:
    name: str
    target: ValueRef
    expressions: tuple[ValueRef, ...]
    rule_id: str


@dataclass(frozen=True)
class DivisionEqualityConstraintSpec:
    name: str
    target: ValueRef
    numerator: ValueRef
    denominator: ValueRef
    rule_id: str


@dataclass(frozen=True)
class ModuloEqualityConstraintSpec:
    name: str
    target: ValueRef
    expression: ValueRef
    modulo: ValueRef
    rule_id: str


@dataclass(frozen=True)
class MapDomainConstraintSpec:
    name: str
    variable: str
    bool_variables: tuple[str, ...]
    offset: int
    rule_id: str


@dataclass(frozen=True)
class AllDifferentConstraintSpec:
    name: str
    variables: tuple[str, ...]
    rule_id: str


@dataclass(frozen=True)
class IntervalSpec:
    name: str
    start: str | int
    size: str | int
    end: str | int
    presence: str | None = None


@dataclass(frozen=True)
class NoOverlapConstraintSpec:
    name: str
    intervals: tuple[str, ...]
    rule_id: str


@dataclass(frozen=True)
class CumulativeConstraintSpec:
    name: str
    intervals: tuple[str, ...]
    demands: tuple[ValueRef, ...]
    capacity: ValueRef
    rule_id: str


@dataclass(frozen=True)
class NoOverlap2DConstraintSpec:
    name: str
    x_intervals: tuple[str, ...]
    y_intervals: tuple[str, ...]
    rule_id: str


@dataclass(frozen=True)
class CircuitArcSpec:
    tail: int
    head: int
    literal: BoolLiteral


@dataclass(frozen=True)
class CircuitConstraintSpec:
    name: str
    arcs: tuple[CircuitArcSpec, ...]
    rule_id: str


@dataclass(frozen=True)
class MultipleCircuitConstraintSpec:
    name: str
    arcs: tuple[CircuitArcSpec, ...]
    rule_id: str


@dataclass(frozen=True)
class ReservoirConstraintSpec:
    name: str
    times: tuple[ValueRef, ...]
    level_changes: tuple[ValueRef, ...]
    min_level: int
    max_level: int
    rule_id: str
    active_literals: tuple[BoolLiteral, ...] = ()


@dataclass(frozen=True)
class SolverParameterSpec:
    name: str
    value: SolverParameterValue


@dataclass(frozen=True)
class SolutionHintSpec:
    variable: str
    value: int


@dataclass(frozen=True)
class DecisionStrategySpec:
    variables: tuple[str, ...]
    variable_selection: str
    domain_reduction: str
    rule_id: str | None = None


@dataclass(frozen=True)
class CpSatSolveConfig:
    parameters: tuple[SolverParameterSpec, ...] = ()
    hints: tuple[SolutionHintSpec, ...] = ()
    assumptions: tuple[BoolLiteral, ...] = ()
    decision_strategies: tuple[DecisionStrategySpec, ...] = ()


@dataclass(frozen=True)
class ObjectiveSpec:
    rule_id: str
    sense: str
    expression: LinearExpression


ConstraintSpec = (
    LinearConstraintSpec
    | LinearExpressionInDomainConstraintSpec
    | BoolOrConstraintSpec
    | BoolAndConstraintSpec
    | BoolXorConstraintSpec
    | AtLeastOneConstraintSpec
    | AtMostOneConstraintSpec
    | ExactlyOneConstraintSpec
    | ImplicationConstraintSpec
    | AllowedAssignmentsConstraintSpec
    | ForbiddenAssignmentsConstraintSpec
    | ElementConstraintSpec
    | AutomatonConstraintSpec
    | InverseConstraintSpec
    | AbsEqualityConstraintSpec
    | MaxEqualityConstraintSpec
    | MinEqualityConstraintSpec
    | MultiplicationEqualityConstraintSpec
    | DivisionEqualityConstraintSpec
    | ModuloEqualityConstraintSpec
    | MapDomainConstraintSpec
    | AllDifferentConstraintSpec
    | NoOverlapConstraintSpec
    | CumulativeConstraintSpec
    | NoOverlap2DConstraintSpec
    | CircuitConstraintSpec
    | MultipleCircuitConstraintSpec
    | ReservoirConstraintSpec
)


@dataclass(frozen=True)
class OptimizationProblemSpec:
    problem_id: str
    variables: tuple[VariableSpec, ...]
    rules: tuple[RuleSpec, ...]
    constraints: tuple[ConstraintSpec, ...]
    objective: ObjectiveSpec | None = None
    intervals: tuple[IntervalSpec, ...] = ()
    solve_config: CpSatSolveConfig = field(default_factory=CpSatSolveConfig)

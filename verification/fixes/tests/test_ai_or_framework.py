from __future__ import annotations

from ortools.sat.python import cp_model

from ai_orchestrated_optimization import (
    AllDifferentConstraintSpec,
    AllowedAssignmentsConstraintSpec,
    AutomatonConstraintSpec,
    BoolLiteralSpec,
    CircuitArcSpec,
    CircuitConstraintSpec,
    CpSatSolveConfig,
    DecisionStrategySpec,
    CumulativeConstraintSpec,
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
    LinearTerm,
    MapDomainConstraintSpec,
    MaxEqualityConstraintSpec,
    MinEqualityConstraintSpec,
    ModuloEqualityConstraintSpec,
    MultipleCircuitConstraintSpec,
    MultiplicationEqualityConstraintSpec,
    NoOverlapConstraintSpec,
    NoOverlap2DConstraintSpec,
    ObjectiveSpec,
    ReservoirConstraintSpec,
    AbsEqualityConstraintSpec,
    OptimizationProblemSpec,
    RuleSpec,
    SolutionHintSpec,
    SolverParameterSpec,
    VariableSpec,
    ai_or_model_rule_context,
    build_default_agent_architecture,
    build_rule_first_plan,
    create_existing_cp_model,
    get_existing_cp_model_operation_trace,
    build_legacy_rule_migration_backlog,
    build_agent_migration_task_plan,
    solve_existing_cp_model,
    solve_cp_sat_problem,
    summarize_existing_cp_model_operations_by_rule,
)


def test_default_agent_architecture_matches_required_ai_or_flow() -> None:
    architecture = build_default_agent_architecture()

    assert [agent.role_id for agent in architecture.agents] == [
        "business_expert",
        "chief_architect",
        "mathematical_modeler",
        "dimension_reduction_optimizer",
        "code_execution",
        "debug_diagnostics",
    ]
    assert ("business_expert", "chief_architect", "business_pain_description") in architecture.handoffs
    assert ("chief_architect", "mathematical_modeler", "task_decomposition") in architecture.handoffs
    assert ("chief_architect", "dimension_reduction_optimizer", "solution_space_analysis") in architecture.handoffs
    assert ("mathematical_modeler", "code_execution", "model_artifacts") in architecture.handoffs
    assert ("dimension_reduction_optimizer", "code_execution", "optimization_artifacts") in architecture.handoffs
    assert ("code_execution", "debug_diagnostics", "ortools_run_logs") in architecture.handoffs


def test_rule_first_plan_orders_constraints_before_objective_by_rule_priority() -> None:
    rules = (
        RuleSpec(rule_id="capacity", description="capacity is a hard business rule", enforcement="hard", priority=20),
        RuleSpec(rule_id="coverage", description="coverage is the first hard rule", enforcement="hard", priority=10),
        RuleSpec(rule_id="cost", description="cost is optimized only after hard rules", enforcement="soft", priority=30),
    )
    constraints = (
        LinearConstraintSpec("capacity_worker_a", LinearExpression((LinearTerm("a_t1", 1), LinearTerm("a_t2", 1))), "<=", 1, "capacity"),
        LinearConstraintSpec("cover_task_1", LinearExpression((LinearTerm("a_t1", 1), LinearTerm("b_t1", 1))), "==", 1, "coverage"),
    )

    plan = build_rule_first_plan(rules=rules, constraints=constraints, objective_rule_id="cost")

    assert [item.rule_id for item in plan.rule_order] == ["coverage", "capacity", "cost"]
    assert [item.constraint.name for item in plan.constraint_order] == ["cover_task_1", "capacity_worker_a"]
    assert plan.objective_rule_id == "cost"


def test_generic_cp_sat_solver_solves_assignment_problem_without_scheduler_domain() -> None:
    variables = (
        VariableSpec.bool("a_t1"),
        VariableSpec.bool("a_t2"),
        VariableSpec.bool("b_t1"),
        VariableSpec.bool("b_t2"),
    )
    rules = (
        RuleSpec(rule_id="coverage", description="each task is assigned once", enforcement="hard", priority=10),
        RuleSpec(rule_id="worker_capacity", description="each worker handles at most one task", enforcement="hard", priority=20),
        RuleSpec(rule_id="assignment_cost", description="minimize assignment cost", enforcement="soft", priority=100),
    )
    constraints = (
        LinearConstraintSpec("cover_t1", LinearExpression((LinearTerm("a_t1", 1), LinearTerm("b_t1", 1))), "==", 1, "coverage"),
        LinearConstraintSpec("cover_t2", LinearExpression((LinearTerm("a_t2", 1), LinearTerm("b_t2", 1))), "==", 1, "coverage"),
        LinearConstraintSpec("cap_a", LinearExpression((LinearTerm("a_t1", 1), LinearTerm("a_t2", 1))), "<=", 1, "worker_capacity"),
        LinearConstraintSpec("cap_b", LinearExpression((LinearTerm("b_t1", 1), LinearTerm("b_t2", 1))), "<=", 1, "worker_capacity"),
    )
    objective = ObjectiveSpec(
        rule_id="assignment_cost",
        sense="minimize",
        expression=LinearExpression(
            (
                LinearTerm("a_t1", 3),
                LinearTerm("a_t2", 1),
                LinearTerm("b_t1", 1),
                LinearTerm("b_t2", 3),
            )
        ),
    )
    problem = OptimizationProblemSpec(
        problem_id="generic_assignment",
        variables=variables,
        rules=rules,
        constraints=constraints,
        objective=objective,
    )

    solution = solve_cp_sat_problem(problem, time_limit_seconds=5)

    assert solution.status_name in {"OPTIMAL", "FEASIBLE"}
    assert solution.objective_value == 2
    assert solution.values == {"a_t1": 0, "a_t2": 1, "b_t1": 1, "b_t2": 0}
    assert solution.applied_constraints == ("cover_t1", "cover_t2", "cap_a", "cap_b")


def test_generic_cp_sat_solver_supports_all_different_without_scheduler_domain() -> None:
    variables = (
        VariableSpec("item_a_slot", 1, 3),
        VariableSpec("item_b_slot", 1, 3),
        VariableSpec("item_c_slot", 1, 3),
    )
    rules = (
        RuleSpec(rule_id="unique_slots", description="each item must occupy a different slot", enforcement="hard", priority=10),
        RuleSpec(rule_id="anchor", description="business expert fixed item A to the first slot", enforcement="hard", priority=20),
    )
    constraints = (
        AllDifferentConstraintSpec("unique_item_slots", ("item_a_slot", "item_b_slot", "item_c_slot"), "unique_slots"),
        LinearConstraintSpec("fix_item_a", LinearExpression((LinearTerm("item_a_slot", 1),)), "==", 1, "anchor"),
    )
    problem = OptimizationProblemSpec(
        problem_id="generic_all_different",
        variables=variables,
        rules=rules,
        constraints=constraints,
    )

    solution = solve_cp_sat_problem(problem, time_limit_seconds=5)

    assert solution.status_name in {"OPTIMAL", "FEASIBLE"}
    assert solution.values["item_a_slot"] == 1
    assert sorted(solution.values.values()) == [1, 2, 3]
    assert solution.applied_constraints == ("unique_item_slots", "fix_item_a")


def test_generic_cp_sat_solver_supports_interval_resource_constraints_without_scheduler_domain() -> None:
    variables = (
        VariableSpec("start_a", 0, 5),
        VariableSpec("end_a", 0, 5),
        VariableSpec("start_b", 0, 5),
        VariableSpec("end_b", 0, 5),
    )
    intervals = (
        IntervalSpec("task_a", start="start_a", size=2, end="end_a"),
        IntervalSpec("task_b", start="start_b", size=3, end="end_b"),
    )
    rules = (
        RuleSpec(rule_id="resource_capacity", description="one worker can run only one task at a time", enforcement="hard", priority=10),
        RuleSpec(rule_id="finish_b_early", description="prefer finishing task B early", enforcement="soft", priority=50),
    )
    constraints = (
        NoOverlapConstraintSpec("single_machine_no_overlap", ("task_a", "task_b"), "resource_capacity"),
        CumulativeConstraintSpec("single_worker_capacity", ("task_a", "task_b"), (1, 1), 1, "resource_capacity"),
    )
    objective = ObjectiveSpec(
        rule_id="finish_b_early",
        sense="minimize",
        expression=LinearExpression((LinearTerm("end_b", 1),)),
    )
    problem = OptimizationProblemSpec(
        problem_id="generic_interval_resource",
        variables=variables,
        intervals=intervals,
        rules=rules,
        constraints=constraints,
        objective=objective,
    )

    solution = solve_cp_sat_problem(problem, time_limit_seconds=5)

    assert solution.status_name in {"OPTIMAL", "FEASIBLE"}
    assert solution.values["start_b"] == 0
    assert solution.values["end_b"] == 3
    assert solution.values["start_a"] >= solution.values["end_b"]
    assert solution.applied_constraints == ("single_machine_no_overlap", "single_worker_capacity")


def test_generic_cp_sat_solver_supports_boolean_table_and_element_primitives() -> None:
    variables = (
        VariableSpec.bool("choose_a"),
        VariableSpec.bool("choose_b"),
        VariableSpec.bool("choose_c"),
        VariableSpec("item", 0, 1),
        VariableSpec("machine", 0, 1),
        VariableSpec("lookup_cost", 0, 10),
    )
    rules = (
        RuleSpec("pick_one", "choose exactly one candidate", "hard", 10),
        RuleSpec("logic_guard", "candidate A excludes candidate B", "hard", 20),
        RuleSpec("allowed_pairing", "only approved item-machine pairs are legal", "hard", 30),
        RuleSpec("blocked_pairing", "agent rejected a dominated pairing", "hard", 40),
        RuleSpec("lookup_cost", "cost is read from an indexed vector", "hard", 50),
        RuleSpec("minimize_cost", "prefer the cheapest generic choice", "soft", 100),
    )
    constraints = (
        ExactlyOneConstraintSpec("exactly_one_candidate", ("choose_a", "choose_b", "choose_c"), "pick_one"),
        ImplicationConstraintSpec(
            "if_a_then_not_b",
            BoolLiteralSpec("choose_a"),
            BoolLiteralSpec("choose_b", negated=True),
            "logic_guard",
        ),
        AllowedAssignmentsConstraintSpec("allowed_item_machine_pairs", ("item", "machine"), ((0, 1), (1, 0)), "allowed_pairing"),
        ForbiddenAssignmentsConstraintSpec("forbid_expensive_pair", ("item", "machine"), ((0, 0),), "blocked_pairing"),
        ElementConstraintSpec("item_cost_lookup", "item", (5, 2), "lookup_cost", "lookup_cost"),
    )
    objective = ObjectiveSpec(
        "minimize_cost",
        "minimize",
        LinearExpression(
            (
                LinearTerm("lookup_cost", 1),
                LinearTerm("choose_a", 5),
                LinearTerm("choose_b", 1),
            )
        ),
    )
    problem = OptimizationProblemSpec(
        "generic_boolean_table_element",
        variables=variables,
        rules=rules,
        constraints=constraints,
        objective=objective,
    )

    solution = solve_cp_sat_problem(problem, time_limit_seconds=5)

    assert solution.status_name in {"OPTIMAL", "FEASIBLE"}
    assert solution.values["item"] == 1
    assert solution.values["machine"] == 0
    assert solution.values["lookup_cost"] == 2
    assert solution.values["choose_c"] == 1
    assert solution.applied_constraints == (
        "exactly_one_candidate",
        "if_a_then_not_b",
        "allowed_item_machine_pairs",
        "forbid_expensive_pair",
        "item_cost_lookup",
    )


def test_generic_cp_sat_solver_supports_automaton_and_inverse_primitives() -> None:
    variables = (
        VariableSpec("bit_0", 0, 1),
        VariableSpec("bit_1", 0, 1),
        VariableSpec("bit_2", 0, 1),
        VariableSpec("perm_0", 0, 1),
        VariableSpec("perm_1", 0, 1),
        VariableSpec("inv_0", 0, 1),
        VariableSpec("inv_1", 0, 1),
    )
    rules = (
        RuleSpec("state_machine", "binary sequence cannot contain adjacent active periods", "hard", 10),
        RuleSpec("permutation", "inverse variables must describe the same assignment", "hard", 20),
        RuleSpec("anchor", "business expert pins one permutation entry", "hard", 30),
        RuleSpec("maximize_activity", "keep as many active periods as possible", "soft", 100),
    )
    constraints = (
        AutomatonConstraintSpec(
            "no_adjacent_ones",
            ("bit_0", "bit_1", "bit_2"),
            0,
            (0, 1),
            (
                (0, 0, 0),
                (0, 1, 1),
                (1, 0, 0),
            ),
            "state_machine",
        ),
        InverseConstraintSpec("permutation_inverse", ("perm_0", "perm_1"), ("inv_0", "inv_1"), "permutation"),
        LinearConstraintSpec("fix_perm_0_to_1", LinearExpression((LinearTerm("perm_0", 1),)), "==", 1, "anchor"),
    )
    objective = ObjectiveSpec(
        "maximize_activity",
        "maximize",
        LinearExpression((LinearTerm("bit_0", 1), LinearTerm("bit_1", 1), LinearTerm("bit_2", 1))),
    )
    problem = OptimizationProblemSpec(
        "generic_automaton_inverse",
        variables=variables,
        rules=rules,
        constraints=constraints,
        objective=objective,
    )

    solution = solve_cp_sat_problem(problem, time_limit_seconds=5)

    assert solution.status_name in {"OPTIMAL", "FEASIBLE"}
    assert [solution.values["bit_0"], solution.values["bit_1"], solution.values["bit_2"]] == [1, 0, 1]
    assert solution.values["perm_0"] == 1
    assert solution.values["perm_1"] == 0
    assert solution.values["inv_0"] == 1
    assert solution.values["inv_1"] == 0


def test_generic_cp_sat_solver_supports_circuit_and_no_overlap_2d_primitives() -> None:
    variables = (
        VariableSpec.bool("arc_0_1"),
        VariableSpec.bool("arc_1_2"),
        VariableSpec.bool("arc_2_0"),
        VariableSpec("a_x_start", 0, 4),
        VariableSpec("a_x_end", 0, 6),
        VariableSpec("b_x_start", 0, 4),
        VariableSpec("b_x_end", 0, 6),
    )
    intervals = (
        IntervalSpec("rect_a_x", "a_x_start", 2, "a_x_end"),
        IntervalSpec("rect_a_y", 0, 2, 2),
        IntervalSpec("rect_b_x", "b_x_start", 2, "b_x_end"),
        IntervalSpec("rect_b_y", 0, 2, 2),
    )
    rules = (
        RuleSpec("route_cycle", "selected arcs must form one route cycle", "hard", 10),
        RuleSpec("packing", "rectangles sharing the same lane cannot overlap", "hard", 20),
        RuleSpec("finish_early", "prefer the second rectangle early", "soft", 100),
    )
    constraints = (
        CircuitConstraintSpec(
            "three_node_cycle",
            (
                CircuitArcSpec(0, 1, "arc_0_1"),
                CircuitArcSpec(1, 2, "arc_1_2"),
                CircuitArcSpec(2, 0, "arc_2_0"),
            ),
            "route_cycle",
        ),
        NoOverlap2DConstraintSpec("pack_rectangles", ("rect_a_x", "rect_b_x"), ("rect_a_y", "rect_b_y"), "packing"),
    )
    objective = ObjectiveSpec("finish_early", "minimize", LinearExpression((LinearTerm("b_x_end", 1),)))
    problem = OptimizationProblemSpec(
        "generic_circuit_no_overlap_2d",
        variables=variables,
        intervals=intervals,
        rules=rules,
        constraints=constraints,
        objective=objective,
    )

    solution = solve_cp_sat_problem(problem, time_limit_seconds=5)

    assert solution.status_name in {"OPTIMAL", "FEASIBLE"}
    assert solution.values["arc_0_1"] == 1
    assert solution.values["arc_1_2"] == 1
    assert solution.values["arc_2_0"] == 1
    assert (
        solution.values["a_x_end"] <= solution.values["b_x_start"]
        or solution.values["b_x_end"] <= solution.values["a_x_start"]
    )


def test_generic_cp_sat_solver_supports_arithmetic_domain_and_reservoir_primitives() -> None:
    variables = (
        VariableSpec("x", -5, 5),
        VariableSpec("abs_x", 0, 5),
        VariableSpec("y", 3, 3),
        VariableSpec("product", 0, 30),
        VariableSpec("quotient", 0, 10),
        VariableSpec("remainder", 0, 2),
        VariableSpec("max_value", 0, 10),
        VariableSpec("min_value", 0, 10),
    )
    rules = (
        RuleSpec("domain", "x must come from a business-approved disjoint domain", "hard", 10),
        RuleSpec("arithmetic", "derive helper variables for nonlinear CP-SAT expressions", "hard", 20),
        RuleSpec("inventory", "reservoir level must stay inside operating bounds", "hard", 30),
        RuleSpec("prefer_negative", "prefer the lower domain member", "soft", 100),
    )
    constraints = (
        LinearExpressionInDomainConstraintSpec(
            "x_in_two_point_domain",
            LinearExpression((LinearTerm("x", 1),)),
            ((-2, -2), (2, 2)),
            "domain",
        ),
        AbsEqualityConstraintSpec("absolute_value", "abs_x", "x", "arithmetic"),
        MultiplicationEqualityConstraintSpec("product_value", "product", ("abs_x", "y"), "arithmetic"),
        DivisionEqualityConstraintSpec("quotient_value", "quotient", "product", "y", "arithmetic"),
        ModuloEqualityConstraintSpec("remainder_value", "remainder", "product", 3, "arithmetic"),
        MaxEqualityConstraintSpec("max_helper", "max_value", ("abs_x", "y"), "arithmetic"),
        MinEqualityConstraintSpec("min_helper", "min_value", ("abs_x", "y"), "arithmetic"),
        ReservoirConstraintSpec("bounded_inventory", (0, 1, 2), (3, -2, -1), 0, 3, "inventory"),
    )
    objective = ObjectiveSpec("prefer_negative", "minimize", LinearExpression((LinearTerm("x", 1),)))
    problem = OptimizationProblemSpec(
        "generic_arithmetic_domain_reservoir",
        variables=variables,
        rules=rules,
        constraints=constraints,
        objective=objective,
    )

    solution = solve_cp_sat_problem(problem, time_limit_seconds=5)

    assert solution.status_name in {"OPTIMAL", "FEASIBLE"}
    assert solution.values["x"] == -2
    assert solution.values["abs_x"] == 2
    assert solution.values["product"] == 6
    assert solution.values["quotient"] == 2
    assert solution.values["remainder"] == 0
    assert solution.values["max_value"] == 3
    assert solution.values["min_value"] == 2


def test_generic_cp_sat_solver_supports_map_domain_and_multiple_circuit_primitives() -> None:
    variables = (
        VariableSpec("route_choice", 0, 1),
        VariableSpec.bool("route_zero"),
        VariableSpec.bool("route_one"),
        VariableSpec.bool("arc_0_1"),
        VariableSpec.bool("arc_1_0"),
    )
    rules = (
        RuleSpec("map_domain", "choice integer must map to indicator literals", "hard", 10),
        RuleSpec("routing", "selected arcs form a valid multi-route circuit", "hard", 20),
        RuleSpec("prefer_route_one", "prefer route one when otherwise equivalent", "soft", 100),
    )
    constraints = (
        MapDomainConstraintSpec("choice_to_literals", "route_choice", ("route_zero", "route_one"), 0, "map_domain"),
        MultipleCircuitConstraintSpec(
            "two_node_multi_circuit",
            (CircuitArcSpec(0, 1, "arc_0_1"), CircuitArcSpec(1, 0, "arc_1_0")),
            "routing",
        ),
    )
    objective = ObjectiveSpec("prefer_route_one", "maximize", LinearExpression((LinearTerm("route_choice", 1),)))
    problem = OptimizationProblemSpec(
        "generic_map_domain_multiple_circuit",
        variables=variables,
        rules=rules,
        constraints=constraints,
        objective=objective,
    )

    solution = solve_cp_sat_problem(problem, time_limit_seconds=5)

    assert solution.status_name in {"OPTIMAL", "FEASIBLE"}
    assert solution.values["route_choice"] == 1
    assert solution.values["route_zero"] == 0
    assert solution.values["route_one"] == 1
    assert solution.values["arc_0_1"] == 1
    assert solution.values["arc_1_0"] == 1


def test_generic_cp_sat_solver_applies_ai_solver_controls_for_hint_strategy_and_params() -> None:
    variables = (
        VariableSpec.bool("use_fast_lane"),
        VariableSpec.bool("use_low_cost_lane"),
    )
    rules = (
        RuleSpec("choose_lane", "business expert requires one lane choice", "hard", 10),
        RuleSpec("prefer_low_cost", "agent prefers the low cost lane", "soft", 100),
    )
    problem = OptimizationProblemSpec(
        problem_id="generic_ai_solver_controls",
        variables=variables,
        rules=rules,
        constraints=(
            ExactlyOneConstraintSpec(
                "choose_exactly_one_lane",
                ("use_fast_lane", "use_low_cost_lane"),
                "choose_lane",
            ),
        ),
        objective=ObjectiveSpec(
            "prefer_low_cost",
            "minimize",
            LinearExpression((LinearTerm("use_fast_lane", 3), LinearTerm("use_low_cost_lane", 1))),
        ),
        solve_config=CpSatSolveConfig(
            parameters=(
                SolverParameterSpec("search_branching", "FIXED_SEARCH"),
                SolverParameterSpec("num_search_workers", 1),
            ),
            hints=(SolutionHintSpec("use_fast_lane", 1),),
            decision_strategies=(
                DecisionStrategySpec(
                    variables=("use_fast_lane", "use_low_cost_lane"),
                    variable_selection="CHOOSE_FIRST",
                    domain_reduction="SELECT_MAX_VALUE",
                    rule_id="choose_lane",
                ),
            ),
        ),
    )

    solution = solve_cp_sat_problem(problem, time_limit_seconds=5)

    assert solution.status_name == "OPTIMAL"
    assert solution.values["use_low_cost_lane"] == 1
    assert solution.solver_parameters["search_branching"] == "FIXED_SEARCH"
    assert solution.solver_parameters["num_search_workers"] == 1
    assert solution.solution_hints == {"use_fast_lane": 1}
    assert solution.decision_strategy_count == 1
    assert "CpSolverResponse" in solution.response_stats


def test_generic_cp_sat_solver_reports_assumption_core_for_agent_debugging() -> None:
    problem = OptimizationProblemSpec(
        problem_id="generic_assumption_core_debug",
        variables=(VariableSpec.bool("force_option_a"),),
        rules=(
            RuleSpec("hard_exclusion", "business rule excludes option A", "hard", 10),
            RuleSpec("debug_assumption", "debug agent temporarily assumes option A", "hard", 20),
        ),
        constraints=(
            LinearConstraintSpec(
                "exclude_option_a",
                LinearExpression((LinearTerm("force_option_a", 1),)),
                "==",
                0,
                "hard_exclusion",
            ),
        ),
        solve_config=CpSatSolveConfig(assumptions=("force_option_a",)),
    )

    solution = solve_cp_sat_problem(problem, time_limit_seconds=5)

    assert solution.status_name == "INFEASIBLE"
    assert solution.values == {}
    assert solution.assumption_core == ("force_option_a",)
    assert solution.assumptions == ("force_option_a",)
    assert "CpSolverResponse" in solution.response_stats


def test_generic_cp_sat_solver_supports_enforced_linear_constraints_for_assumption_debugging() -> None:
    problem = OptimizationProblemSpec(
        problem_id="generic_enforced_linear_assumption_debug",
        variables=(
            VariableSpec.bool("place_item"),
            VariableSpec.bool("assume_block_item"),
        ),
        rules=(
            RuleSpec("require_item", "business rule requires placing the item", "hard", 10),
            RuleSpec("block_item", "debug assumption blocks the item", "hard", 20),
        ),
        constraints=(
            LinearConstraintSpec(
                "require_item_to_be_placed",
                LinearExpression((LinearTerm("place_item", 1),)),
                "==",
                1,
                "require_item",
            ),
            LinearConstraintSpec(
                "block_item_if_assumed",
                LinearExpression((LinearTerm("place_item", 1),)),
                "==",
                0,
                "block_item",
                enforcement_literals=("assume_block_item",),
            ),
        ),
        solve_config=CpSatSolveConfig(assumptions=("assume_block_item",)),
    )

    solution = solve_cp_sat_problem(problem, time_limit_seconds=5)

    assert solution.status_name == "INFEASIBLE"
    assert solution.assumption_core == ("assume_block_item",)


def test_existing_cp_model_factory_records_rule_scoped_legacy_operations_and_still_solves() -> None:
    model = create_existing_cp_model("legacy_rule_trace")

    with ai_or_model_rule_context("coverage"):
        x = model.NewBoolVar("x")
        model.Add(x == 1)
    with ai_or_model_rule_context("objective"):
        model.Maximize(x)

    result = solve_existing_cp_model(model, time_limit_seconds=5)
    trace = get_existing_cp_model_operation_trace(model)

    assert result.status_name == "OPTIMAL"
    assert result.solver.Value(x) == 1
    assert [(item.operation, item.rule_id) for item in trace] == [
        ("NewBoolVar", "coverage"),
        ("Add", "coverage"),
        ("Maximize", "objective"),
    ]
    assert summarize_existing_cp_model_operations_by_rule(model) == {
        "coverage": {"operation_count": 2, "operations": {"Add": 1, "NewBoolVar": 1}},
        "objective": {"operation_count": 1, "operations": {"Maximize": 1}},
    }
    assert result.operation_trace == trace
    assert result.operation_summary_by_rule["coverage"]["operation_count"] == 2


def test_existing_cp_model_solver_supports_solution_callback_on_current_ortools() -> None:
    class CountingCallback(cp_model.CpSolverSolutionCallback):
        def __init__(self) -> None:
            super().__init__()
            self.solution_count = 0

        def on_solution_callback(self) -> None:
            self.solution_count += 1

    model = create_existing_cp_model("callback_compatibility")
    x = model.NewBoolVar("x")
    model.Maximize(x)
    callback = CountingCallback()

    result = solve_existing_cp_model(model, time_limit_seconds=5, solution_callback=callback)

    assert result.status_name == "OPTIMAL"
    assert result.solver.StatusName(result.status) == "OPTIMAL"
    assert result.solver.Value(x) == 1
    assert callback.solution_count >= 1


def test_legacy_rule_migration_backlog_prioritizes_unconverted_heavy_rules() -> None:
    backlog = build_legacy_rule_migration_backlog(
        {
            "legacy.capacity": {"operation_count": 9, "operations": {"Add": 7, "NewBoolVar": 2}},
            "legacy.cost": {"operation_count": 3, "operations": {"Minimize": 1, "Add": 2}},
            "__unscoped__": {"operation_count": 2, "operations": {"Add": 2}},
        },
        generic_rule_ids=("legacy.cost",),
    )

    assert [item.rule_id for item in backlog] == ["legacy.capacity", "__unscoped__", "legacy.cost"]
    assert backlog[0].generic_contract_status == "missing_generic_contract"
    assert (
        backlog[0].recommended_next_step
        == "convert this legacy rule into OptimizationProblemSpec constraints using LinearConstraintSpec, VariableSpec.bool"
    )
    assert backlog[1].generic_contract_status == "missing_rule_context"
    assert backlog[2].generic_contract_status == "covered_by_generic_contract"
    assert backlog[2].recommended_next_step == "keep parity tests and retire the legacy operation path when equivalent"


def test_legacy_rule_migration_backlog_recommends_generic_specs_from_cp_sat_operations() -> None:
    backlog = build_legacy_rule_migration_backlog(
        {
            "legacy.resource": {
                "operation_count": 6,
                "operations": {
                    "NewBoolVar": 2,
                    "NewIntervalVar": 2,
                    "AddNoOverlap": 1,
                    "AddCumulative": 1,
                },
            },
            "legacy.routing": {
                "operation_count": 3,
                "operations": {
                    "AddAllowedAssignments": 1,
                    "AddCircuit": 1,
                    "AddElement": 1,
                },
            },
            "legacy.arithmetic": {
                "operation_count": 4,
                "operations": {
                    "AddAbsEquality": 1,
                    "AddMaxEquality": 1,
                    "AddModuloEquality": 1,
                    "Minimize": 1,
                },
            },
        }
    )
    by_rule = {item.rule_id: item for item in backlog}

    assert by_rule["legacy.resource"].candidate_generic_specs == (
        "CumulativeConstraintSpec",
        "IntervalSpec",
        "NoOverlapConstraintSpec",
        "VariableSpec.bool",
    )
    assert by_rule["legacy.routing"].candidate_generic_specs == (
        "AllowedAssignmentsConstraintSpec",
        "CircuitConstraintSpec",
        "ElementConstraintSpec",
    )
    assert by_rule["legacy.arithmetic"].candidate_generic_specs == (
        "AbsEqualityConstraintSpec",
        "MaxEqualityConstraintSpec",
        "ModuloEqualityConstraintSpec",
        "ObjectiveSpec",
    )


def test_agent_migration_task_plan_assigns_backlog_items_to_required_agent_roles() -> None:
    backlog = build_legacy_rule_migration_backlog(
        {
            "legacy.capacity": {
                "operation_count": 6,
                "operations": {"AddNoOverlap": 1, "AddCumulative": 1, "NewIntervalVar": 2, "NewBoolVar": 2},
            },
            "legacy.linear": {"operation_count": 4, "operations": {"Add": 2, "NewBoolVar": 2}},
            "__unscoped__": {"operation_count": 1, "operations": {"Add": 1}},
            "legacy.ready": {"operation_count": 2, "operations": {"Add": 1, "NewBoolVar": 1}},
        },
        generic_rule_ids=("legacy.ready",),
    )

    plan = build_agent_migration_task_plan(backlog)
    by_rule = {item.rule_id: item for item in plan}

    assert [item.rule_id for item in plan] == ["legacy.capacity", "legacy.linear", "__unscoped__", "legacy.ready"]
    assert by_rule["legacy.capacity"].owner_agent_role == "dimension_reduction_optimizer"
    assert by_rule["legacy.capacity"].handoff_from == "chief_architect"
    assert by_rule["legacy.capacity"].target_generic_specs == (
        "CumulativeConstraintSpec",
        "IntervalSpec",
        "NoOverlapConstraintSpec",
        "VariableSpec.bool",
    )
    assert by_rule["legacy.linear"].owner_agent_role == "mathematical_modeler"
    assert by_rule["__unscoped__"].owner_agent_role == "debug_diagnostics"
    assert by_rule["legacy.ready"].owner_agent_role == "code_execution"
    assert by_rule["legacy.linear"].acceptance_checks == (
        "convert rule to OptimizationProblemSpec using candidate generic specs",
        "add parity test against legacy rule behavior",
        "run focused tests plus AI OR acceptance audit",
    )

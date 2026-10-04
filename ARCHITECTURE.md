# 架构说明：AI-Orchestrated Optimization

## 1. 总体定位

本项目是给 AI 使用的运筹优化框架，而不是单一排课脚本。目标流程是：

`自然语言业务痛点 -> Agent 分解 -> 规则优先计划 -> CP-SAT 建模 -> OR-Tools 求解 -> 日志诊断`

当前仓库保留两层：

- 通用层：`ai_orchestrated_optimization/`，提供 Agent 拓扑、规则合同、变量/约束/目标合同、规则优先计划器和 CP-SAT 后端。
- 示例层：`scheduler/`、`profiles/`、`edu-ops-scheduler-console/`，保留匿名 K12 排课场景作为复杂业务示例和兼容应用。

## 2. 规则优先

规则不是展示层元数据，而是求解前的第一顺位输入。通用层的核心合同如下：

- `RuleSpec`：业务规则、硬/软属性、优先级和来源。
- `VariableSpec`：CP-SAT 变量定义，覆盖 bool/int。
- `LinearConstraintSpec`、`LinearExpressionInDomainConstraintSpec`、布尔逻辑约束、Allowed/Forbidden Assignments、`ElementConstraintSpec`、`AutomatonConstraintSpec`、`InverseConstraintSpec`、`CircuitConstraintSpec`、`MultipleCircuitConstraintSpec`、`AllDifferentConstraintSpec`、`IntervalSpec`、`NoOverlapConstraintSpec`、`NoOverlap2DConstraintSpec`、`CumulativeConstraintSpec`、`ReservoirConstraintSpec`、算术 equality 约束：通用约束原语，必须通过约束对象引用 `rule_id`。线性约束支持 `enforcement_literals`，用于 assumption-core 诊断、Big-M/0-1 开关和规则启停。
- `CpSatSolveConfig`、`SolverParameterSpec`、`SolutionHintSpec`、`DecisionStrategySpec`：Agent 迭代求解控制面，用于设置 solver parameters、传入历史/启发式 hints、设置 assumptions、声明 decision strategies，并把 response stats 与 infeasible assumption core 交给 Debug Agent。
- `ObjectiveSpec`：目标函数，必须引用规则。
- `OptimizationProblemSpec`：完整问题定义。
- `RuleFirstPlan`：按硬规则、优先级、目标规则排序后的执行计划。

求解器必须先构造 `RuleFirstPlan`，再按规则顺序添加约束，最后添加目标函数。

## 3. Agent 协作架构

```text
业务专家 Agent (人类)
  输入业务痛点
  v
首席架构师 Agent
  分解任务 + 分析解空间
  v
数学建模 Agent                  数学降维与优化 Agent
  Big-M / 0-1变量               列生成 / 割平面 / 分解 / 剪枝
  v                             v
代码生成与执行 Agent
  运行 OR-Tools
  v
日志诊断 Debug Agent
```

`ai_orchestrated_optimization.agents` 将这套结构固化为机器可读拓扑，便于后续 Agent 生成代码、检查交接物和定位缺失证据。`ai_orchestrated_optimization.orchestration` 进一步把 `BusinessBrief`、`AgentHandoffArtifact`、`OptimizationProblemSpec`、CP-SAT 求解和 `AgentSolveReport` 连成可执行链路。

## 4. 数据流

1. 人类或上游 Agent 提供自然语言需求。
2. 首席架构师 Agent 输出问题边界、实体、规则列表和求解策略。
3. 数学建模 Agent 输出变量、约束、目标函数。
4. 数学降维与优化 Agent 输出列生成、割平面、分解、对称性破除等优化建议。
5. 代码生成与执行 Agent 生成 `OptimizationProblemSpec`，`run_agent_solve_workflow` 检查必需交接物后调用 `solve_cp_sat_problem`。
6. Debug Agent 读取 `AgentSolveReport` 中的状态、目标值、变量赋值、规则追踪、自动生成的 `ortools_run_logs` 和下一步建议。

## 5. 兼容区

`scheduler/` 仍包含历史 K12 排课应用，其规则 registry 当前仍有 audit/trace 兼容路径。`scheduler.rules.generic_bridge` 已将现有 `RuleExecutionPlan` 提升为通用 `RuleSpec -> RuleFirstPlan -> OptimizationProblemSpec` 的可执行影子模型，用于证明旧示例层可以进入规则优先合同。`scheduler.solver_params` 已把真实 scheduler 求解入口的 solver profile、时限、workers、gap、search branching 等参数先编译为通用 `CpSatSolveConfig`，再通过 `apply_cp_sat_solve_config` 应用到 OR-Tools `CpSolver`。`scheduler.app.conflict_detection` 已把小型 assumption-core 冲突诊断迁移为通用 `OptimizationProblemSpec` 求解。后续迁移方向是逐步把旧约束调用本身纳入通用 CP-SAT backend，而不是继续让排课入口显式决定约束顺序。

## 6. 开源发布要求

- Git 跟踪文件必须脱敏，不包含真实业务 Excel、运行输出、日志、截图或临时目录。
- K12 文档与 Profile 只能作为匿名示例存在，不能暴露真实学校或个人。
- 新增优化能力必须能用非排课测试证明框架通用性。
- 发布前至少运行通用框架测试、`verification/fixes/ai_or_acceptance_audit.py` 和工程卫生测试。

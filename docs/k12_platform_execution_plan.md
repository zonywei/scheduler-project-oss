# K12 示例域平台化执行计划

> 本文档现在是 `AI-Orchestrated Optimization` 的 K12 示例域迁移记录，不再定义整个仓库的唯一产品方向。通用规则优先内核以 `ai_orchestrated_optimization/` 为准；K12 排课保留为复杂业务示例和兼容应用。

## 北极星

把当前项目从“单校高中排课求解器”推进为“可服务中国 K12 学校的教务排课平台”。短期不推翻 OR-Tools CP-SAT 内核，不强迫学校放弃 Excel；先把学校差异、规则实例、输入适配和交付解释从核心求解代码里分离出来。

## 当前最高优先级问题

1. 学校 Profile 还不是一等公民。当前学校作息、晚自习日历、值班制度、个性化规则和输出口径仍分散在 YAML、Excel、约束函数和前端文案里。
2. 个性化规则仍有较强单校特征。具体教师、具体班级和具体日期规则应逐步迁移为“通用规则模板 + 当前学校 rule_instances”。
3. 输入适配层不足。不同学校的 Excel/OA 表结构不应直接牵动求解核心；核心应该接收标准 `SchoolProblem`。
4. 规则执行计划还不是唯一来源。registry 当前偏审计/展示，实际执行仍由求解入口显式调用约束函数。
5. 测试门禁需要从“当前学校可跑”升级到“跨校 fixture 可证明”。至少要有 base high school、寄宿制高中、初中、小学课后服务等最小匿名 fixture。
6. 工程卫生仍会直接影响商业交付。根目录生成物、生产模块裸 `print`、真实输出混入工作区，会降低交付可信度和开源可维护性。
7. 当前主 Web 静态入口仍要守住商业闭环：规则工作台、结果统计、批量导入、可执行微调、结果交付材料和运行状态必须在主入口直接可用。
8. 主 Web 的设计源不能再漂移。生产入口补 UI 时以 `edu-ops-scheduler-console/` 为准，不再保留 `legacy/` 作为可访问归档入口。

## 当前门禁状态

- Profile、日历作用域、K12 教务扩展、考前复习排课、Excel writer 策略、工程卫生和 gate manifest 的聚焦测试已通过。
- `test_commercial_acceptance_audit.py` 和 `test_web_rule_workspace.py` 已恢复通过，主 Web 静态入口重新覆盖规则工作台、结果统计、批量导入、可执行微调和结果交付合同。
- `verification/fixes/run_dev_gate.py` 仍需要全量复跑确认：下一阶段应以全量门禁为准继续清理剩余回归。
- 结论：下一阶段最高优先级不是继续扩展求解器，而是让主 Web 入口在 `edu-ops-scheduler-console/` 视觉与信息架构下承载完整商业闭环。

## 已落地的第一批平台化支点

- `scheduler/calendar.py`：统一日历事实源，减少周中/周末/晚自习作用域漂移。
- `scheduler/domain/school_profile.py`：建立 `SchoolProfile / CalendarSpec / PeriodGroup / PeriodSpec` 合同，先作为无副作用领域层接入。
- `scheduler/domain/rule_instance.py`：建立 `RuleInstance / CompiledRuleInstance` 合同，把学校差异描述为“通用规则模板 + 学校参数实例”，当前仅用于审计和迁移验证，不接管 solver 调用。
- `scheduler/domain/school_problem.py`：建立 `SchoolProblem` 标准问题模型和 adapter，先并行接收现有 `DayInputData` 与匿名 fixture mapping，不接管 solver 输入。
- `scheduler/domain/profile_catalog.py`：建立跨校 Profile catalog validator，一次性校验 `Profile + RuleInstance + SchoolProblem + RuleExecutionPlan`，用于新增学校模板时防漂移。
- `scheduler/rules/execution_plan.py`：建立 audit-only `RuleExecutionPlan`，把 registry 有效规则、学校规则实例和 runtime trace 放到同一张可校验计划里；它不执行约束，也不决定求解启停。
- `scheduler/app/service.py`：运行时在既有快照旁新增 `rule_execution_plan.json`，把 registry 计划和 runtime trace audit 写入 `outputs/meta` 与每次运行的 `_run_meta`，不改变既有四个快照文件。
- `profiles/current_school/profile.yaml`：当前学校 Profile 审计件，记录日历、作息、输入源、输出口径和第一批规则实例。
- `profiles/base_high_school`、`profiles/junior_day_school`、`profiles/primary_after_school`：匿名跨校 Profile 与 sample problem fixture，用于证明领域合同不只服务当前高中。
- `verification/fixes/tests/test_calendar_scope_contract.py`：固化日历作用域和 day-night bridge 周六晚自习扩展语义。
- `verification/fixes/tests/test_school_profile_contract.py`：固化通用高中模板、legacy config profile 映射和教务工作台星期来源。
- `verification/fixes/tests/test_rule_instance_contract.py`：固化规则实例校验、编译和跨校模板覆盖。
- `verification/fixes/tests/test_school_problem_adapter.py`：固化现有输入 reader 输出与跨校匿名 fixture 到 `SchoolProblem` 的适配合同。
- `verification/fixes/tests/test_rule_execution_plan.py`：固化当前学校/跨校规则实例能映射到 registry 计划，并能报告 trace 缺失、异常和错误行。
- `verification/fixes/validate_profiles.py` 与 `test_profile_catalog_validation.py`：把跨校模板校验做成机器可运行门禁，当前覆盖 4 个 Profile、3 个 sample problem。

## 下一步执行顺序

1. Profile 化当前学校：新增 `profiles/current_school`，把当前晚自习日历、作息、规则实例和输出口径从散落配置中映射出来。
2. 匿名 fixture：构造 `profiles/base_high_school` 和一套最小匿名输入数据，不依赖真实 Excel 就能跑基础白天课表。
3. RuleInstance 试点：从 personalized 里挑 3 条人名规则，改为通用模板 + 参数实例，保留旧 wrapper 验证语义不变。
4. 输入 adapter：把当前 `教师定位表.xlsx`、`白天规则.xlsx` 读取结果转换为标准 `SchoolProblem`，先并行输出不接管求解。
5. 执行计划：让 registry 产出 `RuleExecutionPlan` 审计件，先校验“计划中的规则”和“实际调用的规则”一致，再逐步接管执行。
6. 跨校门禁：新增 profile fixture tests、规则实例编译 tests、跨模式等价 tests，并把它们纳入 fast gate。
7. Web 集成：把 `edu-ops-scheduler-console/` 的页面分区逐步接入 `scheduler/app/static/` 的真实接口，先迁移 shell、导航、结果导出和数据导入，再迁移诊断、规则与求解页。

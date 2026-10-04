# AI-Orchestrated Optimization

面向 AI Agent 的运筹优化框架。人类用自然语言描述业务痛点，AI 将需求拆解为规则、变量、约束、目标函数、求解配置和诊断动作，最后通过 Google OR-Tools CP-SAT 运行求解。

本仓库已经不再定位为单一排课系统。原 `scheduler/` 能力保留为 K12 排课示例和兼容应用；新的通用内核位于 `ai_orchestrated_optimization/`，用于承载 CP-SAT 可表达的分配、排班、路径、装箱、资源容量、覆盖、选择、匹配等离散优化问题。

## WebMCP agent collaboration

The web workspace includes a WebMCP progressive enhancement for compatible browsers. Five structured tools let a browser agent inspect project readiness, review rules, diagnose deterministic conflicts, save a server-validated rule draft for human approval, and prepare the shared Solve view. The tools deliberately do not activate rules, start a solve, or publish a timetable; those consequential steps remain visible human decisions.

Implementation and challenge-period provenance are documented in [`docs/webmcp_challenge_2026.md`](docs/webmcp_challenge_2026.md). The live product continues to work in browsers without WebMCP support.

## 产品化方向

通用优化内核继续保持领域无关；面向中国学校的商业产品层位于 `scheduler/`。产品交互遵循“自然语言生成规则草案 -> 服务器白名单校验 -> 用户明确确认 -> 私有求解器执行 -> 可解释诊断”的边界，模型不会直接生成并执行代码，也不能任意写入求解配置。

Phase 0 已补齐版本化规则草案、OpenAI-compatible 国产模型适配边界、Python 3.14 文件上传兼容、项目安装元数据和一致的发布解释器入口，详见 [`docs/productization_phase0.md`](docs/productization_phase0.md)。

Phase 1 单校 SaaS 底座已实现：租户化 SQLite WAL、不可变工作区版本、审计账本、密码会话与 CSRF、服务端 RBAC、持久化 Job/独立 Worker、国产模型多供应商路由、配额与成本账本，以及登录/任务中心/AI 服务的前端闭环。数据合同见 [`docs/productization_phase1_contract.md`](docs/productization_phase1_contract.md)，发布候选证据见 [`docs/productization_phase1_release.md`](docs/productization_phase1_release.md)，部署运维见 [`docs/deployment_and_operations.md`](docs/deployment_and_operations.md)，商业与核心资产边界见 [`docs/security_and_commercialization.md`](docs/security_and_commercialization.md)。

## 单校 SaaS 本地启动

Docker 本机验收使用 `deploy/compose.local.yaml`，它只允许回环地址上的 HTTP 登录；生产环境必须使用 HTTPS 配置。

```powershell
Copy-Item deploy\.env.example deploy\.env
docker compose --env-file deploy\.env -f deploy\compose.yaml -f deploy\compose.local.yaml build
docker compose --env-file deploy\.env -f deploy\compose.yaml -f deploy\compose.local.yaml run --rm bootstrap
```

随后按 [`docs/deployment_and_operations.md`](docs/deployment_and_operations.md) 创建首个管理员并启动 `web` 与 `worker`。核心求解器只在 Worker 内执行；浏览器和模型供应商都不能提交或执行任意代码。

## 核心原则

- 规则第一：业务规则先形成可排序、可追踪的 `RuleSpec`，再进入建模和求解。
- AI 友好：接口面向 Agent 读写，优先使用清晰的数据合同，而不是隐藏在脚本里的隐式业务逻辑。
- 通用 CP-SAT：框架不绑定学校、班级、教师或课表；K12 排课只是一个示例域。当前通用后端覆盖 bool/int 变量、线性约束/线性域、reified/enforced 线性约束、布尔逻辑、Allowed/Forbidden Assignments、Element、Automaton、Inverse、Circuit、MultipleCircuit、AllDifferent、Interval、NoOverlap、NoOverlap2D、Cumulative、Reservoir、Abs/Max/Min/Multiplication/Division/Modulo Equality、线性目标，以及 Agent 迭代求解所需的 solver parameters、solution hints、assumptions、decision strategies 和 response stats。
- 全面脱敏：真实输入、历史输出、运行日志、临时产物、热启动池和截图不进入 GitHub 发布版本。
- 可诊断：求解过程保留规则计划、应用顺序、求解状态和后续 Debug Agent 可消费的证据。

## Agent 架构

```text
业务专家 Agent (人类)
  -> 首席架构师 Agent
    -> 数学建模 Agent
    -> 数学降维与优化 Agent
      -> 代码生成与执行 Agent
        -> 日志诊断 Debug Agent
```

默认拓扑由 `ai_orchestrated_optimization.build_default_agent_architecture()` 提供。它明确记录：

- `business_expert -> chief_architect`: business pain description
- `chief_architect -> mathematical_modeler`: task decomposition
- `chief_architect -> dimension_reduction_optimizer`: solution-space analysis
- `mathematical_modeler -> code_execution`: model artifacts
- `dimension_reduction_optimizer -> code_execution`: optimization artifacts
- `code_execution -> debug_diagnostics`: OR-Tools run logs

`ai_orchestrated_optimization.run_agent_solve_workflow()` 提供可执行链路：输入 `BusinessBrief`、多 Agent `AgentHandoffArtifact` 和 `OptimizationProblemSpec`，先检查必需交接物，再按规则优先计划运行 CP-SAT，最后生成 `AgentSolveReport`，其中包含求解结果、规则追踪、自动生成的 `ortools_run_logs` 交接物和 Debug Agent 可消费的摘要。旧 `scheduler/` 入口的 solver 参数也已通过 `CpSatSolveConfig` 和 `apply_cp_sat_solve_config` 接入同一控制面。

## 快速验证

Python 版本约束：`>=3.11,<3.15`，当前本地工作区使用 Python 3.14 和 OR-Tools 9.15。

```powershell
.\verify_environment.ps1 -Dev
.\.venv\Scripts\python.exe -m pytest verification\fixes\tests\test_ai_or_framework.py -q
.\.venv\Scripts\python.exe verification\fixes\ai_or_acceptance_audit.py
.\.venv\Scripts\python.exe -m pytest verification\fixes\tests\test_engineering_hygiene.py -q
```

通用框架最小示例见 `verification/fixes/tests/test_ai_or_framework.py`：它用布尔变量、线性约束和目标函数求解任务分配问题，也用布尔逻辑、表约束、Element、Automaton、Inverse、Circuit、MultipleCircuit、AllDifferent、Interval、NoOverlap、NoOverlap2D、Cumulative、Reservoir 和算术 equality 求解非排课的唯一性、状态机、路径、资源容量和派生变量问题，并验证 hints、assumptions、decision strategies、solver parameters 与 Debug Agent 可消费的 assumption core。

## 目录结构

```text
ai_orchestrated_optimization/
  agents.py          # 多 Agent 拓扑
  contracts.py       # 变量、区间、规则、约束、目标、问题合同
  orchestration.py   # 自然语言 brief、多 Agent 交接物、求解和 Debug 报告链路
  planning.py        # 规则优先执行计划
  cp_sat_backend.py  # OR-Tools CP-SAT 通用后端
scheduler/
  rules/generic_bridge.py  # K12 规则执行计划到通用规则优先合同的迁移桥
  ...                      # K12 排课示例和兼容应用
profiles/
  ...                # 匿名示例 Profile
verification/fixes/
  ...                # 开源卫生、环境、规则和回归门禁
docs/
  ai_or_framework_architecture.md
  open_source_release_audit.md
```

## 开源边界

仓库不应跟踪以下内容：

- `tmp/`, `outputs/`, `scheduler/outputs/`
- `.venv/`, `.pytest_cache/`, `__pycache__/`
- `*.xlsx`, `*.zip`, 生成的截图、`*.out`, `*.err`, `*.log`；版本化的产品静态图片除外
- 真实学校、教师、学生、手机号、邮箱、地址、审批记录或历史求解结果

`verification/fixes/tests/test_engineering_hygiene.py` 会检查生成物是否被 Git 跟踪。发布前应以 `git status --short` 和门禁测试共同确认。

## License

Apache-2.0; see [LICENSE](LICENSE). Bundled Cytoscape.js and Remix Icon assets retain their own copyright and license notices in their vendor files.

# R-08 模块拆分记录

## 当前热点
本轮量化得到的最大 Python 文件：

| 文件 | 行数 | 风险 |
|---|---:|---|
| `scheduler/snapshot_diagnostics.py` | 2125 -> 1953 非空行 | 诊断报表构建、展示文案、Excel 写入混在一起 |
| `scheduler/joint_solver.py` | 2073 -> 1980 非空行 | 白天/晚自习联合建模与运行编排密集 |
| `scheduler/model/constraints/day_weekday_constraints.py` | 1915 -> 1678 非空行 | 多个白天工作日约束与报告写出集中 |

## 本轮拆分
- 新增 `scheduler/diagnostics/display_catalog.py`。
- 将多解诊断中的中文规则 fallback 文案、个性化规则描述和查寝软约束 fallback 从 `snapshot_diagnostics.py` 移出。
- `snapshot_diagnostics.py` 从 2125 行降到 1953 行。
- 新增 `scheduler/joint_runtime.py`。
- 将联合求解的轻量 solution callback、`DayBuildResult`、`NightBuildResult` 和晚自习 assignment 还原函数从 `joint_solver.py` 移出。
- `joint_solver.py` 从 2073 非空行降到 1980 非空行。
- 新增 `scheduler/model/constraints/day_weekday_reports.py`。
- 将白天工作日约束中的低课时、双班、软时间偏好、教师连贯性、AM4+PM1、M1 上限与核心教师日负载报告写出函数移出。
- `day_weekday_constraints.py` 从 1915 非空行降到 1678 非空行，报告模块为 261 非空行。

## 语义边界
本轮只移动诊断展示层常量、联合运行时轻量结构和报告写出函数：
- 不改 CP-SAT 变量、约束、目标函数、求解参数。
- 不改 event_log 原始字段。
- 不改 Excel sheet 结构。
- 不改 `run_joint(...)` 外部入口。
- `day_weekday_constraints.py` 保留原导入路径，外部调用方仍可从旧模块导入报告函数。

## 门禁
`verification/fixes/tests/test_module_decomposition.py` 保障：
- `snapshot_diagnostics.py` 保持在 2000 行以下。
- `joint_solver.py` 保持在 2000 行以下。
- `day_weekday_constraints.py` 保持在 1800 行以下。
- 诊断展示目录存在且关键文案完整。
- `snapshot_diagnostics` 仍能通过目录返回相同个性化规则中文名。
- `joint_runtime.py` 可导入，且保存联合求解运行时结构对象。
- `day_weekday_reports.py` 可导入，且旧模块继续 re-export 关键报告函数。

## 后续
`R-08` 当前已将所有 2000+ 非空行热点压到门禁阈值以下。后续若继续降复杂度，可再处理：
- `joint_solver.py` 的运行配置解析与归档编排进一步拆分。
- `day_weekday_constraints.py` 的约束族按“教师负载/班级均衡/连续性”分组拆分。

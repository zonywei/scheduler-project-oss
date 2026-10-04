# 商业级验收审计

## 目的

把“面向真实中国 K12 学校教务人员的商业级排课系统”拆成可执行检查项，避免只用测试通过或功能数量来误判已经可交付。

## 命令

```powershell
py -3 verification/fixes/commercial_acceptance_audit.py
py -3 verification/fixes/commercial_acceptance_audit.py --strict-release
```

## 输出含义

- `overall: pass`：结构能力齐备，且当前结果有正式可行候选课表。
- `overall: blocked`：结构能力齐备，但当前没有正式可行候选课表，不能宣布商业级目标完成。
- `overall: fail`：缺少必须存在的代码、文档或验证产物。

严格模式要求当前批次 `publish_assessment.summary.status=ready`，并要求结果包根目录至少包含 `delivery_manifest.json` 与唯一 `status.json`。

## 检查维度

- 目标用户与外部调研：`docs/commercial_k12_scheduler_research.md`。
- 后端商业化服务：求解前校验、发布评估、结果预览、诊断放宽、交付清单和教务对象。
- Web 主流程：教师定位、规则、自然语言规则、冲突检测、求解运行、求解结果、教务工作台、课表预览和结果导出。
- 核心求解与输出：联合求解、运行时拆分、统一输出根、Excel writer、诊断展示目录。
- K12 教务对象范围：常见教务能力、学校 Profile、跨校 fixture 和风险检测。
- 教务表格流转：Excel/CSV 模板下载、当前表导入预览、导入不自动保存确认。
- 交付安全与当前文档：README、架构说明、平台执行计划、输出策略、Excel 策略和工程卫生。
- 验证门禁覆盖：商业化关键测试是否进入 `run_dev_gate`。
- 当前可发布课表：当前正式结果必须有可行解、课表文件并通过发布评估。

## 当前口径

审计不会把“当前配置已证明无解”的状态包装成完成。只要最近正式结果仍是 `INFEASIBLE`、无课表文件，或最近批次是诊断试跑，审计会给出 `blocked`，提示必须先完成一次正式可行求解再谈商业交付。

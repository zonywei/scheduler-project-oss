# 测试门禁矩阵

## 目标
把排课排障期间验证过的关键检查固化成可重复执行的门禁，避免后续重构再次出现“状态提示与真实产物不一致”“输出目录双根”“配置加载口径分裂”等回归。

## 门禁分层

| 层级 | 命令 | 适用场景 | 覆盖重点 |
|---|---|---|---|
| 开发快速门禁 | `powershell -ExecutionPolicy Bypass -File .\verification\fixes\run_dev_gate.ps1` | 每次后端/规则/输出路径改动后 | 依赖版本、清理边界、随机种子、loader 单入口、输出根目录、求解状态摘要、发布评估、交付清单、诊断文案、Web 规则工作区 |
| 本机完整冒烟 | `powershell -ExecutionPolicy Bypass -File .\verification\fixes\run_dev_gate.ps1 -IncludeLocalSmoke` | 本机有真实学校 Excel 输入时 | 在快速门禁基础上增加 `scheduler.smoke_check`，校验当前本机配置和输入链路 |
| 发版门禁 | `powershell -ExecutionPolicy Bypass -File .\verify_release.ps1` | 准备提交/交付前 | 要求 git clean，先跑开发快速门禁，再跑严格商业验收；当前批次不是 `ready` 时必须失败 |

## Python 依赖
运行快速门禁前安装开发依赖：

```powershell
py -3 -m pip install -r requirements-dev.txt
```

如使用项目虚拟环境，PowerShell 入口会优先选择 `.venv\Scripts\python.exe`；否则回退到 `py -3`。

## 当前门禁清单来源
- 机器可执行清单：`verification/fixes/gate_manifest.py`。
- 入口脚本：`verification/fixes/run_dev_gate.py`、`verification/fixes/run_dev_gate.ps1`。
- 清单自检：`verification/fixes/tests/test_dev_gate_manifest.py`。

## 本轮排障相关强约束
- 不再只看“是否存在结果文件”，必须同时检查求解状态、`solution_count`、课表文件数和发布评估。
- 项目根 `outputs/` 是唯一运行产物根，`scheduler/outputs/` 必须被拒绝。
- `random_seed`、时限、worker、快照等运行参数必须进入状态和交付清单，便于复现。

# 参与贡献

欢迎提交可复现的问题和小范围改进。请在 issue 或 PR 中说明业务场景、期望结果、实际结果，以及你使用的 Python 版本；涉及规则或求解结果时，附上不含真实学校信息的最小示例。

## 本地验证

项目支持 Python 3.11–3.14，CI 使用 Python 3.13。先在独立虚拟环境安装开发依赖：

```bash
python -m venv .venv
python -m pip install -r requirements-dev.txt
python verification/fixes/run_dev_gate.py
```

在 Windows PowerShell 中，激活虚拟环境后执行相同的 `python` 命令即可。修改规则白名单、确认流程或求解器时，请增加能验证实际行为的回归测试，并确保未经确认的草案不能进入求解。

## 数据与提交范围

只使用匿名或合成的学校、教师和学生数据。不要提交真实工作簿、课表、截图、日志、数据库、密钥、部署配置或本地生成目录；具体排除范围见 [README 的开源边界](README.md#开源边界)。提交前检查 `git status --short`，确认新增文件均可公开。

PR 请描述改动前后的行为、运行过的验证命令，以及仍未覆盖的场景。运行结果或性能数据应注明测试环境与输入规模；不要把模拟结果表述为线上效果。

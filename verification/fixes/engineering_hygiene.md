# R-09/R-10 工程卫生记录

## 处理范围
- `R-09`：根目录临时文件候选。
- `R-10`：生产模块裸 `print(...)` 输出。
- `R-11`：根目录生成截图 / UI 快照候选。

## 本轮处理
- 根目录按 `temp*`、`tmp*`、`debug*`、`dump*`、`scratch*`、`*.tmp`、`*.bak`、`*.log` 扫描，未发现临时文件候选。
- 根目录按 `*.png`、`*snapshot*.md` 扫描，生成截图 / UI 快照应放在 `output/web/screenshots/` 或临时目录，不再进入仓库根目录。
- `.gitignore` 明确隔离 `outputs/`、`scheduler/outputs/`、`tmp/`、`.cache/`、`cache/` 与 `output/web/screenshots/`。
- `scheduler/app/web.py` 的启动提示改为 `logger.info(...)`。
- `scheduler/output/day_exporter.py` 的导出空格警告改为 `logger.warning(...)`。
- `scheduler/snapshot_diagnostics.py` 的诊断自检输出改为 logger。

## 门禁
新增 `verification/fixes/tests/test_engineering_hygiene.py`：
- `test_no_temp_artifacts_in_repo_root` 禁止根目录临时文件候选进入工作树。
- `test_no_generated_snapshots_in_repo_root` 禁止根目录生成截图 / UI 快照进入工作树。
- `test_gitignore_keeps_runtime_artifacts_out_of_core_tree` 固化运行产物、缓存和预览图忽略策略。
- `test_no_print_calls_in_production_scheduler_modules` 禁止生产模块重新引入裸 `print(...)`。

允许例外：
- `scheduler/tests/**`
- `*_smoke_test.py`
- `scheduler/smoke_check.py`
- `verification/**`

这些脚本本身承担命令行验证职责，保留 stdout PASS 标记。

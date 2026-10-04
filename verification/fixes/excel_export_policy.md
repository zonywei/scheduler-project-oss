# Excel 导出策略

## 结论
项目内 `.xlsx` 写入统一使用 `openpyxl`。原因：
- 现有课表排版、分页、富文本、预览读取都基于 `openpyxl`。
- `openpyxl` 可在写出后继续加载并修改样式，适合当前“先生成、再做排版调整”的导出链路。
- 避免白天和晚自习分别使用不同引擎导致样式、日期/空值、sheet 兼容行为不一致。

## 代码入口
- 统一 writer：`scheduler/output/excel_writer.py`
- pandas 写入入口必须使用：`create_excel_writer(...)`
- 手工排版工作簿继续直接使用 `openpyxl.Workbook` / `load_workbook`

## 门禁
`verification/fixes/tests/test_excel_export_policy.py` 覆盖：
- 默认引擎必须是 `openpyxl`
- `scheduler/**/*.py` 不得显式使用 `engine="xlsxwriter"`
- 除策略模块外，不得直接调用 `pd.ExcelWriter`
- 晚自习导出文件可被 `openpyxl` 正常读取，并包含排课与晚查寝 sheet

## 依赖
最小运行依赖不再要求 `xlsxwriter`。如果未来确需引入第二引擎，必须先补充明确的产物差异测试和发布兼容说明。

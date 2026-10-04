# Edu Ops Console UI Source

`edu-ops-scheduler-console/` is the source of truth for the production Web shell design.

The production entry under `scheduler/app/static/` should keep the live API wiring, access control, import/save flows, solver controls, result preview, delivery materials, and audit behavior. When UI surface or copy needs to be filled back into the real app, it should follow the `edu-ops-scheduler-console` IA and visual language:

- Brand: `排课工程 / 教务排课系统`.
- Primary navigation: `首页概览`, `数据导入`, `晚自习排课`, `诊断处理`, `联合求解`, `结果导出`.
- Page classes: `home-page page-home`, `screen-page page-data`, `screen-page page-rule`, `screen-page page-diagnostics`, `screen-page page-solver`, `screen-page page-release`.
- Visual system: soft blue-white education console, left sidebar, metric cards, panels, role/notice footer, dense table-first operational layouts.

Do not treat `scheduler/app/static/legacy/` as a design source or compatibility archive. The production UI should carry current behavior directly.

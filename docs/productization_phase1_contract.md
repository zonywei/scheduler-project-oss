# 产品化 Phase 1 合同：持久化、安全与任务边界

本阶段把 Phase 0 的可信 AI 规则入口升级为可部署的单校 SaaS 运行底座。核心求解器继续保留在服务端；浏览器、模型供应商和普通用户都只能通过受控数据合同调用它。

## 现状审计

- 业务写状态集中在 `scheduler/config/web_overrides.yaml`，缺少并发版本控制和租户作用域。
- Web 角色由浏览器提交的 `X-Scheduler-Role` 决定，属于界面演示能力，不是真实身份认证。
- 求解生命周期依赖 `solve_service.py` 的进程内全局变量；服务重启后无法可靠认领、恢复或审计任务。
- 求解结果已有独立运行目录和 `status.json`，可以继续作为大文件证据层，但任务索引必须进入数据库。
- 当前主 Web 已覆盖单校业务闭环；前端工程化应保持现有真实 API 能力和 `edu-ops-scheduler-console/` 的设计源。

## 目标边界

```text
浏览器
  -> 身份会话 + CSRF
  -> 租户化 API
  -> SQLite/PostgreSQL 仓储
       -> Workspace / RuleDraft / Audit / SolveJob / ModelUsage
  -> 隔离 Worker
       -> 私有规则编译器 + OR-Tools 求解器
       -> 租户运行目录与交付包
```

Phase 1 本地版本使用 SQLite WAL，所有仓储方法强制 `organization_id`，并保留迁移编号。生产扩容时可在不改变领域合同的前提下替换为 PostgreSQL。

## 数据合同

- `organizations`：学校/组织租户；即使首发只有一个学校，也不允许使用无租户记录。
- `users / sessions`：真实用户、服务端角色和可撤销会话。
- `workspace_snapshots / workspace_versions`：当前工作区及不可变版本，采用乐观并发 revision。
- `rule_drafts`：版本化 AI/本地规则草案，继续执行 Phase 0 白名单与人工确认。
- `audit_events`：跨配置、规则、认证、任务和交付的统一审计账本。
- `solve_jobs`：排队、运行、取消、完成和失败状态，不以 Web 进程内变量作为事实源。
- `model_usage_events`：供应商、模型、Token、成本和请求编号，为按量付费与配额提供证据。

## 兼容迁移原则

1. 先建立数据库和 YAML 导入工具，不自动删除或覆盖现有 YAML。
2. 通过显式运行模式切换数据源，验证一致后再把数据库设为默认。
3. 配置保存、规则确认和审计必须在同一数据库事务中完成。
4. 大型 Excel、日志和结果包保留在文件对象层，数据库只记录租户化路径、状态和校验元数据。
5. 所有读取和写入测试必须证明租户 A 无法观察或修改租户 B 的记录。

## 完整验收顺序

1. 数据库迁移、租户仓储、YAML 导入与备份恢复。
2. 密码哈希、登录/登出、HttpOnly 会话、CSRF、服务端 RBAC。
3. 持久化 Job API、Worker 认领、心跳、取消、服务重启恢复。
4. 模型路由、故障降级、配额、Token 与成本账本。
5. 前端登录、任务中心、规则版本、用量页和统一错误状态。
6. 本地部署、健康检查、迁移检查、全量门禁和发布候选审计。

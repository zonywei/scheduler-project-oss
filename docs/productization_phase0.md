# 产品化 Phase 0：可信 AI 规则入口与可部署底座

本阶段把现有求解框架向“国产模型可替换、规则可审计、用户明确确认、服务端核心不下发”的产品架构推进。它不试图一次性完成多租户 SaaS，而是先固定后续前端、模型网关和求解服务共同依赖的安全合同。

## 已落地能力

### 1. 版本化规则草案

自然语言解析结果统一使用 `scheduler.rule-draft.v1`：

- `status=draft`：模型或本地解析器只能生成草案。
- `validation`：服务器返回错误、警告和是否需要人工确认。
- `provenance`：记录本地/模型来源、供应商、模型和生成时间。
- `confidence`：供界面提示，不作为自动应用依据。
- `confirmation`：必须显式确认后才能转为 `active`。

当前服务器只允许两类已经接入真实求解配置的补丁：

- 教师指定星期的晚自习禁排。
- 教师上午第一节禁排。

模型返回其他路径、任意写配置或伪造执行操作时，草案会被拒绝并回退到本地解析器。新增规则能力时，应先增加规则实现和回归测试，再扩展服务器白名单。

### 2. 模型供应商边界

`scheduler.app.model_gateway` 提供最小的 OpenAI-compatible JSON 适配层：

- 供应商、Base URL、模型和密钥环境变量由服务端配置。
- 同时支持 Chat Completions 与 Responses API；Responses 请求默认流式读取并固定关闭供应商响应留存。
- 远程接口必须使用 HTTPS；仅 localhost 可以使用 HTTP。
- 密钥不会进入浏览器、规则草案或错误信息。
- 请求、提示词和响应均有限额。
- 上层仅接收 JSON 对象及脱敏的用量、请求编号元数据。

该接口用于接入国产模型，但业务代码不绑定具体供应商。生产环境应至少配置两家经过同一规则评测集验证的供应商，并支持路由、限额和降级。

### 3. 人工确认 API 流程

```text
POST /api/nl-rules/parse
  -> 返回 draft + validation + provenance

用户在界面检查草案

POST /api/nl-rules/add
  body.confirm 必须为 true
  -> 服务端重新校验白名单
  -> 转为 active
  -> 作为独立规则层叠加到本轮有效配置
```

前端按钮只是确认入口，服务器仍是最终安全边界。直接绕过界面调用 API，也无法在没有 `confirm=true` 或白名单校验失败时应用规则。草案不会反向改写人工维护的基础规则；移出草案时只删除这一层，原有配置和其他已确认草案保持不变。

### 4. Python 3.14 与安装入口

- 文件上传不再依赖 Python 已移除的 `cgi` 模块，改用标准库 MIME 解析，并限制总大小、字段数量和文件名。
- `pyproject.toml` 声明构建后端、运行依赖、包发现、静态资源和 `scheduler-web` 命令。
- `verify_release.ps1` 优先使用项目 `.venv`，避免发布门禁绕过已验证解释器。

验证命令：

```powershell
.\.venv\Scripts\python.exe -m pytest verification\fixes\tests\test_productization_foundation.py -q
.\.venv\Scripts\python.exe verification\fixes\run_dev_gate.py
.\.venv\Scripts\pip.exe install .
scheduler-web --host 127.0.0.1 --port 8765
```

## 明确未做的事情

Phase 0 仍不是完整 SaaS。后续优先级应保持为：

1. 把规则草案和版本记录迁移到数据库，而不是单机 YAML。
2. 将求解入口拆为异步 Job API 与隔离 Worker。
3. 建立学校/组织/用户/RBAC 和完整租户隔离。
4. 建立真实学校规则评测集、模型路由、额度与成本账本。
5. 将当前单文件静态控制台工程化为可独立部署的前端，并补齐登录、租户、任务与错误状态管理，固化数据导入、规则确认、求解、诊断、调整、导出的闭环。

核心求解器、规则编译器和诊断实现应始终保留在服务端私有边界；模型只接触完成任务所需的最小化结构化上下文。

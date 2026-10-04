# Rule V2 正式数据模型

状态：设计与实现共同遵守的正式契约  
版本：`scheduler.rule.v2`  
目标：支持默认规则、全校统一规则、年级学科规则、特殊规则和自然语言 AI 草案，同时保持可验证、可审计和可编译。

## 1. 为什么需要 V2

现有 `scheduler.rule-draft.v1` 是可信 AI 入口的安全起点，但只支持：

- `ban / require` 两种动作；
- `day / night` 两种范围；
- 教师目标；
- 两类白名单补丁。

它无法完整表达学期有效期、单双周、班级/年级/学科/场地、例外、规则继承、版本快照和复杂关系。Rule V2 不允许模型生成任意 Python 或直接改求解配置，而是让模型生成受限、版本化、可校验的规则合同，再由服务端编译器决定是否能进入正式求解。

## 2. 三个必须分开的维度

### 2.1 业务层级 `policy_level`

- `default`：系统默认规则，可在学校项目内覆写，但不修改系统模板。
- `schoolwide`：全校统一规则。
- `grade_subject`：年级、学科、课程或活动层规则。
- `special`：教师、班级、活动、日期等特殊要求。

### 2.2 约束强度 `strength`

- `hard`：必须满足，否则方案不可行。
- `soft`：允许违反，但产生可解释代价；必须有优先级或权重。
- `advisory`：仅提示或发布检查，不直接进入优化目标。

### 2.3 生命周期 `status`

- `draft`：可编辑草案。
- `needs_clarification`：自然语言仍有歧义，需要教务补充。
- `validated`：结构、引用和编译能力校验通过，等待确认。
- `active`：已由有权限的人确认，进入活动规则集。
- `paused`：暂不参与新规则集，历史版本仍可追溯。
- `superseded`：被新版本替代。
- `retired`：不再使用，只读保留。
- `rejected`：明确拒绝的 AI/导入草案。

视觉上不得只靠一种颜色同时表达这三个维度。建议：强度用形状和文字徽标，业务层级用色带，状态用开关/状态点和文字。

## 3. 规范对象

```json
{
  "schema_version": "scheduler.rule.v2",
  "id": "rule.teacher.night_no_pm3.01",
  "version": 3,
  "status": "validated",
  "title": "有晚自习的教师当天不排下午第 3 节",
  "description": "减少晚自习教师当日连续工作时长。",
  "policy_level": "special",
  "domain_tags": ["teacher", "day-night-link", "workload"],
  "strength": {
    "type": "hard",
    "priority": null,
    "weight": null
  },
  "scope": {
    "include": [
      {
        "entity": "teacher",
        "match": {"ids": ["teacher_104", "teacher_218"]}
      }
    ],
    "exclude": []
  },
  "effective_time": {
    "range": {"type": "project_term"},
    "week_pattern": "all",
    "days": [],
    "slots": []
  },
  "constraint": {
    "kind": "implication",
    "when": {
      "fact": "teacher.has_activity",
      "params": {"activity_type": "night_study", "same_day": true}
    },
    "assert": {
      "fact": "teacher.lesson_count",
      "operator": "eq",
      "value": 0,
      "params": {"period": "PM3", "same_day": true}
    }
  },
  "exceptions": [
    {
      "id": "exception.exam_week",
      "behavior": "exclude",
      "reason": "考试周使用临时作息",
      "scope": {"include": [{"entity": "calendar_tag", "match": {"values": ["exam_week"]}}]},
      "effective_time": {"range": {"type": "date_range", "start": "2026-11-09", "end": "2026-11-15"}}
    }
  ],
  "implementation": {
    "type": "constraint_ast",
    "compiler": "scheduler.rule-compiler",
    "compiler_version": "2.0",
    "support": "supported",
    "legacy_rule_ref": "personalized_constraints.enable_xhd_night_no_pm3"
  },
  "provenance": {
    "source_type": "ai",
    "source_text": "两位晚自习老师当天最后一节不要再排课，考试周除外",
    "parser": "structured-rule-agent",
    "provider_id": "domestic-provider-a",
    "model": "model-name",
    "confidence": 0.88,
    "generated_at": "2026-07-27T08:00:00Z"
  },
  "governance": {
    "requires_confirmation": true,
    "confirmed": false,
    "confirmed_by": null,
    "confirmed_at": null,
    "created_by": "user_001",
    "created_at": "2026-07-27T08:00:00Z",
    "updated_by": "user_001",
    "updated_at": "2026-07-27T08:02:00Z"
  },
  "validation": {
    "status": "passed",
    "errors": [],
    "warnings": [],
    "impact_summary": {
      "matched_teachers": 2,
      "matched_classes": 0,
      "matched_slots": 2
    }
  }
}
```

## 4. 作用范围

`scope.include` 和 `scope.exclude` 都由实体选择器组成。首发必须支持：

- `teacher`
- `class`
- `grade`
- `subject`
- `subject_group`
- `course_or_activity`
- `room`
- `resource`
- `campus`
- `calendar_tag`

选择器只允许稳定 ID 或经服务端解析的属性条件。显示名称用于界面，不作为求解主键。关系型选择器，例如“高二物理任课教师”“所有班主任”，必须先解析为可审计的 ID 集合和解析时间；基础数据变化后重新解析并标记规则集为 `dirty`。

## 5. 作用时间

`effective_time.range.type` 支持：

- `project_term`：默认值，自动继承项目学期起止时间。
- `date_range`：指定日期范围。
- `calendar_tags`：考试周、活动周等日历标签。

`week_pattern` 支持：

- `all`
- `a_week`
- `b_week`
- `odd_week`
- `even_week`
- `specific_weeks`

规则还可以限定星期、节次、时间段和特殊日。日期优先于抽象星期；固定公休和临时停课由项目日历统一裁剪，不让每条规则重复保存一份公休日列表。

## 6. 例外

每条例外都是有 ID、原因、作用对象和作用时间的结构化对象：

- `exclude`：命中对象不参与本规则。
- `soften`：命中对象把硬约束降为指定软约束。
- `override`：在限定范围内使用例外自己的约束值。
- `note`：只记录业务说明，不改变求解。

例外不能用自由文本偷偷改变约束。自由文本只保存原因；真正行为必须结构化并重新校验。例外默认继承主规则的学期范围，除非明确设置更窄的有效期。

## 7. 约束表达

### 7.1 首发原语

- `availability`：允许/禁止某对象出现在某时间。
- `placement`：固定、偏好或避免某位置。
- `cardinality`：次数、上限、下限、恰好次数。
- `sequence`：连续、不得连续、相邻、间隔。
- `distribution`：跨天、上下午或周期分布。
- `coupling`：同天、同时、先后或联动。
- `separation`：两个活动不得同天/同时/相邻。
- `capacity`：教室、资源和人员容量。
- `workload`：教师、班级或资源工作量。
- `balance`：公平性和差异最小化。
- `lock`：锁定已确认安排。
- `implication`：如果 A，则要求 B。
- `composite`：由 `all / any / not` 组合上述受限原语。

### 7.2 禁止项

- 不允许 AI 返回 Python、SQL、YAML 路径写入或任意表达式求值。
- 不允许浏览器直接提交求解器变量名。
- 不允许 `eval`、动态 import 或未注册编译器。
- 不允许把 `support=unsupported` 的草案激活为正式规则。

### 7.3 可扩展编译器

Rule V2 支持两种首发实现类型：

1. `catalog_ref`：引用现有 93 条成熟规则的稳定键及参数，用适配器完成 V2 映射。
2. `constraint_ast`：使用受限原语生成通用运筹合同，由注册编译器映射到 CP-SAT。

后续新增规则不再扩充一个巨型 `if/else` 翻译器，而是注册独立编译器插件。每个插件必须声明：支持的原语、参数 schema、所需实体、产生的硬约束/软目标、诊断标签和回归测试。

## 8. AI 规则生成流程

```mermaid
flowchart LR
    A[教务自然语言] --> B[识别歧义]
    B -->|信息不足| C[追问作用对象 时间 强度 例外]
    B -->|信息充分| D[生成 Rule V2 草案]
    C --> D
    D --> E[结构与实体校验]
    E --> F[编译能力检查]
    F --> G[冲突与影响预览]
    G --> H[教务明确确认]
    H --> I[激活新规则版本]
    I --> J[生成规则集快照]
```

AI 可以提出任何可描述的业务需求，但不能承诺任何需求都已被求解器支持。返回必须区分：

- `supported`：可以编译并进入求解。
- `partial`：只有部分语义可编译，必须让用户选择是否接受缩减版本。
- `unsupported`：保留草案和原始需求，进入规则能力待办，不能激活。

人工确认发生在结构化预览之后，而不是确认一段未经解释的自然语言。

## 9. 版本和规则集快照

- `id` 标识同一条业务规则，`version` 每次编辑递增。
- `active` 版本不可原地修改；编辑会复制为新 `draft`。
- 规则集快照包含全部活动规则的 `id + version + content_hash`。
- 每个求解任务绑定一个不可变规则集快照。
- 规则变更后，基于旧快照的候选立即变 `stale`。
- 默认规则的学校修改使用新作用层，不直接改系统模板。
- 同一作用范围出现相互矛盾的硬规则时，规则集必须 `blocked`；不得依赖后写覆盖先写。

## 10. 持久化建议

正式存储建议从当前单表草案逐步演进为：

- `rules`：稳定规则 ID、项目/组织归属和当前生命周期。
- `rule_versions`：不可变 Rule V2 JSON、hash、创建人和时间。
- `project_rule_bindings`：项目启用哪个规则版本及其排序/层级。
- `ruleset_snapshots`：求解时冻结的活动规则集合。
- `rule_validation_results`：结构、引用、冲突、编译和影响检查结果。

现有 `rule_drafts` 表可以在迁移期继续存 `scheduler.rule-draft.v1`，并增加 V1 → V2 读取适配器；不能直接把旧 payload 当作完整 V2。

## 11. 与现有代码的迁移顺序

1. 为 Rule V2 增加纯领域模型、校验器和 JSON schema，不连接 UI。
2. 把现有业务规则目录只读投影成 `catalog_ref` 类型的 Rule V2。
3. 建立规则集快照，令 SolveJob 同时绑定 workspace revision 和 ruleset revision。
4. 把自然语言规则草案升级为 V2，保留显式人工确认和供应商来源。
5. 增加受限 `constraint_ast` 编译器；每扩展一种原语都先补求解和诊断测试。
6. 新规则中心只读 V2 API；旧配置编辑器保留为管理员兼容入口。
7. 逐步拆分巨大兼容桥，始终保留 legacy 与 V2 编译结果的 parity test。

## 12. 正式版界面要求

- 规则总览默认按业务层级分组，可切换硬/软、学科、特殊、AI 草案和有问题规则视图。
- 大量规则使用紧凑列表/表格，不以 93 张大卡片平铺。
- 每一行同时显示名称、强度、业务层级、作用范围摘要、有效期、状态和问题数。
- 编辑页分为：规则内容、作用对象、作用时间、例外、求解支持、版本记录。
- 自然语言入口是创建/修改草案的方式之一，不占据规则中心首屏主体。
- AI 草案必须展示“系统理解了什么、影响谁、何时生效、哪些部分不支持”。
- 删除活动规则使用停用/退休；历史任务引用的版本永远保留。

## 13. 必须通过的 Rule V2 验收

- 默认有效期确实继承项目学期。
- A/B 周、周末、固定公休和日期例外有独立测试。
- 教师、班级、年级、学科、活动、场地和资源选择器可校验引用。
- 硬/软强度与业务层级不会互相覆盖。
- 每条例外都有结构化行为、原因、范围和有效期。
- AI 草案不能绕过人工确认，不能激活不受支持的语义。
- 同一规则的历史版本和被其求解的候选可双向追溯。
- 修改规则会产生新规则集快照并让旧候选过期。
- 现有成熟规则迁移后与旧求解结果保持 parity。


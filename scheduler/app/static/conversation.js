/* Premium conversational scheduling workspace. */

VIEW_META.conversation = [
  "高级会员",
  "AI 对话排课",
  "像和排课专家对话一样，从基础数据、需求追问到规则确认和工业级排课。",
];
VIEW_BODY_CLASSES.conversation = "screen-page page-conversation";

for (const action of [
  "conversation-create",
  "conversation-send",
  "conversation-confirm",
  "conversation-solve",
  "conversation-upload-trigger",
  "open-conversation-optimization",
]) {
  ACTION_PERMISSIONS[action] = "conversation.schedule";
}

state.conversation = state.conversation || {
  access: null,
  sessions: [],
  active: null,
  activeId: "",
  loading: false,
  sending: false,
  uploading: false,
  confirming: false,
  solving: false,
  draft: "",
  error: "",
  loaded: false,
  railOpen: false,
  contextOpen: false,
  showAllMessages: false,
  valueOpen: false,
};

const CONVERSATION_PHASE_STEPS = [
  { id: "data", label: "补齐数据", detail: "作息、教师与课时" },
  { id: "requirements", label: "确认规则", detail: "需求、范围与例外" },
  { id: "model", label: "AI 整理规则", detail: "生成可确认草案" },
  { id: "solve", label: "工业级求解", detail: "校验与全局优化" },
];

const conversationLegacyRenderCurrentView = renderCurrentView;
renderCurrentView = function renderCurrentViewWithConversation() {
  if (state.view !== "conversation") {
    conversationLegacyRenderCurrentView();
    return;
  }
  const root = $("appContent");
  root.innerHTML = renderConversationWorkspace();
  requestAnimationFrame(() => {
    const thread = document.querySelector(".conversation-thread");
    if (thread) thread.scrollTop = thread.scrollHeight;
  });
};

function renderConversationWorkspace() {
  const workspace = state.conversation;
  if (!workspace.access && workspace.loading) {
    return `<section class="conversation-loading"><div class="conversation-loader"></div><strong>正在打开 AI 对话工作台</strong><span>读取会员权益与最近对话</span></section>`;
  }
  if (workspace.access && workspace.access.enabled === false) return renderConversationLocked();
  return `<section class="conversation-shell ${workspace.railOpen ? "history-open" : ""}">
    ${renderConversationFocusHeader()}
    <div class="conversation-focus-body">
      ${renderConversationRail()}
      <div class="conversation-main">
        ${workspace.active ? renderConversationActive() : renderConversationLauncher()}
      </div>
      ${workspace.active && workspace.contextOpen ? renderConversationContext() : ""}
    </div>
  </section>`;
}

function renderConversationFocusHeader() {
  const session = state.conversation.active;
  const limitationCount = asArray(session?.model?.limitations).length;
  const currentIndex = conversationPhaseIndex(session?.phase);
  return `<header class="conversation-focus-header">
    <div class="conversation-focus-brand">
      <button type="button" class="conversation-back-button" data-view-jump="overview">返回项目</button>
      <div><strong>课有序 <span>CourseOrder AI</span></strong><small>2026-2027 学年第一学期排课</small></div>
    </div>
    <ol class="conversation-focus-progress" aria-label="AI 排课进度">${CONVERSATION_PHASE_STEPS.map((step, index) => `<li class="${index < currentIndex ? "done" : index === currentIndex ? "active" : ""}"><b>${index < currentIndex ? "完成" : index + 1}</b><span>${escapeHtml(step.label)}</span></li>`).join("")}</ol>
    <div class="conversation-focus-actions">
      <button type="button" class="secondary" data-action="conversation-toggle-history" aria-expanded="${state.conversation.railOpen ? "true" : "false"}">会话记录</button>
      ${session ? `<button type="button" class="secondary conversation-summary-button" data-action="conversation-toggle-context" aria-expanded="${state.conversation.contextOpen ? "true" : "false"}">规则摘要${limitationCount ? `<span>${limitationCount} 项局限</span>` : ""}</button>` : ""}
      <small>已自动保存</small>
    </div>
  </header>`;
}

function renderConversationLocked() {
  const access = state.conversation.access || {};
  return `<section class="conversation-locked">
    <div class="conversation-premium-kicker"><span>ADVANCED</span> 高级会员功能</div>
    <h2>把完整排课工作交给一个持续追问的 AI</h2>
    <p>${escapeHtml(access.message || "AI 对话排课需要开通高级会员")}</p>
    <div class="conversation-locked-grid">${asArray(access.capabilities).map((item, index) => `<article><b>${index + 1}</b><span>${escapeHtml(item)}</span></article>`).join("")}</div>
    <div class="conversation-locked-actions"><button type="button" class="secondary" data-view-jump="overview">返回项目概览</button><span>请联系系统管理员开通当前学校的高级会员权益</span></div>
  </section>`;
}

function renderConversationRail() {
  const sessions = asArray(state.conversation.sessions);
  return `<aside class="conversation-rail ${state.conversation.railOpen ? "expanded" : ""}" aria-label="AI 排课对话列表">
    <div class="conversation-rail-compact">
      <button type="button" data-action="conversation-toggle-history" aria-label="展开或收起会话记录" aria-expanded="${state.conversation.railOpen ? "true" : "false"}"><b>会话</b><span>${sessions.length}</span></button>
      <button type="button" data-action="conversation-new" aria-label="新建排课对话"><b>新建</b><span>+</span></button>
    </div>
    <div class="conversation-rail-content" aria-hidden="${state.conversation.railOpen ? "false" : "true"}">
      <div class="conversation-rail-head">
        <div><span>高级会员</span><strong>对话记录</strong></div>
        <button type="button" class="conversation-rail-close" data-action="conversation-toggle-history">收起</button>
      </div>
      <button type="button" class="conversation-new-button" data-action="conversation-new">新建排课对话</button>
      <div class="conversation-session-label">最近对话</div>
      <div class="conversation-session-list">${sessions.length ? sessions.map(renderConversationSessionItem).join("") : `<div class="conversation-session-empty">还没有历史对话</div>`}</div>
      <div class="conversation-rail-note"><strong>数据边界</strong><span>只向 AI 发送脱敏摘要和对话内容，不发送原始工作簿。</span></div>
    </div>
  </aside>`;
}

function renderConversationSessionItem(item) {
  const active = item.id === state.conversation.active?.id;
  return `<button type="button" class="conversation-session-item ${active ? "active" : ""}" data-action="conversation-open" data-session-id="${escapeAttr(item.id)}">
    <strong>${escapeHtml(item.title || "AI 对话排课")}</strong>
    <span><i class="conversation-phase-dot ${escapeAttr(conversationPhaseTone(item.phase))}"></i>${escapeHtml(item.phase_label || "进行中")}</span>
    <time>${escapeHtml(conversationTime(item.updated_at))}</time>
  </button>`;
}

function renderConversationLauncher() {
  return `<div class="conversation-launcher">
    <div class="conversation-launcher-copy">
      <span class="conversation-launcher-kicker">从一句需求开始</span>
      <h2>你提供学校情况，AI 负责把问题问清楚</h2>
      <p>选择一个起点即可。AI 会检查数据、追问关键歧义，形成可确认的规则草案，再交给工业级求解引擎。</p>
    </div>
    <div class="conversation-entry-grid">
      <button type="button" class="conversation-entry-card primary" data-action="conversation-create" data-entry-mode="direct" data-source-mode="current_project">
        <span class="conversation-entry-index">01</span><span class="conversation-entry-tag">推荐</span>
        <strong>沿用当前项目，直接开始</strong><p>读取已设置的作息、教师定位、课时与规则，然后只向你追问缺失信息。</p><em>开始 AI 排课</em>
      </button>
      <button type="button" class="conversation-entry-card" data-action="conversation-create" data-entry-mode="direct" data-source-mode="upload_base">
        <span class="conversation-entry-index">02</span>
        <strong>上传基础数据</strong><p>从教师定位表或基础数据包开始。</p><em>选择文件</em>
      </button>
      <button type="button" class="conversation-entry-card" data-action="conversation-create" data-entry-mode="direct" data-source-mode="existing_timetable">
        <span class="conversation-entry-index">03</span><span class="conversation-entry-tag quiet">可调优</span>
        <strong>上传已有课表</strong><p>说明哪些安排要保留、哪些要调整。</p><em>从课表开始</em>
      </button>
    </div>
    <button type="button" class="conversation-launcher-boundary" data-action="conversation-toggle-value"><strong>本地 skill 编排，AI 可选增强</strong><span>按需查看能力边界</span></button>
    ${state.conversation.valueOpen ? renderConversationValuePanel() : ""}
  </div>`;
}

function renderConversationValuePanel() {
  return `<aside class="conversation-value-panel">
    <span class="conversation-panel-kicker">同一会话内核</span>
    <h3>既能从零开始，也能接住原流程的调优任务</h3>
    <div class="conversation-value-flow">
      <article><b>A</b><div><strong>直接开始</strong><span>数据 → 追问 → 规则确认 → 排课</span></div></article>
      <article><b>B</b><div><strong>原流程调优</strong><span>当前候选 → 诊断 → 新规则 → 再求解</span></div></article>
    </div>
    <div class="conversation-value-proof"><span>规则可编辑</span><span>阻断审查</span><span>版本留痕</span><span>续排加速</span></div>
  </aside>`;
}

function renderConversationActive() {
  const session = state.conversation.active || {};
  const messages = asArray(session.messages);
  const visibleMessages = state.conversation.showAllMessages ? messages : messages.slice(-6);
  const hiddenMessageCount = Math.max(0, messages.length - visibleMessages.length);
  const purpose = session.source_mode === "existing_timetable" ? "existing_timetable" : "base_data";
  return `<div class="conversation-active">
    <header class="conversation-active-head">
      <div><span>${session.entry_mode === "optimization" ? "从方案审查进入" : "独立对话任务"}</span><h2>${escapeHtml(session.title || "AI 对话排课")}</h2></div>
      <div class="conversation-active-badges"><span class="conversation-mode-badge">${escapeHtml(conversationSourceLabel(session.source_mode))}</span><span class="conversation-status-badge ${escapeAttr(conversationPhaseTone(session.phase))}">${escapeHtml(session.phase_label || "进行中")}</span></div>
    </header>
    <div class="conversation-thread" aria-live="polite">
      ${hiddenMessageCount ? `<button type="button" class="conversation-older-messages" data-action="conversation-toggle-messages">展开前 ${hiddenMessageCount} 条对话</button>` : state.conversation.showAllMessages && messages.length > 6 ? `<button type="button" class="conversation-older-messages" data-action="conversation-toggle-messages">收起较早对话</button>` : ""}
      ${visibleMessages.map(renderConversationMessage).join("")}
      ${state.conversation.sending ? renderConversationThinking("排课助手正在盘点当前会话数据、追问缺项并整理规则") : ""}
      ${state.conversation.confirming ? renderConversationThinking("正在把确认内容整理为正式规则") : ""}
      ${state.conversation.uploading ? renderConversationThinking("正在读取工作簿结构并检查可转换课位") : ""}
    </div>
    ${renderConversationQuickReplies(session)}
    ${renderConversationInlineAction(session)}
    <footer class="conversation-composer">
      <input id="conversationFileInput" type="file" accept=".xlsx,.csv" data-conversation-upload data-purpose="${escapeAttr(purpose)}" hidden>
      <button type="button" class="conversation-attach" data-action="conversation-upload-trigger" title="上传基础数据或已有课表" ${conversationBusy() ? "disabled" : ""}>上传数据</button>
      <textarea id="conversationInput" rows="2" placeholder="描述需求、回答问题，或补充例外情况…" ${conversationBusy() ? "disabled" : ""}>${escapeHtml(state.conversation.draft || "")}</textarea>
      <button type="button" class="conversation-send" data-action="conversation-send" ${conversationBusy() ? "disabled" : ""}>发送</button>
      <div class="conversation-composer-note"><span>Ctrl / ⌘ + Enter 发送</span><span>确认前不会写入正式规则</span></div>
    </footer>
  </div>`;
}

function renderConversationInlineAction(session) {
  if (!["model_ready", "ready_to_solve", "solving", "completed"].includes(String(session.phase || ""))) return "";
  return `<div class="conversation-primary-inline">${renderConversationPrimaryAction(session)}</div>`;
}

function renderConversationMessage(message) {
  const assistant = message.role === "assistant";
  const payload = message.payload || {};
  const questions = asArray(payload.questions).filter((item) => item && item.question);
  return `<article class="conversation-message ${assistant ? "assistant" : "user"}">
    <div class="conversation-message-author">${assistant ? "课有序排课助手" : "你"}<span>${escapeHtml(conversationMessageKind(message.kind))}</span></div>
    <div class="conversation-message-body">${escapeHtml(message.content || "").replace(/\n/g, "<br>")}</div>
    ${questions.length ? `<div class="conversation-message-questions"><strong>需要你确认</strong>${questions.slice(0, 3).map((item) => `<div class="conversation-question"><span>${escapeHtml(item.question)}</span>${item.why ? `<small>${escapeHtml(item.why)}</small>` : ""}</div>`).join("")}</div>` : ""}
    ${asArray(payload.limitations).length ? `<div class="conversation-inline-limitations">${asArray(payload.limitations).slice(0, 3).map((item) => `<span>${escapeHtml(item.title || item)}</span>`).join("")}</div>` : ""}
  </article>`;
}

function renderConversationThinking(label) {
  return `<article class="conversation-message assistant thinking"><div class="conversation-message-author">课有序排课助手<span>处理中</span></div><div class="conversation-thinking-row"><i></i><i></i><i></i><span>${escapeHtml(label)}</span></div></article>`;
}

function renderConversationQuickReplies(session) {
  const questions = asArray(session.model?.questions);
  if (!questions.length || conversationBusy()) return "";
  const options = questions.flatMap((question) => asArray(question.options).map((option) => ({ question: question.question, option }))).slice(0, 3);
  if (!options.length) return "";
  return `<div class="conversation-quick-replies">${options.map((item) => `<button type="button" data-action="conversation-quick-answer" data-answer="${escapeAttr(`${item.question}：${item.option}`)}">${escapeHtml(item.option)}</button>`).join("")}</div>`;
}

function renderConversationContext() {
  const session = state.conversation.active || {};
  const model = session.model || {};
  const checklist = asArray(model.checklist);
  return `<div class="conversation-context-layer"><button type="button" class="conversation-context-backdrop" data-action="conversation-toggle-context" aria-label="关闭规则摘要"></button><aside class="conversation-context" aria-label="排课规则摘要">
    <header class="conversation-context-head"><div><span>排课规则摘要</span><strong>规则、缺失信息与现有局限</strong></div><button type="button" data-action="conversation-toggle-context">关闭</button></header>
    <div class="conversation-context-scroll">
      ${renderConversationProgress(session.phase)}
      <section class="conversation-context-section">
        <div class="conversation-context-title"><span>当前上下文</span><strong>${checklist.filter((item) => item.status === "ready").length}/${checklist.length || 0}</strong></div>
        <div class="conversation-checklist">${checklist.map((item) => `<div class="conversation-check ${escapeAttr(item.status || "pending")}"><i></i><div><strong>${escapeHtml(item.label)}</strong><span>${escapeHtml(item.detail || "")}</span></div></div>`).join("") || `<p class="conversation-context-empty">AI 正在建立数据清单</p>`}</div>
      </section>
      ${renderConversationFiles(session)}
      ${renderConversationModel(model)}
    </div>
    ${renderConversationPrimaryAction(session)}
  </aside></div>`;
}

function renderConversationProgress(phase) {
  const index = conversationPhaseIndex(phase);
  return `<section class="conversation-progress"><span class="conversation-panel-kicker">工作进度</span>${CONVERSATION_PHASE_STEPS.map((step, stepIndex) => `<div class="conversation-progress-step ${stepIndex < index ? "done" : stepIndex === index ? "active" : ""}"><b>${stepIndex < index ? "✓" : stepIndex + 1}</b><div><strong>${escapeHtml(step.label)}</strong><span>${escapeHtml(step.detail)}</span></div></div>`).join("")}</section>`;
}

function renderConversationFiles(session) {
  const files = asArray(session.files);
  if (!files.length) return "";
  return `<section class="conversation-context-section"><div class="conversation-context-title"><span>已读取文件</span><strong>${files.length}</strong></div><div class="conversation-file-list">${files.map((file) => `<article><div><strong>${escapeHtml(file.name)}</strong><span>${escapeHtml(file.summary?.classification_label || "数据文件")} · ${conversationFileSize(file.size_bytes)}</span></div><b>${file.summary?.warm_start_capable ? `${formatNumber(file.summary.warm_start_records)} 课位` : "已读取"}</b></article>`).join("")}</div></section>`;
}

function renderConversationModel(model) {
  const requirements = asArray(model.requirements);
  const limitations = asArray(model.limitations);
  if (!requirements.length && !limitations.length && !model.ai?.used && !model.modeling?.engine) return "";
  return `<section class="conversation-context-section conversation-model-card">
    <div class="conversation-context-title"><span>规则摘要</span><strong>${model.ai?.used ? "模型增强" : model.modeling?.engine === "local_skill" ? "本地受限引导" : "待整理"}</strong></div>
    ${requirements.length ? `<div class="conversation-requirements">${requirements.slice(0, 6).map((item) => `<article><span class="${escapeAttr(item.strength || "soft")}">${conversationStrengthLabel(item.strength)}</span><div><strong>${escapeHtml(item.statement || "排课要求")}</strong><small>${escapeHtml(item.scope || "全校")} · ${escapeHtml(item.effective_time || "当前学期")}</small></div></article>`).join("")}</div>` : ""}
    ${model.default_constraints_only && model.default_constraint_source ? `<div class="conversation-limitations"><strong>${escapeHtml(model.default_constraint_source.label || "默认约束")}</strong><article><span>已保留</span><small>${escapeHtml(model.default_constraint_source.note || "")}</small></article></div>` : ""}
    ${asArray(model.unparsed_inputs || model.requirement_ledger).filter((item) => item && !["withdrawn", "replaced", "supported"].includes(item.status)).length ? `<div class="conversation-limitations"><strong>未解析输入（已保留）</strong>${asArray(model.unparsed_inputs || model.requirement_ledger).filter((item) => item && !["withdrawn", "replaced", "supported"].includes(item.status)).slice(0, 6).map((item) => `<article><span>${escapeHtml(item.id || "待确认")}</span><small>${escapeHtml(item.statement || "")}</small><em>需要澄清，未进入正式规则</em></article>`).join("")}</div>` : ""}
    ${limitations.length ? `<div class="conversation-limitations"><strong>现有局限</strong>${limitations.slice(0, 5).map((item) => `<article><span>${escapeHtml(item.title || "尚有限制")}</span><small>${escapeHtml(item.impact || "")}</small><em>${escapeHtml(item.resolution || "")}</em></article>`).join("")}</div>` : ""}
  </section>`;
}

function renderConversationPrimaryAction(session) {
  const phase = String(session.phase || "");
  if (phase === "model_ready") {
    return `<div class="conversation-context-action"><span>排课助手已问清关键信息</span><strong>确认后写入正式规则</strong><button type="button" data-action="conversation-confirm" ${conversationBusy() ? "disabled" : ""}>我确认规则方案</button><small>仅当前用户确认，不需要第三方审批</small></div>`;
  }
  if (phase === "ready_to_solve") {
    return `<div class="conversation-context-action ready"><span>求解前检查已通过</span><strong>启动工业级全局求解</strong><button type="button" data-action="conversation-solve" ${conversationBusy() ? "disabled" : ""}>开始排课</button><small>任务会在后台运行，可随时查看状态</small></div>`;
  }
  if (phase === "solving") {
    return `<div class="conversation-context-action running"><span>任务正在后台运行</span><strong>工业级求解中</strong><button type="button" class="secondary" data-action="conversation-open-solve">查看求解状态</button><small>关闭当前页面不会中断任务</small></div>`;
  }
  if (phase === "completed") {
    return `<div class="conversation-context-action ready"><span>候选课表已生成</span><strong>继续对话或进入发布</strong><button type="button" data-view-jump="results">查看课表结果</button><small>也可以新建调优对话继续改善</small></div>`;
  }
  return `<div class="conversation-context-action muted"><span>当前阶段</span><strong>${escapeHtml(session.phase_label || "继续补充信息")}</strong><small>回答左侧 AI 的问题，信息足够后才会出现确认按钮</small></div>`;
}

async function loadConversationWorkspace({ keepActive = true } = {}) {
  if (state.conversation.loading) return;
  state.conversation.loading = true;
  state.conversation.error = "";
  if (state.view === "conversation") renderShell();
  try {
    const access = await api("/api/conversation-scheduler/access");
    state.conversation.access = access;
    if (!access.enabled) {
      state.conversation.sessions = [];
      state.conversation.active = null;
      return;
    }
    const list = await api("/api/conversation-scheduler/sessions?limit=40");
    state.conversation.sessions = asArray(list.sessions);
    if (keepActive && state.conversation.activeId) {
      state.conversation.active = await api(`/api/conversation-scheduler/sessions/${encodeURIComponent(state.conversation.activeId)}`).catch(() => null);
    }
    state.conversation.loaded = true;
  } catch (error) {
    state.conversation.error = error.message;
    toast(error.message);
  } finally {
    state.conversation.loading = false;
    if (state.view === "conversation") renderShell();
  }
}

async function createConversation(entryMode, sourceMode) {
  state.conversation.loading = true;
  renderShell();
  try {
    const session = await api("/api/conversation-scheduler/sessions", {
      method: "POST",
      body: { entry_mode: entryMode, source_mode: sourceMode },
    });
    state.conversation.active = session;
    state.conversation.activeId = session.id;
    state.conversation.draft = "";
    await refreshConversationSessions();
    renderShell();
    if (["upload_base", "existing_timetable"].includes(sourceMode)) {
      requestAnimationFrame(() => $("conversationFileInput")?.click());
    }
  } finally {
    state.conversation.loading = false;
    renderShell();
  }
}

async function openConversation(sessionId) {
  state.conversation.loading = true;
  state.conversation.activeId = sessionId;
  renderShell();
  try {
    state.conversation.active = await api(`/api/conversation-scheduler/sessions/${encodeURIComponent(sessionId)}`);
    state.conversation.draft = "";
  } finally {
    state.conversation.loading = false;
    renderShell();
  }
}

async function refreshConversationSessions() {
  const list = await api("/api/conversation-scheduler/sessions?limit=40");
  state.conversation.sessions = asArray(list.sessions);
}

async function sendConversationMessage(prefilled = "") {
  const session = state.conversation.active;
  if (!session || state.conversation.sending) return;
  const content = String(prefilled || $("conversationInput")?.value || state.conversation.draft || "").trim();
  if (!content) {
    toast("请先输入排课需求或回答 AI 的问题");
    return;
  }
  state.conversation.draft = "";
  state.conversation.sending = true;
  session.messages = [...asArray(session.messages), { role: "user", kind: "text", content, created_at: new Date().toISOString() }];
  renderShell();
  try {
    state.conversation.active = await api(`/api/conversation-scheduler/sessions/${encodeURIComponent(session.id)}/messages`, {
      method: "POST",
      body: { content },
    });
    await refreshConversationSessions();
  } finally {
    state.conversation.sending = false;
    renderShell();
  }
}

async function uploadConversationFile(input) {
  const file = input.files?.[0];
  const session = state.conversation.active;
  if (!file || !session) return;
  const form = new FormData();
  form.append("file", file);
  form.append("purpose", input.dataset.purpose || "base_data");
  state.conversation.uploading = true;
  renderShell();
  try {
    state.conversation.active = await upload(`/api/conversation-scheduler/sessions/${encodeURIComponent(session.id)}/files`, form);
    await refreshConversationSessions();
    toast("文件已读取，排课助手会继续检查缺失信息");
  } finally {
    state.conversation.uploading = false;
    input.value = "";
    renderShell();
  }
}

async function confirmConversationModel() {
  const session = state.conversation.active;
  if (!session || state.conversation.confirming) return;
  state.conversation.confirming = true;
  renderShell();
  try {
    state.conversation.active = await api(`/api/conversation-scheduler/sessions/${encodeURIComponent(session.id)}/confirm-model`, {
      method: "POST",
      body: { confirm: true },
    });
    await Promise.all([refreshConversationSessions(), loadAll({ silent: true })]);
    toast(state.conversation.active.phase === "ready_to_solve" ? "规则方案已确认，可以开始排课" : "规则已确认，但仍有阻断项需要处理");
  } finally {
    state.conversation.confirming = false;
    renderShell();
  }
}

async function startConversationSolve() {
  const session = state.conversation.active;
  if (!session || state.conversation.solving) return;
  state.conversation.solving = true;
  renderShell();
  try {
    const response = await api(`/api/conversation-scheduler/sessions/${encodeURIComponent(session.id)}/solve`, {
      method: "POST",
      body: { mode: session.model?.solve_mode || "joint", time_limit_seconds: 1800 },
    });
    state.conversation.active = response.session;
    await Promise.all([refreshConversationSessions(), refreshSolveStatus(true)]);
    toast("工业级求解任务已进入队列");
  } finally {
    state.conversation.solving = false;
    renderShell();
  }
}

const conversationLegacyHandleAction = handleAction;
handleAction = async function handleActionWithConversation(action, target) {
  if (action === "conversation-new") {
    state.conversation.active = null;
    state.conversation.activeId = "";
    state.conversation.draft = "";
    state.conversation.contextOpen = false;
    state.conversation.showAllMessages = false;
    renderShell();
    return;
  }
  if (action === "conversation-toggle-history") {
    state.conversation.railOpen = !state.conversation.railOpen;
    renderShell();
    return;
  }
  if (action === "conversation-toggle-context") {
    state.conversation.contextOpen = !state.conversation.contextOpen;
    renderShell();
    return;
  }
  if (action === "conversation-toggle-messages") {
    state.conversation.showAllMessages = !state.conversation.showAllMessages;
    renderShell();
    return;
  }
  if (action === "conversation-toggle-value") {
    state.conversation.valueOpen = !state.conversation.valueOpen;
    renderShell();
    return;
  }
  if (action === "conversation-create") {
    await createConversation(target.dataset.entryMode || "direct", target.dataset.sourceMode || "current_project");
    return;
  }
  if (action === "conversation-open") {
    await openConversation(target.dataset.sessionId || "");
    state.conversation.railOpen = false;
    state.conversation.contextOpen = false;
    state.conversation.showAllMessages = false;
    renderShell();
    return;
  }
  if (action === "conversation-send") {
    await sendConversationMessage();
    return;
  }
  if (action === "conversation-quick-answer") {
    await sendConversationMessage(target.dataset.answer || "");
    return;
  }
  if (action === "conversation-upload-trigger") {
    $("conversationFileInput")?.click();
    return;
  }
  if (action === "conversation-confirm") {
    await confirmConversationModel();
    return;
  }
  if (action === "conversation-solve") {
    await startConversationSolve();
    return;
  }
  if (action === "conversation-open-solve") {
    state.view = "solve";
    state.formalSolveSection = "workspace";
    renderShell();
    return;
  }
  if (action === "open-conversation-optimization") {
    state.view = "conversation";
    renderShell();
    if (!state.conversation.loaded) await loadConversationWorkspace({ keepActive: false });
    if (state.conversation.access?.enabled === false) return;
    await createConversation("optimization", "current_result");
    return;
  }
  return conversationLegacyHandleAction(action, target);
};

document.addEventListener("click", (event) => {
  const route = event.target.closest("[data-view='conversation'], [data-view-jump='conversation']");
  if (!route) return;
  queueMicrotask(() => {
    if (state.view === "conversation" && !state.conversation.loaded) {
      loadConversationWorkspace({ keepActive: true }).catch((error) => toast(error.message));
    }
  });
});

document.addEventListener("input", (event) => {
  if (event.target.id === "conversationInput") state.conversation.draft = event.target.value;
});

document.addEventListener("keydown", (event) => {
  if (event.target.id !== "conversationInput") return;
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
    event.preventDefault();
    sendConversationMessage().catch((error) => toast(error.message));
  }
});

document.addEventListener("change", (event) => {
  if (!event.target.matches("[data-conversation-upload]")) return;
  uploadConversationFile(event.target).catch((error) => {
    state.conversation.uploading = false;
    renderShell();
    toast(error.message);
  });
});

function conversationBusy() {
  return Boolean(state.conversation.sending || state.conversation.uploading || state.conversation.confirming || state.conversation.solving);
}

function conversationPhaseIndex(phase) {
  const value = String(phase || "");
  if (["intake", "data_needed"].includes(value)) return 0;
  if (value === "clarifying") return 1;
  if (["model_ready", "blocked", "awaiting_confirmation"].includes(value)) return 2;
  if (value === "ready_to_solve") return 3;
  if (["solving", "completed", "failed"].includes(value)) return 3;
  return 0;
}

function conversationPhaseTone(phase) {
  const value = String(phase || "");
  if (["completed", "ready_to_solve", "model_ready"].includes(value)) return "ok";
  if (["blocked", "failed"].includes(value)) return "error";
  if (["solving", "clarifying"].includes(value)) return "warning";
  return "info";
}

function conversationSourceLabel(source) {
  return ({
    current_project: "当前项目",
    upload_base: "基础数据",
    existing_timetable: "已有课表",
    current_result: "当前候选调优",
  })[String(source || "")] || "对话排课";
}

function conversationMessageKind(kind) {
  return ({
    intake: "开始",
    clarification: "追问",
    model_review: "规则整理",
    file_review: "文件检查",
    confirmation: "已确认",
    blocker: "阻断审查",
    solve_started: "求解",
  })[String(kind || "")] || "";
}

function conversationStrengthLabel(strength) {
  return ({ hard: "硬规则", soft: "软规则", advisory: "建议" })[String(strength || "")] || "规则";
}

function conversationFileSize(bytes) {
  const value = Number(bytes || 0);
  if (value >= 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  if (value >= 1024) return `${Math.round(value / 1024)} KB`;
  return `${value} B`;
}

function conversationTime(value) {
  const date = new Date(value || "");
  if (Number.isNaN(date.getTime())) return "";
  const today = new Date();
  if (date.toDateString() === today.toDateString()) return date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
  return date.toLocaleDateString("zh-CN", { month: "2-digit", day: "2-digit" });
}

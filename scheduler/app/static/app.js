const state = {
  view: "overview",
  accessRole: loadStored("scheduler.accessRole", "academic_admin"),
  solveMode: "course",
  ruleMode: "all",
  ruleSearch: "",
  ruleLimit: 8,
  fileLimit: 12,
  selectedDayRule: "time_grid",
  selectedAcademicTable: "substitutions",
  resultPreviewKind: "class",
  resultPreviewItem: "",
  config: null,
  teachers: [],
  dayRules: {},
  academic: null,
  readiness: null,
  solveStatus: null,
  resultPreview: null,
  profileCatalog: null,
  schoolProblemPreview: null,
  accessContext: null,
  conflicts: null,
  audit: null,
  authSession: null,
  solveJobs: { jobs: [], count: 0 },
  modelUsage: null,
  aiProviderProbe: null,
  rulesV2: null,
  projectState: null,
  foundationStep: "calendar",
  formalRuleTab: "all",
  formalRuleFilter: "all",
  formalRuleSearch: "",
  formalRuleSection: "assistant",
  formalRulePage: 1,
  formalRulePageSize: 9,
  visualRuleSubject: "",
  visualRuleAction: "ban",
  visualRuleStrength: "hard",
  visualRuleSelectedCells: [],
  visualRuleClass: "",
  formalRuleDomain: "course",
  formalRuleCategory: "basic",
  formalSolveSection: "workspace",
  aiBlockReview: null,
  aiBlockReviewLoading: false,
  parsedRuleV2: null,
  optimizationRuleV2: null,
  formalRuleParsingTarget: "",
  formalRuleInput: "",
  formalOptimizationInput: "",
  parsedRule: null,
  leaveRepairPreview: null,
  manualAdjustmentPreview: null,
  loading: false,
  loginPending: false,
  pollTimer: null,
  solveClockTimer: null,
};

const VIEW_META = {
  overview: ["本次排课", "排课首页", "按步骤准备数据、确认规则、开始排课并查看结果。"],
  data: ["第 1 步", "准备数据", "导入教师、班级和课程信息；需要手工修改时再展开表格。"],
  rules: ["第 2 步", "设置规则", "用教务语言确认必须满足的要求和尽量满足的偏好。"],
  solve: ["第 3 步", "开始排课", "选择排课范围和优化时间，启动后可以关闭页面去做其他工作。"],
  results: ["第 4 步", "查看结果", "先预览课表和风险，确认无误后再下载交付文件。"],
  jobs: ["更多工具", "排课记录", "查看每次排课的时间、状态和结果，运行中的任务也可在这里取消。"],
  advanced: ["更多工具", "问题处理", "集中处理规则冲突、教师请假、临时调课和其他异常。"],
};

const VIEW_BODY_CLASSES = {
  overview: "home-page page-home",
  data: "screen-page page-data",
  rules: "screen-page page-rule",
  solve: "screen-page page-solver",
  jobs: "screen-page page-jobs",
  results: "screen-page page-release",
  advanced: "screen-page page-diagnostics",
};

const DAY_RULE_LABELS = {
  time_grid: "时间格子",
  days: "上课日",
  fixed_slots: "固定课位",
  subject_hours: "学科课时",
  subject_bans: "学科禁排",
  class_overrides: "班级差异",
};

const ACADEMIC_LABELS = {
  substitutions: "调代课",
  timetable_changes: "调课变更",
  exam_duties: "考务安排",
  after_school: "课后服务",
  rooms: "场地资源",
  activities: "活动占用",
  teacher_absences: "教师请假",
};

const SEVERITY_RANK = { error: 3, warning: 2, info: 1, ok: 0 };
const ACTION_PERMISSIONS = {
  "save-data-primary": "base_data.write",
  "add-teacher-row": "base_data.write",
  "add-day-row": "base_data.write",
  "save-teachers": "base_data.write",
  "save-day-rules": "base_data.write",
  "add-academic-row": "academic.write",
  "save-academic": "academic.write",
  "set-rule-mode": null,
  "edit-rule": "rules.write",
  "save-rule-fields": "rules.write",
  "add-nl-rule": "rules.write",
  "remove-nl-rule": "rules.write",
  "start-solve": "solve.run",
  "continue-solve": "solve.run",
  "cancel-job": "solve.run",
  "pause-solve": "solve.run",
  "stop-solve": "solve.run",
  "apply-leave-repair": "schedule.adjust",
  "apply-manual-adjustment": "schedule.adjust",
  "save-ai-settings": "rules.write",
  "test-ai-connection": "rules.write",
  "save-model-quota": "billing.manage",
};
const $ = (id) => document.getElementById(id);

function loadStored(key, fallback) {
  try {
    return localStorage.getItem(key) || fallback;
  } catch {
    return fallback;
  }
}

function saveStored(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch {
  }
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[ch]);
}

function escapeAttr(value) {
  return escapeHtml(value).replace(/`/g, "&#96;");
}

function formatNumber(value, fallback = "0") {
  const number = Number(value);
  return Number.isFinite(number) ? number.toLocaleString("zh-CN") : fallback;
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function asArray(value) {
  return Array.isArray(value) ? value : [];
}

function asObject(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

function isRunningStatus(status = state.solveStatus) {
  return ["queued", "starting", "running", "pause_requested", "cancel_requested"].includes(String(status?.status || ""));
}

function solveStatusLabel(status) {
  const labels = {
    FEASIBLE: "可行解",
    OPTIMAL: "已证明最优",
    idle: "暂无任务",
    starting: "启动中",
    queued: "排队中",
    running: "进行中",
    pause_requested: "暂停请求中",
    cancel_requested: "取消请求中",
    cancelled: "已取消",
    completed: "已完成",
    stopped: "已停止",
    failed: "失败",
    unknown: "未知",
  };
  return labels[String(status || "idle")] || String(status || "未知");
}

function solverStatusLabel(status) {
  return solveStatusLabel(status);
}

function severityTone(severity) {
  if (["error", "blocked", "failed", "cancelled"].includes(severity)) return "error";
  if (["warning", "review", "queued", "running", "cancel_requested", "pause_requested"].includes(severity)) return "warning";
  if (severity === "ok" || severity === "ready" || severity === "completed") return "ok";
  return "info";
}

function toast(message) {
  const node = $("toast");
  if (!node) return;
  node.textContent = String(message || "");
  node.classList.add("show");
  clearTimeout(node._timer);
  node._timer = setTimeout(() => node.classList.remove("show"), 2800);
}

async function api(path, options = {}) {
  const method = String(options.method || "GET").toUpperCase();
  const headers = {
    ...accessHeaders(),
    ...(options.headers || {}),
  };
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
    const csrfToken = readCookie("scheduler_csrf");
    if (csrfToken) headers["X-CSRF-Token"] = csrfToken;
  }
  let body = options.body;
  if (body && !(body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
    if (typeof body !== "string") body = JSON.stringify(body);
  }
  const res = await fetch(path, { ...options, method, headers, body, credentials: "same-origin" });
  const text = await res.text();
  let data = {};
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { raw: text };
    }
  }
  if (!res.ok) {
    const error = new Error(data.error || res.statusText);
    error.status = res.status;
    error.payload = data;
    if (res.status === 401 && path !== "/api/auth/login" && path !== "/api/auth/session") {
      state.authSession = { auth_mode: "required", authenticated: false };
      state.loading = false;
      renderAuthState();
    }
    throw error;
  }
  return data;
}

async function upload(path, formData) {
  return api(path, { method: "POST", body: formData, headers: accessHeaders() });
}

function accessHeaders() {
  if (authIsRequired()) return {};
  return { "X-Scheduler-Role": state.accessRole || "academic_admin" };
}

function readCookie(name) {
  const prefix = `${encodeURIComponent(name)}=`;
  const item = String(document.cookie || "").split("; ").find((part) => part.startsWith(prefix));
  return item ? decodeURIComponent(item.slice(prefix.length)) : "";
}

function authIsRequired() {
  return state.authSession?.auth_mode === "required";
}

function isAuthenticated() {
  return !authIsRequired() || Boolean(state.authSession?.authenticated);
}

function currentRoleKey() {
  return authIsRequired() ? String(state.authSession?.user?.role || "viewer") : String(state.accessRole || "academic_admin");
}

function isAdminRole() {
  return currentRoleKey() === "academic_admin";
}

async function loadAll({ silent = false } = {}) {
  state.loading = true;
  if (!silent) renderShell();
  const mode = state.solveMode || "joint";
  const calls = {
    accessContext: api("/api/access/context"),
    config: api("/api/config"),
    teachers: api("/api/teacher-subjects"),
    dayRules: api("/api/day-rules"),
    academic: api("/api/academic-affairs"),
    readiness: api(`/api/readiness?mode=${encodeURIComponent(mode)}`),
    profileCatalog: api(`/api/profiles/catalog?mode=${encodeURIComponent(mode)}`),
    schoolProblemPreview: api(`/api/school-problem/preview?mode=${encodeURIComponent(mode)}`),
    solveStatus: api("/api/solve/status"),
    resultPreview: api("/api/results/preview"),
    solveJobs: api("/api/solve/jobs?limit=30").catch(() => ({ jobs: [], count: 0 })),
    rulesV2: api("/api/rules/v2").catch(() => ({ rules: [], summary: {}, revision: 0 })),
    projectState: api("/api/project/state").catch(() => null),
  };
  const results = await Promise.allSettled(Object.entries(calls).map(async ([key, promise]) => [key, await promise]));
  const errors = [];
  for (const result of results) {
    if (result.status === "fulfilled") {
      const [key, value] = result.value;
      if (key === "teachers") state.teachers = asArray(value.rows);
      else state[key] = value;
    } else {
      errors.push(result.reason?.message || String(result.reason));
    }
  }
  const importedHours = asArray(state.dayRules?.subject_hours);
  const configuredMode = importedHours.some((row) => Object.hasOwn(row, "周期课时")) ? "course" : importedHours.length ? "joint" : state.solveMode;
  if (configuredMode !== state.solveMode) {
    state.solveMode = configuredMode;
    state.readiness = await api(`/api/readiness?mode=${encodeURIComponent(configuredMode)}`).catch(() => state.readiness);
  }
  state.loading = false;
  $("lastUpdated").textContent = `同步于 ${new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}`;
  updatePolling();
  renderShell();
  if (errors.length && !silent) toast(errors[0]);
}

function updatePolling() {
  clearInterval(state.pollTimer);
  clearInterval(state.solveClockTimer);
  state.pollTimer = null;
  state.solveClockTimer = null;
  if (isRunningStatus()) {
    state.pollTimer = setInterval(() => refreshSolveStatus(true), 3000);
    state.solveClockTimer = setInterval(updateLiveSolveClocks, 1000);
  }
}

function updateLiveSolveClocks() {
  document.querySelectorAll("[data-solve-clock]").forEach((node) => {
    const base = Number(node.dataset.elapsedSeconds || 0);
    const renderedAt = Number(node.dataset.renderedAt || Date.now());
    const running = node.dataset.running === "true";
    const elapsed = base + (running ? Math.max(0, Math.floor((Date.now() - renderedAt) / 1000)) : 0);
    node.textContent = formatClock(elapsed);
  });
}

function solveClockMarkup(status = state.solveStatus, className = "") {
  const elapsed = Number(status?.elapsed_seconds || status?.result?.elapsed_seconds || 0);
  const running = isRunningStatus(status);
  return `<strong class="${escapeAttr(className)}" data-solve-clock data-elapsed-seconds="${elapsed}" data-rendered-at="${Date.now()}" data-running="${running}">${escapeHtml(formatClock(elapsed))}</strong>`;
}

async function refreshSolveStatus(silent = false) {
  state.solveStatus = await api("/api/solve/status");
  state.solveJobs = await api("/api/solve/jobs?limit=30").catch(() => state.solveJobs);
  state.resultPreview = await api("/api/results/preview").catch(() => state.resultPreview);
  state.readiness = await api(`/api/readiness?mode=${encodeURIComponent(state.solveMode || "joint")}`).catch(() => state.readiness);
  state.projectState = await api("/api/project/state").catch(() => state.projectState);
  updatePolling();
  renderShell();
  if (!silent) toast("求解状态已刷新");
}

function renderShell() {
  if (!renderAuthState()) return;
  const [eyebrow, title, subtitle] = VIEW_META[state.view] || VIEW_META.overview;
  syncEduOpsBodyClass();
  $("eyebrow").textContent = eyebrow;
  $("pageTitle").textContent = title;
  $("pageSubtitle").textContent = subtitle;
  document.querySelectorAll(".nav-item").forEach((node) => {
    node.classList.toggle("active", node.dataset.view === state.view);
    node.classList.toggle("is-active", node.dataset.view === state.view);
  });
  const navMore = $("navMore");
  if (navMore) navMore.open = ["jobs", "advanced"].includes(state.view);
  renderTopStatus();
  renderPageActions();
  renderCurrentView();
  applyAccessPermissions();
}

function renderAuthState() {
  const shell = $("appShell");
  const gate = $("authGate");
  if (!state.authSession) {
    if (shell) shell.hidden = true;
    if (gate) gate.hidden = true;
    return false;
  }
  const authenticated = isAuthenticated();
  if (shell) shell.hidden = !authenticated;
  if (gate) gate.hidden = authenticated;
  document.body.classList.toggle("auth-page", !authenticated);
  if (!authenticated) return false;

  const identity = state.authSession?.user || {};
  const roleSelect = $("accessRoleSelect");
  const roleBadge = $("authenticatedRole");
  const logoutButton = $("logoutBtn");
  if (roleSelect) roleSelect.hidden = authIsRequired();
  if (roleBadge) {
    roleBadge.hidden = !authIsRequired();
    roleBadge.textContent = state.accessContext?.role?.label || roleLabel(currentRoleKey());
  }
  if (logoutButton) logoutButton.hidden = !authIsRequired();
  if ($("sideUserName")) $("sideUserName").textContent = identity.display_name || state.accessContext?.role?.label || "教务用户";
  if ($("sideUserRole")) $("sideUserRole").textContent = authIsRequired()
    ? `${identity.organization_name || "当前学校"} · ${state.accessContext?.role?.label || roleLabel(identity.role)}`
    : "开发预览身份";
  document.querySelectorAll(".admin-only").forEach((node) => { node.hidden = !isAdminRole(); });
  if (!isAdminRole() && state.view === "usage") state.view = "overview";
  renderTaskSummary();
  return true;
}

function roleLabel(key) {
  return ({
    academic_admin: "教务管理员",
    scheduler_operator: "排课操作员",
    grade_lead: "年级组",
    dorm_supervisor: "宿管/值周",
    viewer: "只读查看",
  })[String(key || "")] || "当前身份";
}

function renderTaskSummary() {
  const jobs = asArray(state.solveJobs?.jobs);
  const active = jobs.filter((job) => ["queued", "running", "cancel_requested"].includes(String(job.status || ""))).length;
  if ($("sideTaskCount")) $("sideTaskCount").textContent = String(active || jobs.length || 0);
  if ($("sideTaskSummary")) $("sideTaskSummary").textContent = active ? `${active} 次排课进行中` : jobs.length ? `最近 ${jobs.length} 次排课` : "暂无排课记录";
}

function syncEduOpsBodyClass() {
  document.body.className = VIEW_BODY_CLASSES[state.view] || VIEW_BODY_CLASSES.overview;
  document.body.dataset.uiSource = "edu-ops-scheduler-console";
}

function applyAccessPermissions() {
  const roleLabel = state.accessContext?.role?.label || "当前角色";
  document.querySelectorAll("[data-action]").forEach((node) => {
    const permission = ACTION_PERMISSIONS[node.dataset.action];
    if (!permission || hasPermission(permission)) return;
    node.disabled = true;
    node.title = `${roleLabel}没有执行该操作的权限`;
  });
  document.querySelectorAll("[data-upload]").forEach((input) => {
    const permission = input.dataset.upload === "academic" ? "academic.write" : "base_data.write";
    if (hasPermission(permission)) return;
    input.disabled = true;
    const label = input.closest(".upload-button");
    if (label) {
      label.setAttribute("aria-disabled", "true");
      label.title = `${roleLabel}没有导入该表的权限`;
    }
  });
}

function hasPermission(permission) {
  if (!permission) return true;
  const permissions = asArray(state.accessContext?.permissions);
  return permissions.includes("*") || permissions.includes(permission);
}

function renderTopStatus() {
  const badge = $("globalRunBadge");
  const status = state.solveStatus || {};
  const readiness = state.readiness?.summary || {};
  const tone = isRunningStatus(status) ? "warning" : status.status === "completed" ? "ok" : readiness.can_start_solver ? "ok" : "warning";
  badge.className = `run-badge ${tone}`;
  badge.textContent = isRunningStatus(status)
    ? "正在排课"
    : status.status === "completed"
      ? "结果已生成"
      : readiness.can_start_solver
        ? "可以开始"
        : "有待办";
}

function renderPageActions() {
  const actions = $("pageActions");
  const byView = {
    overview: "",
    data: "",
    rules: `<button type="button" data-action="refresh-readiness">检查规则</button><button type="button" class="secondary" data-view-jump="solve">下一步</button>`,
    solve: "",
    jobs: `<button type="button" data-action="refresh-jobs">刷新记录</button>`,
    results: hasResultContext() ? `<button type="button" class="secondary" data-action="refresh-results">刷新结果</button>` : "",
    advanced: `<button type="button" data-action="run-conflicts">检查问题</button>`,
    usage: `<button type="button" data-action="refresh-model-usage">刷新用量</button>`,
  };
  actions.innerHTML = byView[state.view] || "";
}

function renderCurrentView() {
  const root = $("appContent");
  if (state.loading && !state.config) {
    root.innerHTML = `<div class="card pad empty-state">正在读取项目数据...</div>`;
    return;
  }
  const renderers = {
    overview: renderOverview,
    data: renderDataView,
    rules: renderRulesView,
    solve: renderSolveView,
    jobs: renderJobsView,
    results: renderResultsView,
    advanced: renderAdvancedView,
    usage: renderUsageView,
  };
  root.innerHTML = (renderers[state.view] || renderOverview)();
}

function renderOverview() {
  const next = overviewNextAction();
  return `
    <section class="home-focus ${next.tone}">
      <div class="home-focus-main">
        <span class="home-state">${escapeHtml(next.stateLabel)}</span>
        <h2>${escapeHtml(next.title)}</h2>
        <p>${escapeHtml(next.message)}</p>
        <button type="button" data-view-jump="${escapeAttr(next.view)}">${escapeHtml(next.actionLabel)}</button>
      </div>
      <div class="home-focus-summary">
        <div><span>数据准备</span><strong>${dataCompletenessPercent()}%</strong></div>
        <div><span>待处理</span><strong>${overviewIssueCount()} 项</strong></div>
        <div><span>最近排课</span><strong>${escapeHtml(solveStatusLabel(state.solveStatus?.status))}</strong></div>
      </div>
    </section>
    ${renderWorkflowStepper()}
    <div class="home-simple-grid">
      ${renderHomeTodoCard()}
      ${renderHomeRecentCard()}
    </div>
    <details class="secondary-disclosure home-details">
      <summary>查看完整状态</summary>
      <div class="home-details-body">
        ${renderStatusStrip()}
        <div class="two-grid">
          ${renderDiagnosticsCard()}
          ${renderRecentRunsCard()}
        </div>
      </div>
    </details>
  `;
}

function overviewNextAction() {
  const readiness = state.readiness?.summary || {};
  const status = state.solveStatus || {};
  const files = asArray(status.files);
  if (isRunningStatus(status)) {
    return { view: "solve", actionLabel: "查看排课进度", stateLabel: "排课进行中", title: "系统正在生成课表", message: status.message || "排课在后台运行，你可以离开此页面，稍后再回来查看。", tone: "warning" };
  }
  if (status.status === "completed" || files.length) {
    return { view: "results", actionLabel: "查看排课结果", stateLabel: "结果已生成", title: "本次排课已有结果", message: "先预览课表和风险提示，确认无误后再下载正式文件。", tone: "ok" };
  }
  if (!state.teachers.length || !dayRuleTotal()) {
    return { view: "data", actionLabel: "准备排课数据", stateLabel: "需要准备数据", title: "先把基础数据补齐", message: "导入教师、班级、课程和作息信息后，系统会自动检查是否可以开始。", tone: "warning" };
  }
  if (!readiness.can_start_solver || Number(readiness.blocking_errors || 0) > 0) {
    return { view: "advanced", actionLabel: "处理待办问题", stateLabel: "暂不能开始", title: "还有问题需要处理", message: readiness.message || "先处理阻断项，再开始排课。", tone: "error" };
  }
  const warnings = Number(readiness.warnings || 0);
  return { view: "solve", actionLabel: "开始排课", stateLabel: "准备完成", title: "现在可以开始排课", message: warnings ? `还有 ${warnings} 个提醒，不影响试排；可在下方待办中查看。` : "数据和规则检查已通过，可以开始生成课表。", tone: "ok" };
}

function overviewIssueCount() {
  const summary = state.readiness?.summary || {};
  return Number(summary.blocking_errors || 0) + Number(summary.warnings || 0);
}

function renderHomeTodoCard() {
  const items = asArray(state.readiness?.items)
    .filter((item) => ["error", "warning", "blocked"].includes(String(item.severity || "")))
    .sort((a, b) => (SEVERITY_RANK[b.severity] || 0) - (SEVERITY_RANK[a.severity] || 0));
  const rows = items.slice(0, 3).map((item) => `
    <div class="home-todo-row ${severityTone(item.severity)}">
      <div><strong>${escapeHtml(item.title || item.domain || "待处理事项")}</strong><span>${escapeHtml(safeOperationalText(item.detail || item.suggestion || ""))}</span></div>
    </div>
  `).join("") || `<div class="home-empty-ok"><strong>没有阻断问题</strong><span>基础数据和规则可以用于本次排课。</span></div>`;
  return `
    <section class="card home-todo-card">
      <div class="card-head"><div><h2>待处理事项</h2><p>这里只显示会影响本次排课的内容。</p></div><span class="pill ${items.length ? "warning" : "ok"}">${items.length ? `${items.length} 项` : "已完成"}</span></div>
      <div class="home-todo-list">${rows}</div>
      ${items.length ? `<div class="card-actions home-card-actions"><button type="button" class="secondary" data-view-jump="advanced">查看并处理</button></div>` : ""}
    </section>
  `;
}

function renderHomeRecentCard() {
  const status = state.solveStatus || {};
  const files = asArray(status.files);
  const solutionCount = status.solution_count ?? status.result?.solution_count ?? 0;
  const hasResult = status.status === "completed" || files.length > 0;
  return `
    <section class="card home-recent-card">
      <div class="card-head"><div><h2>最近一次排课</h2><p>关闭页面不会中断正在运行的排课。</p></div><span class="pill ${severityTone(status.status)}">${escapeHtml(solveStatusLabel(status.status))}</span></div>
      <div class="home-recent-body">
        <strong>${escapeHtml(status.message || "还没有排课记录")}</strong>
        <div class="home-quick-facts">
          <div><span>候选课表</span><b>${formatNumber(solutionCount)}</b></div>
          <div><span>结果文件</span><b>${formatNumber(files.length)}</b></div>
        </div>
      </div>
      <div class="card-actions home-card-actions"><button type="button" class="secondary" data-view-jump="${hasResult ? "results" : "jobs"}">${hasResult ? "查看结果" : "查看记录"}</button></div>
    </section>
  `;
}

function renderStatusStrip() {
  const readiness = state.readiness?.summary || {};
  const metrics = state.readiness?.metrics || {};
  const status = state.solveStatus || {};
  const files = asArray(status.files);
  const dataPct = dataCompletenessPercent();
  const canStart = readiness.can_start_solver;
  const solutionCount = status.solution_count ?? status.result?.solution_count ?? status.solutions ?? 0;
  const packageReady = files.some((file) => file.category === "package" || String(file.label || file.path || "").includes("result_package"));
  const cells = [
    ["基础数据覆盖", `${dataPct}%`, `${formatNumber(metrics.teacher_rows)} 行教师定位；${dayRuleTotal()} 行白天规则${canStart ? "（核心项已通过）" : ""}`, dataPct >= 90 ? "ok" : "warning"],
    ["可以开始求解", canStart ? "是" : "否", readiness.message || "等待校验", canStart ? "ok" : "error"],
    ["当前求解", solveStatusLabel(status.status), `${formatNumber(solutionCount)} 个候选解`, isRunningStatus(status) ? "warning" : status.status === "completed" ? "ok" : "info"],
    ["当前最优结果", bestResultLabel(), bestResultHint(), status.status === "completed" ? "ok" : "info"],
    ["输出文件", packageReady ? "结果包就绪" : `${files.length} 个文件`, packageReady ? "可下载课表、诊断和清单" : "完成求解后生成", packageReady ? "ok" : "info"],
  ];
  return `<section class="status-strip">${cells.map(([label, value, hint, tone]) => `
    <div class="status-cell ${tone}">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
      <em>${escapeHtml(hint)}</em>
    </div>
  `).join("")}</section>`;
}

function renderProfileCatalogCard() {
  const catalog = state.profileCatalog || {};
  const summary = catalog.summary || {};
  const profiles = asArray(catalog.profiles);
  const issues = asArray(catalog.issues);
  const ok = summary.ok === true;
  const sampleProblems = Number(summary.sample_problems || 0);
  const rows = profiles.length ? profiles.map((profile) => {
    const sample = profile.sample_problem || {};
    const sampleHint = sample.classes
      ? `${formatNumber(sample.classes)} 个班；${formatNumber(sample.rule_instances)} 条实例规则`
      : "当前校画像";
    return `
      <div class="profile-row">
        <div>
          <strong>${escapeHtml(profile.profile_id || "school_profile")}</strong>
          <span>${escapeHtml(profile.stage || "school")} · ${escapeHtml(sampleHint)}</span>
        </div>
        <span class="pill ${profile.execution_plan_items ? "ok" : "warning"}">${formatNumber(profile.execution_plan_items)} 项计划</span>
      </div>
    `;
  }).join("") : `<div class="empty-state">未发现学校画像配置。</div>`;
  const issueRows = issues.slice(0, 3).map((issue) => `
    <div class="risk-row ${severityTone(issue.severity)}">
      <strong>${escapeHtml(issue.profile_id || "profile")}</strong>
      <span>${escapeHtml(issue.message || "")}</span>
    </div>
  `).join("");
  return `
    <section class="card profile-catalog-card" data-contract="cross-school-profile-catalog">
      <div class="card-head">
        <div>
          <h2>跨校画像部署检查</h2>
          <p>校验不同学段、作息和规则实例是否能复用当前规则目录。</p>
        </div>
        <span class="pill ${ok ? "ok" : "error"}">${ok ? "可复用" : "需修复"}</span>
      </div>
      <div class="mini-metrics">
        <div class="mini-metric"><span>学校画像</span><strong>${formatNumber(summary.profiles)}</strong></div>
        <div class="mini-metric"><span>样例问题</span><strong>${formatNumber(sampleProblems)}</strong></div>
        <div class="mini-metric"><span>错误</span><strong>${formatNumber(summary.errors)}</strong></div>
        <div class="mini-metric"><span>告警</span><strong>${formatNumber(summary.warnings)}</strong></div>
      </div>
      ${renderSchoolProblemPreviewPanel()}
      <div class="profile-list">${rows}</div>
      ${issueRows ? `<div class="risk-list">${issueRows}</div>` : ""}
    </section>
  `;
}

function renderSchoolProblemPreviewPanel() {
  const preview = state.schoolProblemPreview || {};
  const summary = preview.summary || {};
  const validation = preview.validation || {};
  const adapter = preview.adapter || {};
  const errors = asArray(validation.errors);
  const ok = validation.ok === true;
  const unavailable = adapter.status === "unavailable";
  const statusText = unavailable ? "待适配" : ok ? "已适配" : "需处理";
  const statusTone = ok ? "ok" : unavailable ? "warning" : "error";
  const hint = ok
    ? `${escapeHtml(summary.profile_id || "current_school")} · ${escapeHtml(summary.source || "web.day_inputs")}`
    : escapeHtml(errors[0] || "标准问题预览暂不可用");
  return `
    <div class="school-problem-panel" data-contract="school-problem-preview">
      <div class="profile-row">
        <div>
          <strong>当前标准排课问题</strong>
          <span>${hint}</span>
        </div>
        <span class="pill ${statusTone}">${statusText}</span>
      </div>
      <div class="mini-metrics compact">
        <div class="mini-metric"><span>班级</span><strong>${formatNumber(summary.classes)}</strong></div>
        <div class="mini-metric"><span>任课行</span><strong>${formatNumber(summary.class_subject_teacher_rows)}</strong></div>
        <div class="mini-metric"><span>可排课位</span><strong>${formatNumber(summary.available_slots)}</strong></div>
        <div class="mini-metric"><span>实例规则</span><strong>${formatNumber(summary.rule_instances)}</strong></div>
      </div>
    </div>
  `;
}

function dataCompletenessPercent() {
  const metrics = state.readiness?.metrics || {};
  const teacherRows = Number(metrics.teacher_rows || state.teachers.length || 0);
  const quality = metrics.teacher_data_quality || {};
  const issueRows = Number(quality.issue_rows || 0);
  const teacherScore = teacherRows ? clamp(Math.round(((teacherRows - issueRows) / teacherRows) * 100), 0, 100) : 0;
  const dayRows = dayRuleTotal();
  const dayScore = dayRows ? 100 : 0;
  const configScore = state.config ? 100 : 0;
  return Math.round((teacherScore * 0.45) + (dayScore * 0.35) + (configScore * 0.2));
}

function dayRuleTotal() {
  const rows = state.readiness?.metrics?.day_rule_rows || {};
  const fromMetrics = Object.values(rows).reduce((sum, value) => sum + Number(value || 0), 0);
  if (fromMetrics) return fromMetrics;
  return Object.values(state.dayRules || {}).reduce((sum, tableRows) => sum + asArray(tableRows).length, 0);
}

function bestResultLabel() {
  const status = state.solveStatus || {};
  if (!hasResultContext(status)) return "暂无";
  const quality = status.solver_quality || {};
  const objective = status.objective_value ?? status.best_objective ?? status.solver_objective_value ?? quality.objective_value;
  if (objective !== undefined && objective !== null && objective !== "") return formatNumber(objective);
  const assessment = status.publish_assessment?.summary?.status_label;
  if (assessment) return assessment;
  return status.status === "completed" ? "已生成" : "暂无";
}

function bestResultHint() {
  const status = state.solveStatus || {};
  if (!hasResultContext(status)) return "求解完成后展示最优候选和评分";
  if (status.message) return status.message;
  if (status.run_id) return status.run_id;
  return "求解完成后展示最优候选和评分";
}

function hasResultContext(status = state.solveStatus) {
  return Boolean(
    status?.run_id
    || ["starting", "running", "pause_requested", "completed", "stopped", "failed"].includes(String(status?.status || ""))
    || asArray(status?.files).length
  );
}

function renderWorkflowStepper() {
  const readiness = state.readiness?.summary || {};
  const status = state.solveStatus || {};
  const steps = [
    ["准备数据", state.teachers.length && dayRuleTotal() ? "已准备" : "待完成", state.teachers.length && dayRuleTotal() ? "done" : "warning", "data"],
    ["确认规则", allRules().length ? "已读取" : "待确认", allRules().length ? "done" : "warning", "rules"],
    ["开始排课", isRunningStatus(status) ? "进行中" : status.status === "completed" ? "已完成" : readiness.can_start_solver ? "可以开始" : "暂不可用", isRunningStatus(status) ? "active" : status.status === "completed" ? "done" : readiness.can_start_solver ? "current" : "warning", "solve"],
    ["查看结果", status.status === "completed" || asArray(status.files).length ? "已有结果" : "等待排课", status.status === "completed" || asArray(status.files).length ? "done" : "info", "results"],
  ];
  return `<section class="workflow-stepper simple-journey" aria-label="排课步骤">${steps.map(([title, detail, stateName, view], index) => `
    <button type="button" class="workflow-step ${stateName}" data-view-jump="${escapeAttr(view)}">
      <b>${index + 1}</b>
      <div><strong>${escapeHtml(title)}</strong><span>${escapeHtml(detail)}</span></div>
    </button>
  `).join("")}</section>`;
}

function publishStatusLabel() {
  return state.solveStatus?.publish_assessment?.summary?.status_label
    || state.solveStatus?.release_state?.status_label
    || "未评估";
}

function renderReadinessCard({ compact = false } = {}) {
  const readiness = state.readiness || {};
  const summary = readiness.summary || {};
  const allItems = asArray(readiness.items)
    .slice()
    .sort((a, b) => (SEVERITY_RANK[b.severity] || 0) - (SEVERITY_RANK[a.severity] || 0));
  const actionable = allItems.filter((item) => ["error", "warning", "blocked"].includes(String(item.severity || "")));
  const items = actionable.slice(0, compact ? 3 : 6);
  const rows = items.length ? items.map((item) => `
    <div class="check-row ${severityTone(item.severity)}">
      <strong>${escapeHtml(item.title || item.domain || "校验项")}</strong>
      <span>${escapeHtml(safeOperationalText(item.detail || item.suggestion || ""))}</span>
    </div>
  `).join("") : `<div class="home-empty-ok"><strong>检查通过</strong><span>没有需要教务人员处理的问题。</span></div>`;
  const passedItems = allItems.filter((item) => !["error", "warning", "blocked"].includes(String(item.severity || "")));
  return `
    <section class="card readiness-card">
      <div class="card-head">
        <div>
          <h2>排课前检查</h2>
          <p>${escapeHtml(summary.message || "检查数据和规则是否满足排课条件。")}</p>
        </div>
        <span class="pill ${severityTone(summary.status)}">${escapeHtml(summary.status_label || "未检查")}</span>
      </div>
      <div class="mini-metrics readiness-metrics">
        <div class="mini-metric"><span>必须处理</span><strong>${formatNumber(summary.blocking_errors)}</strong></div>
        <div class="mini-metric"><span>提醒</span><strong>${formatNumber(summary.warnings)}</strong></div>
      </div>
      <div class="check-list">${rows}</div>
      ${passedItems.length ? `<details class="passed-checks"><summary>查看 ${passedItems.length} 项已通过检查</summary><div class="check-list">${passedItems.slice(0, 8).map((item) => `<div class="check-row ok"><strong>${escapeHtml(item.title || item.domain || "已通过")}</strong></div>`).join("")}</div></details>` : ""}
    </section>
  `;
}

function renderSolveProgressCard() {
  const status = state.solveStatus || {};
  const request = asObject(status.request);
  const result = asObject(status.result);
  const running = isRunningStatus(status);
  const pct = solveProgressPercent(status);
  return `
    <section class="card">
      <div class="card-head">
        <div>
          <h2>求解进度</h2>
          <p>后台运行，不会阻塞界面操作。</p>
        </div>
        <span class="pill ${running ? "warning" : status.status === "completed" ? "ok" : "info"}">${escapeHtml(solveStatusLabel(status.status))}</span>
      </div>
      <div class="progress-panel">
        <div class="progress-head">
          <div>
            <strong>${escapeHtml(status.message || "还没有开始排课")}</strong>
            <p>${running ? "排课在后台运行，可以离开此页面。" : "开始后会在这里显示进度和候选课表。"}</p>
          </div>
          <div class="progress-number">${pct}%</div>
        </div>
        <div class="progress-track"><div class="progress-bar" style="width:${pct}%"></div></div>
        <div class="mini-metrics">
          <div class="mini-metric"><span>已用时</span><strong>${formatDuration(status.elapsed_seconds || result.elapsed_seconds)}</strong></div>
          <div class="mini-metric"><span>求解时长</span><strong>${formatDuration(status.time_limit_seconds || request.time_limit_seconds)}</strong></div>
          <div class="mini-metric"><span>候选解</span><strong>${formatNumber(status.solution_count || result.solution_count)}</strong></div>
        </div>
      </div>
    </section>
  `;
}

function solveProgressPercent(status) {
  if (status.status === "completed") return 100;
  if (status.status === "queued") return 8;
  if (!isRunningStatus(status)) return 0;
  const limit = Number(status.time_limit_seconds || status.request?.time_limit_seconds || 0);
  const elapsed = Number(status.elapsed_seconds || status.result?.elapsed_seconds || 0);
  if (!limit) return 20;
  return clamp(Math.round((elapsed / limit) * 100), 5, 96);
}

function formatDuration(seconds) {
  const value = Number(seconds || 0);
  if (!value) return "0 分";
  if (value < 60) return `${Math.round(value)} 秒`;
  return `${Math.floor(value / 60)} 分`;
}

function renderBestResultCard() {
  const status = state.solveStatus || {};
  const assessment = hasResultContext(status) ? (status.publish_assessment?.summary || {}) : {};
  return `
    <section class="card">
      <div class="card-head">
        <div>
          <h2>当前最优结果</h2>
          <p>实时取当前批次或推荐正式候选。</p>
        </div>
        ${state.view === "results" ? "" : `<button type="button" class="secondary" data-view-jump="results">打开结果</button>`}
      </div>
      <div class="mini-metrics">
        <div class="mini-metric"><span>综合结论</span><strong>${escapeHtml(bestResultLabel())}</strong></div>
        <div class="mini-metric"><span>候选解</span><strong>${formatNumber(status.solution_count)}</strong></div>
        <div class="mini-metric"><span>发布状态</span><strong>${escapeHtml(assessment.status_label || "未评估")}</strong></div>
      </div>
      <div class="risk-list">
        <div class="risk-row ${severityTone(assessment.status || status.status)}">
          <strong>${escapeHtml(assessment.message || status.message || "完成求解后显示质量与发布判断。")}</strong>
          <span>${escapeHtml(status.config_freshness?.message || "")}</span>
        </div>
      </div>
    </section>
  `;
}

function renderFilesCard({ limit = 0 } = {}) {
  const files = asArray(state.solveStatus?.files).slice().sort((a, b) => filePriority(a) - filePriority(b));
  const effectiveLimit = limit || state.fileLimit;
  const visible = files.slice(0, effectiveLimit);
  const rows = visible.length ? visible.map(renderFileRow).join("") : `<div class="empty-state">暂无输出文件。完成求解或生成结果包后显示。</div>`;
  return `
    <section class="card">
      <div class="card-head">
        <div>
          <h2>输出文件</h2>
          <p>优先展示正式课表和结果包；技术材料可按需继续展开。</p>
        </div>
        <button type="button" class="secondary" data-action="download-package">下载结果包</button>
      </div>
      <div class="file-list">${rows}</div>
      ${!limit && files.length > visible.length ? `<div class="list-more"><button type="button" class="secondary" data-action="show-more-files">继续显示 ${Math.min(12, files.length - visible.length)} 个文件</button></div>` : ""}
    </section>
  `;
}

function formatClock(seconds) {
  const value = Math.max(0, Math.floor(Number(seconds || 0)));
  const hours = Math.floor(value / 3600);
  const minutes = Math.floor((value % 3600) / 60);
  const secs = value % 60;
  return hours > 0
    ? [hours, minutes, secs].map((item) => String(item).padStart(2, "0")).join(":")
    : [minutes, secs].map((item) => String(item).padStart(2, "0")).join(":");
}

function renderFileRow(file) {
  const category = file.category || "other";
  const tone = category === "schedule" || category === "package" ? "ok" : category === "diagnostic" ? "warning" : "info";
  const rawLabel = file.display_label || file.label || file.download_name || file.path || "文件";
  const label = /[\\/]/.test(String(rawLabel)) ? fileBaseName(rawLabel) : rawLabel;
  return `
    <div class="file-row ${tone}">
      <div>
        <strong>${escapeHtml(label)}</strong>
        <span>${escapeHtml(file.release_use || category)} · ${formatBytes(file.size)} · ${escapeHtml(file.modified_at || "")}</span>
      </div>
      ${file.path ? `<button type="button" class="secondary" data-action="download-file" data-path="${escapeAttr(file.path)}">下载</button>` : ""}
    </div>
  `;
}

function formatBytes(size) {
  const n = Number(size || 0);
  if (!n) return "0 B";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function renderDiagnosticsCard() {
  const diagnostics = state.solveStatus?.solve_diagnostics || {};
  const packageIntegrity = state.solveStatus?.package_integrity || {};
  const issues = [
    ...asArray(diagnostics.issues),
    ...asArray(packageIntegrity.issues),
    ...asArray(state.readiness?.next_actions).map((item) => ({ ...item, detail: item.suggestion })),
  ].slice(0, 5);
  const rows = issues.length ? issues.map((item) => `
    <div class="risk-row ${severityTone(item.severity)}">
      <strong>${escapeHtml(item.title || item.domain || "诊断项")}</strong>
      <span>${escapeHtml(item.detail || item.suggestion || item.message || "")}</span>
    </div>
  `).join("") : `<div class="empty-state">暂无严重诊断问题。</div>`;
  return `
    <section class="card">
      <div class="card-head">
        <div>
          <h2>诊断结果</h2>
          <p>汇总阻断、警告、包完整性和求解建议。</p>
        </div>
      </div>
      <div class="risk-list">${rows}</div>
    </section>
  `;
}

function renderRecentRunsCard() {
  const status = state.solveStatus || {};
  const comparison = state.solveStatus?.formal_run_comparison?.runs || state.solveStatus?.formal_run_comparison?.items || [];
  const rows = asArray(comparison).slice(0, 5).map((run) => `
    <div class="run-row">
      <strong>${escapeHtml(run.name || "一次排课记录")}</strong>
      <span>${escapeHtml(run.status_label || run.status || "")} · ${escapeHtml(run.completed_at || run.updated_at || "")}</span>
    </div>
  `).join("") || `
    <div class="run-row">
      <strong>${escapeHtml(status.run_id ? "最近一次排课" : "暂无排课记录")}</strong>
      <span>${escapeHtml(status.message || "完成一次求解后会显示运行记录。")}</span>
    </div>
  `;
  return `
    <section class="card">
      <div class="card-head">
        <div>
          <h2>最近排课记录</h2>
          <p>回看之前的排课状态和结果。</p>
        </div>
      </div>
      <div class="run-list">${rows}</div>
    </section>
  `;
}

function renderDataView() {
  const quality = state.readiness?.metrics?.teacher_data_quality || {};
  const academicSummary = state.academic?.summary || {};
  const academicTables = asObject(state.academic?.data?.tables);
  const academicRows = Object.values(academicTables).reduce((sum, rows) => sum + asArray(rows).length, 0);
  const ready = Boolean(state.readiness?.summary?.can_start_solver);
  return `
    <section class="data-intro ${ready ? "ok" : "warning"}">
      <div><span class="home-state">${ready ? "可以继续" : "还需完善"}</span><h2>${ready ? "基础数据已可用于排课" : "先完成下面的数据准备"}</h2><p>推荐直接导入学校现有表格；只有少量内容需要修正时，再展开手工编辑。</p></div>
      <button type="button" class="secondary" data-action="refresh-readiness">重新检查</button>
    </section>
    <section class="data-source-grid" aria-label="数据准备项目">
      <article class="data-source-card ${state.teachers.length ? "done" : "warning"}">
        <div class="data-source-head"><span>1</span><div><strong>教师与班级</strong><small>${state.teachers.length ? `已导入 ${formatNumber(state.teachers.length)} 个班` : "尚未导入"}</small></div></div>
        <p>班级和用户表格中实际提供的各学科任课教师；班主任信息可选。</p>
        <div class="card-actions"><button type="button" class="secondary" data-action="download-teacher-template">下载模板</button><label class="upload-button">导入文件<input type="file" hidden accept=".xlsx,.xls,.csv,text/csv" data-upload="teacher"></label></div>
      </article>
      <article class="data-source-card ${dayRuleTotal() ? "done" : "warning"}">
        <div class="data-source-head"><span>2</span><div><strong>课程与作息</strong><small>${dayRuleTotal() ? `已读取 ${formatNumber(dayRuleTotal())} 条` : "尚未导入"}</small></div></div>
        <p>上课日、节次、课时、固定课位和禁排时间。</p>
        <div class="card-actions"><button type="button" class="secondary" data-action="download-day-template">下载模板</button><label class="upload-button">导入文件<input type="file" hidden accept=".xlsx,.csv,text/csv" data-upload="day-rule"></label></div>
      </article>
      <article class="data-source-card ${academicRows ? "done" : "info"}">
        <div class="data-source-head"><span>3</span><div><strong>其他教务安排</strong><small>${academicRows ? `已读取 ${formatNumber(academicRows)} 条` : "可稍后补充"}</small></div></div>
        <p>请假、调代课、考务、场地和课后服务等信息。</p>
        <div class="card-actions"><button type="button" class="secondary" data-action="download-academic-workbook">下载工作簿</button><label class="upload-button secondary">导入文件<input type="file" hidden accept=".xlsx,.csv,text/csv" data-upload="academic"></label></div>
      </article>
    </section>
    <div class="data-quality-note"><strong>${formatNumber(quality.issue_rows)} 行需要复核</strong><span>${academicSummary.risks?.length ? `另有 ${formatNumber(academicSummary.risks.length)} 项教务提醒。` : "系统会在开始排课前再次检查。"}</span></div>
    <details class="secondary-disclosure data-editor-disclosure">
      <summary>需要逐项修改？展开基础表格</summary>
      <div class="stack disclosure-body">
        ${renderTeacherTableCard()}
        ${renderDayRulesCard()}
      </div>
    </details>
    <details class="secondary-disclosure">
      <summary>调代课、考务和其他教务表</summary>
      <div class="disclosure-body">${renderAcademicTableCard()}</div>
    </details>
  `;
}

function summaryCard(title, value, hint, tone = "info") {
  return `
    <section class="card pad">
      <span class="pill ${tone}">${escapeHtml(title)}</span>
      <div style="margin-top:16px" class="status-cell ${tone}">
        <strong>${escapeHtml(value)}</strong>
        <em>${escapeHtml(hint)}</em>
      </div>
    </section>
  `;
}

function renderTeacherTableCard() {
  return `
    <section class="card">
      <div class="card-head">
        <div>
          <h2>教师定位表</h2>
          <p>班级和表格实际提供的各学科任课教师；班主任、性别仅用于值班/查寝，可不填。</p>
        </div>
        <div class="card-actions">
          <button type="button" class="secondary" data-action="download-teacher-template">Excel 模板</button>
          <button type="button" class="secondary" data-action="download-teacher-csv-template">CSV 模板</button>
          <label class="upload-button secondary">导入<input type="file" hidden accept=".xlsx,.xls,.csv,text/csv" data-upload="teacher"></label>
          <button type="button" class="secondary" data-action="add-teacher-row">新增</button>
          <button type="button" data-action="save-teachers">保存</button>
        </div>
      </div>
      ${renderEditableTable("teacher", state.teachers)}
    </section>
  `;
}

function renderDayRulesCard() {
  const keys = Object.keys(state.dayRules || {});
  if (!keys.includes(state.selectedDayRule)) state.selectedDayRule = keys[0] || "time_grid";
  return `
    <section class="card">
      <div class="card-head">
        <div>
          <h2>白天规则基础表</h2>
          <p>默认隐藏复杂表格，只在需要时编辑当前表。</p>
        </div>
        <div class="card-actions">
          <select id="dayRulePicker" data-control="day-rule-picker">
            ${keys.map((key) => `<option value="${escapeAttr(key)}" ${key === state.selectedDayRule ? "selected" : ""}>${escapeHtml(DAY_RULE_LABELS[key] || key)}</option>`).join("")}
          </select>
          <button type="button" class="secondary" data-action="download-day-template">模板</button>
          <label class="upload-button secondary">导入<input type="file" hidden accept=".xlsx,.csv,text/csv" data-upload="day-rule"></label>
          <button type="button" class="secondary" data-action="add-day-row">新增</button>
          <button type="button" data-action="save-day-rules">保存</button>
        </div>
      </div>
      ${renderEditableTable("day", asArray(state.dayRules[state.selectedDayRule]), { tableKey: state.selectedDayRule })}
    </section>
  `;
}

function renderAcademicTableCard() {
  const tables = asObject(state.academic?.data?.tables);
  const keys = Object.keys(tables);
  if (!keys.includes(state.selectedAcademicTable)) state.selectedAcademicTable = keys[0] || "substitutions";
  return `
    <section class="card">
      <div class="card-head">
        <div>
          <h2>教务功能表</h2>
          <p>调代课、考务、场地、课后服务等不会影响 CLI 协议。</p>
        </div>
        <div class="card-actions">
          <select data-control="academic-picker">
            ${keys.map((key) => `<option value="${escapeAttr(key)}" ${key === state.selectedAcademicTable ? "selected" : ""}>${escapeHtml(academicLabel(key))}</option>`).join("")}
          </select>
          <button type="button" class="secondary" data-action="download-academic-template">模板</button>
          <button type="button" class="secondary" data-action="download-academic-workbook">全量工作簿</button>
          <label class="upload-button secondary">导入<input type="file" hidden accept=".xlsx,.csv,text/csv" data-upload="academic"></label>
          <button type="button" class="secondary" data-action="add-academic-row">新增</button>
          <button type="button" data-action="save-academic">保存</button>
        </div>
      </div>
      ${renderEditableTable("academic", asArray(tables[state.selectedAcademicTable]), { tableKey: state.selectedAcademicTable })}
    </section>
  `;
}

function academicLabel(key) {
  return state.academic?.summary?.schema?.[key]?.label || ACADEMIC_LABELS[key] || key;
}

function renderEditableTable(model, rows, options = {}) {
  const cleanRows = asArray(rows);
  const columns = tableColumns(cleanRows);
  if (!cleanRows.length) {
    return `<div class="empty-state">暂无数据。可导入模板或新增一行。</div>`;
  }
  return `
    <div class="table-scroll">
      <table class="plain-table editable-table">
        <thead><tr>${columns.map((col) => `<th>${escapeHtml(col)}</th>`).join("")}</tr></thead>
        <tbody>
          ${cleanRows.map((row, rowIndex) => `<tr>
            ${columns.map((col) => `<td><input data-edit-model="${escapeAttr(model)}" data-table-key="${escapeAttr(options.tableKey || "")}" data-row="${rowIndex}" data-col="${escapeAttr(col)}" value="${escapeAttr(row[col] ?? "")}"></td>`).join("")}
          </tr>`).join("")}
        </tbody>
      </table>
    </div>
  `;
}

function tableColumns(rows) {
  const columns = [];
  for (const row of rows) {
    for (const key of Object.keys(row || {})) {
      if (key === "row_index") continue;
      if (!columns.includes(key)) columns.push(key);
    }
  }
  return columns;
}

function allRules() {
  return asArray(state.config?.business_rule_groups).flatMap((group) => asArray(group.rules).map((rule) => ({ ...rule, group_label: group.title || group.label || group.name || group.id })));
}

function renderRulesView() {
  const rules = filteredRules();
  const groups = asArray(state.config?.business_rule_groups);
  const visibleRules = rules.slice(0, state.ruleLimit);
  return `
    <div class="rules-primary">
      ${renderNaturalLanguageTool()}
    </div>
    ${renderReadinessCard({ compact: true })}
    <section class="card">
      <div class="card-head">
        <div>
          <h2>已设置的规则</h2>
          <p>共 ${formatNumber(allRules().length)} 条，先展示最常用的 ${formatNumber(visibleRules.length)} 条；可搜索教师或具体要求。</p>
        </div>
        <div class="filters">
          <input data-control="rule-search" placeholder="搜索规则、教师或说明" value="${escapeAttr(state.ruleSearch)}">
          <span class="segmented">
            ${["all", "hard", "soft"].map((mode) => `<button type="button" class="${state.ruleMode === mode ? "active" : ""}" data-action="set-rule-mode" data-mode="${mode}">${mode === "all" ? "全部" : mode === "hard" ? "必须满足" : "尽量满足"}</button>`).join("")}
          </span>
        </div>
      </div>
      <div class="rule-grid">${visibleRules.length ? visibleRules.map(renderRuleCard).join("") : `<div class="empty-state">没有匹配的规则。</div>`}</div>
      ${rules.length > visibleRules.length ? `<div class="list-more"><button type="button" class="secondary" data-action="show-more-rules">再显示 ${Math.min(18, rules.length - visibleRules.length)} 条</button></div>` : ""}
    </section>
    <details class="secondary-disclosure">
      <summary>AI 助手状态</summary>
      <div class="disclosure-body">${renderAiServiceStatusCard()}</div>
    </details>
  `;
}

function filePriority(file) {
  const category = String(file.release_use || file.category || "").toLowerCase();
  if (category.includes("official") || category === "package" || category === "schedule") return 0;
  if (category.includes("diagnostic")) return 1;
  return 2;
}

function fileBaseName(value) {
  return String(value || "").split(/[\\/]/).filter(Boolean).pop() || "";
}

function safeOperationalText(value, maxLength = 420) {
  let text = String(value || "");
  text = text.replace(/[A-Za-z]:[\\/](?:[^\s,，；;]+[\\/])*([^\\/\s,，；;]+)/g, (_match, name) => `服务器文件：${name}`);
  text = text.replace(/(?:\/[^\s,，；;]+){3,}/g, (match) => `服务器文件：${fileBaseName(match)}`);
  return text.length > maxLength ? `${text.slice(0, maxLength)}…` : text;
}

function filteredRules() {
  const query = state.ruleSearch.trim().toLowerCase();
  return allRules().filter((rule) => {
    const mode = ruleMode(rule);
    if (state.ruleMode !== "all" && state.ruleMode !== mode) return false;
    if (!query) return true;
    return JSON.stringify(rule).toLowerCase().includes(query);
  });
}

function ruleMode(rule) {
  const text = `${rule.mode || ""} ${rule.mode_label || ""} ${rule.type || ""} ${rule.priority_label || ""}`.toLowerCase();
  if (text.includes("soft") || text.includes("尽量") || text.includes("偏好")) return "soft";
  return "hard";
}

function renderRuleCard(rule) {
  const mode = ruleMode(rule);
  const targets = asArray(rule.targets || rule.target_teachers || rule.subjects).slice(0, 5);
  const technicalId = String(rule.id || "");
  return `
    <article class="rule-card">
      <header>
        <div>
          <h3>${escapeHtml(ruleDisplayName(rule))}</h3>
          <p>${escapeHtml(rule.group_label || rule.domain || "")}</p>
        </div>
        <span class="pill ${mode === "soft" ? "ok" : "info"}">${mode === "soft" ? "尽量满足" : "必须满足"}</span>
      </header>
      <p>${escapeHtml(rule.explanation || rule.description || rule.explain || rule.summary || `用于控制${rule.group_label || "排课"}中的业务边界，修改前可先生成规则草案并校验。`)}</p>
      <div class="tag-list">
        <span class="tag">${rule.enabled === false ? "关闭" : "启用"}</span>
        ${targets.map((item) => `<span class="tag">${escapeHtml(item)}</span>`).join("")}
      </div>
      <button type="button" class="secondary" data-action="edit-rule" data-rule-id="${escapeAttr(rule.id)}" ${rule.locked ? "disabled" : ""}>${rule.locked ? "系统锁定" : "配置规则"}</button>
      ${technicalId ? `<details class="rule-tech-meta"><summary>更多信息</summary><code>${escapeHtml(technicalId)}</code></details>` : ""}
    </article>
  `;
}

function ruleDisplayName(rule) {
  const id = String(rule.id || "");
  const candidate = String(rule.title || rule.label || rule.name || "").trim();
  if (candidate && candidate !== id && !candidate.includes(".")) return candidate;
  const tokens = id.split(/[._-]+/).filter(Boolean).filter((token) => !["personal", "teacher", "enable", "rule"].includes(token));
  const labels = {
    xhd: "查寝", night: "晚自习", no: "禁排", need: "需要", couple: "联动",
    zf: "值房", zw: "值晚", weekday: "工作日", sun: "周日", cap: "上限",
    am1: "上午第一节", am2: "上午第二节", am4: "上午第四节", am12: "上午前两节",
    pm1: "下午第一节", pm2: "下午第二节", pm3: "下午第三节", teacher: "教师",
    subject: "学科", class: "班级", max: "最多", min: "至少", fixed: "固定",
  };
  const translated = tokens.map((token) => labels[token] || (/^\d+$/.test(token) ? token : "")).filter(Boolean);
  return translated.length ? translated.join(" · ") : `${rule.group_label || "排课"}业务规则`;
}

function aiRuleSettings() {
  return asObject(state.config?.effective?.rules?.ai_rule_assistant || state.config?.overrides?.rules?.ai_rule_assistant);
}

function configuredAiProviders() {
  const settings = aiRuleSettings();
  const providers = asArray(settings.providers);
  return providers.length ? providers : (settings.base_url ? [settings] : []);
}

function renderAiServiceStatusCard() {
  const settings = aiRuleSettings();
  const providers = configuredAiProviders().filter((provider) => provider.enabled !== false);
  const enabled = Boolean(settings.enabled && providers.length);
  const probe = asObject(state.aiProviderProbe);
  const statusLabel = !enabled
    ? "使用本地整理"
    : probe.status === "ready"
      ? "连接正常"
      : probe.status === "unavailable"
        ? "连接失败"
        : "已配置，待检测";
  const statusTone = !enabled ? "info" : probe.status === "ready" ? "ok" : probe.status === "unavailable" ? "error" : "warning";
  const usage = state.modelUsage?.totals || {};
  return `
    <section class="card ai-service-card">
      <div class="card-head"><div><h2>AI 助手</h2><p>只帮你把口头要求整理成规则草案，确认后才会用于排课。</p></div><span class="pill ${statusTone}">${statusLabel}</span></div>
      <div class="mini-metrics ai-simple-metrics">
        <div class="mini-metric"><span>当前方式</span><strong>${enabled ? "AI 辅助" : "本地整理"}</strong></div>
        <div class="mini-metric"><span>本月使用</span><strong>${formatNumber(usage.requests)} 次</strong></div>
      </div>
      ${isAdminRole() ? `<div class="card-actions form-actions"><button type="button" class="secondary" data-view-jump="usage">打开管理员设置</button></div>` : ""}
    </section>
  `;
}

function renderSolveView() {
  const showProgress = isRunningStatus(state.solveStatus) || state.solveStatus?.status === "completed";
  return `
    <div class="solve-layout ${showProgress ? "has-progress" : "single"}">
      ${renderSolveFormCard()}
      ${showProgress ? renderSolveProgressCard() : ""}
      ${renderReadinessCard({ compact: true })}
    </div>
    <details class="secondary-disclosure">
      <summary>排课记录与输出文件</summary>
      <div class="two-grid disclosure-body">${renderJobQueueCard({ limit: 5 })}${renderFilesCard({ limit: 6 })}</div>
    </details>
  `;
}

function renderJobsView() {
  return `
    ${renderJobSummaryStrip()}
    ${renderJobQueueCard({ limit: 30, standalone: true })}
  `;
}

function renderJobSummaryStrip() {
  const jobs = asArray(state.solveJobs?.jobs);
  const count = (status) => jobs.filter((job) => status.includes(String(job.status || ""))).length;
  return `
    <section class="status-strip job-status-strip">
      ${[
        ["待处理", count(["queued"]), "info"],
        ["运行中", count(["running", "cancel_requested"]), "warning"],
        ["已完成", count(["completed"]), "ok"],
        ["失败/取消", count(["failed", "cancelled"]), "error"],
      ].map(([label, value, tone]) => `<div class="status-cell ${tone}"><span>${label}</span><strong>${formatNumber(value)}</strong></div>`).join("")}
    </section>
  `;
}

function renderJobQueueCard({ limit = 10, standalone = false } = {}) {
  const jobs = asArray(state.solveJobs?.jobs).slice(0, limit);
  const rows = jobs.map((job) => {
    const status = String(job.status || "unknown");
    const active = ["queued", "running", "cancel_requested"].includes(status);
    const request = asObject(job.request);
    const error = asObject(job.error);
    return `
      <article class="job-row ${severityTone(status)}">
        <div class="job-state"><span class="job-dot" aria-hidden="true"></span><strong>${escapeHtml(solveStatusLabel(status))}</strong></div>
        <div class="job-main">
          <strong>${request.mode === "night" ? "晚自习与值班" : "全校课表"}</strong>
          <span>${escapeHtml(formatDateTime(job.created_at))} · 计划用时 ${formatDuration(request.time_limit_seconds)}</span>
          ${error.message ? `<small>${escapeHtml(error.message)}</small>` : ""}
          <details class="job-meta"><summary>任务信息</summary><small>数据版本 ${formatNumber(job.workspace_revision)} · 任务编号 ${escapeHtml(String(job.id || "").slice(0, 8))}</small></details>
        </div>
        <div class="job-actions">
          ${active ? `<button type="button" class="secondary danger" data-action="cancel-job" data-job-id="${escapeAttr(job.id)}">取消</button>` : ""}
        </div>
      </article>
    `;
  }).join("") || `<div class="empty-state">暂无持久化求解任务。首次开始求解后会在这里保留运行记录。</div>`;
  return `
    <section class="card job-center-card">
      <div class="card-head">
        <div><h2>${standalone ? "全部排课记录" : "最近排课"}</h2><p>排课在后台运行，关闭页面不会中断。</p></div>
        ${standalone ? `<button type="button" class="secondary" data-action="refresh-jobs">刷新</button>` : `<button type="button" class="secondary" data-view-jump="jobs">查看全部</button>`}
      </div>
      <div class="job-list">${rows}</div>
    </section>
  `;
}

function formatDateTime(value) {
  if (!value) return "时间待记录";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function renderSolveFormCard() {
  const running = isRunningStatus(state.solveStatus);
  const duration = Number(state.solveStatus?.time_limit_seconds || 300);
  const durationOptions = [[60, "快速试排（约 1 分钟）"], [300, "标准排课（约 5 分钟）"], [600, "充分优化（约 10 分钟）"], [1800, "精细优化（约 30 分钟）"]];
  if (!durationOptions.some(([value]) => value === duration)) durationOptions.unshift([duration, `沿用上次设置（${formatDuration(duration)}）`]);
  return `
    <section class="card">
      <div class="card-head">
        <div>
          <h2>${running ? "排课正在进行" : "开始一次排课"}</h2>
          <p>${running ? "可以离开此页面，完成后会自动生成候选课表。" : "通常只需要选择排课范围和优化时间。"}</p>
        </div>
        <div class="card-actions">
          ${running
            ? `<button type="button" class="secondary" data-action="pause-solve">暂停并保留当前结果</button><button type="button" class="secondary danger" data-action="stop-solve">停止排课</button>`
            : `<button type="button" data-action="start-solve">开始排课</button>`}
        </div>
      </div>
      <div class="form-grid solve-basic-form">
        <label for="solveMode">排课范围</label>
        <select id="solveMode" data-control="solve-mode">
          <option value="course" ${state.solveMode === "course" ? "selected" : ""}>按业务配置排课（自定义时间格与周期课时）</option>
          <option value="day" ${state.solveMode === "day" ? "selected" : ""}>旧版课程排课</option>
          <option value="joint" ${state.solveMode === "joint" ? "selected" : ""}>全校课表（白天、晚自习和值班）</option>
          <option value="night" ${state.solveMode === "night" ? "selected" : ""}>只排晚自习和值班</option>
        </select>
        <label for="solveTimeLimit">优化时间</label>
        <select id="solveTimeLimit">${durationOptions.map(([value, label]) => `<option value="${value}" ${value === duration ? "selected" : ""}>${label}</option>`).join("")}</select>
      </div>
      <div class="details-panel">
        <details>
          <summary>管理员选项（一般不用修改）</summary>
          <div class="form-grid">
            <label for="solveWorkers">并行线程</label>
            <input id="solveWorkers" type="number" min="1" step="1" value="${escapeAttr(state.solveStatus?.workers || 8)}">
            <label for="solveRandomSeed">随机种子</label>
            <input id="solveRandomSeed" type="number" min="0" step="1" value="${escapeAttr(state.solveStatus?.random_seed ?? 7)}">
            <label for="solveMaxKeep">保留候选解数</label>
            <input id="solveMaxKeep" type="number" min="1" step="1" value="${escapeAttr(state.solveStatus?.max_keep || 10)}">
            <label for="solveSnapshotInterval">快照间隔</label>
            <input id="solveSnapshotInterval" type="number" min="5" step="5" value="${escapeAttr(state.solveStatus?.snapshot_interval_sec || 30)}">
            <label for="solveEnableSnapshots">过程快照</label>
            <select id="solveEnableSnapshots"><option value="false">关闭</option><option value="true" ${state.solveStatus?.enable_snapshots ? "selected" : ""}>开启</option></select>
            <label for="solveProfile">优化策略</label>
            <select id="solveProfile">
              <option value="">默认</option>
              <option value="balanced">均衡</option>
              <option value="improve_incumbent">改善当前候选</option>
              <option value="prove_bound">加强证明界</option>
            </select>
            <label for="solveRelativeGap">相对差距目标</label>
            <input id="solveRelativeGap" type="number" min="0" step="0.01" placeholder="留空">
            <label for="solveAbsoluteGap">绝对差距目标</label>
            <input id="solveAbsoluteGap" type="number" min="0" step="1" placeholder="留空">
          </div>
          <div class="card-actions form-actions"><button type="button" class="secondary" data-action="continue-solve">沿用当前结果继续优化</button></div>
        </details>
      </div>
      ${state.solveStatus?.log_tail ? `<details class="technical-log"><summary>查看技术日志</summary><div class="log-box">${escapeHtml(safeOperationalText(state.solveStatus.log_tail, 12000))}</div></details>` : ""}
    </section>
  `;
}

function renderResultsView() {
  if (!hasResultContext() && !previewViews().length) {
    return `
      <section class="card result-empty-card">
        <div class="result-empty-copy"><span class="home-state">等待排课</span><h2>还没有可查看的课表</h2><p>完成一次排课后，这里会集中展示班级课表、教师课表、风险提示和下载文件。</p><button type="button" data-view-jump="solve">去开始排课</button></div>
      </section>
      <details class="secondary-disclosure"><summary>查看当前提醒</summary><div class="disclosure-body">${renderDiagnosticsCard()}</div></details>
    `;
  }
  return `
    ${renderBestResultCard()}
    <div class="main-grid">
      <div class="stack">
        ${renderSchedulePreviewCard()}
        ${renderResultRiskCard()}
      </div>
      <div class="stack">
        ${renderFilesCard()}
        ${renderDiagnosticsCard()}
      </div>
    </div>
  `;
}

function renderSchedulePreviewCard() {
  const preview = state.resultPreview || {};
  const summary = preview.summary || {};
  const views = previewViews();
  if (!views.some((item) => item.name === state.resultPreviewItem)) {
    state.resultPreviewItem = views[0]?.name || "";
  }
  const current = views.find((item) => item.name === state.resultPreviewItem) || views[0];
  return `
    <section class="card">
      <div class="card-head">
        <div>
          <h2>课表在线预览</h2>
          <p>${escapeHtml(summary.message || "生成课表后可按班级、教师或原始表抽查。")}</p>
        </div>
      </div>
      <div class="schedule-picker">
        <select data-control="preview-kind">
          <option value="class" ${state.resultPreviewKind === "class" ? "selected" : ""}>班级视图</option>
          <option value="teacher" ${state.resultPreviewKind === "teacher" ? "selected" : ""}>教师视图</option>
          <option value="sheet" ${state.resultPreviewKind === "sheet" ? "selected" : ""}>原始表</option>
        </select>
        <select data-control="preview-item">
          ${views.map((view) => `<option value="${escapeAttr(view.name)}" ${view.name === state.resultPreviewItem ? "selected" : ""}>${escapeHtml(view.name)}</option>`).join("")}
        </select>
      </div>
      ${current ? renderScheduleTable(current) : `<div class="empty-state">暂无可预览课表。</div>`}
    </section>
  `;
}

function previewViews() {
  const preview = state.resultPreview || {};
  if (state.resultPreviewKind === "teacher") return asArray(preview.teacher_views);
  if (state.resultPreviewKind === "sheet") {
    return asArray(preview.workbooks).flatMap((workbook) => asArray(workbook.sheets).map((sheet) => ({
      kind: "sheet",
      name: `${workbook.label || "工作簿"} / ${sheet.name}`,
      columns: [],
      rows: asArray(sheet.rows).map((row, index) => ({ slot: `第 ${index + 1} 行`, values: Object.fromEntries(row.map((cell, i) => [`列${i + 1}`, cell])) })),
    })));
  }
  return asArray(preview.class_views);
}

function renderScheduleTable(view) {
  const columns = asArray(view.columns).length ? view.columns : tableColumns(asArray(view.rows).map((row) => row.values || {}));
  return `
    <div class="table-scroll">
      <table class="plain-table preview-table">
        <thead><tr><th>节次</th>${columns.map((col) => `<th>${escapeHtml(col)}</th>`).join("")}</tr></thead>
        <tbody>
          ${asArray(view.rows).map((row) => `<tr><td>${escapeHtml(row.slot || "")}</td>${columns.map((col) => `<td>${escapeHtml(row.values?.[col] || "")}</td>`).join("")}</tr>`).join("")}
        </tbody>
      </table>
    </div>
  `;
}

function renderResultRiskCard() {
  const status = state.solveStatus || {};
  const assessment = status.publish_assessment || {};
  const summary = assessment.summary || {};
  return `
    <section class="card">
      <div class="card-head">
        <div>
          <h2>课表风险提示</h2>
          <p>${escapeHtml(summary.message || "下载前查看求解质量、配置版本和教务风险提示。")}</p>
        </div>
        <span class="pill ${severityTone(summary.status)}">${escapeHtml(summary.status_label || "未评估")}</span>
      </div>
      <div class="risk-list">
        ${asArray(assessment.gates).slice(0, 5).map((gate) => `
          <div class="risk-row ${severityTone(gate.severity)}"><strong>${escapeHtml(gate.title || gate.domain || "风险项")}</strong><span>${escapeHtml(gate.detail || gate.suggestion || "")}</span></div>
        `).join("") || `<div class="empty-state">暂无待展示的风险提示。</div>`}
      </div>
    </section>
  `;
}

function renderUsageView() {
  if (!isAdminRole()) return `<section class="card pad empty-state">当前身份无权查看 AI 成本和配额。</section>`;
  const usage = state.modelUsage || {};
  const totals = usage.totals || {};
  const quota = usage.quota || {};
  const settings = aiRuleSettings();
  const providers = configuredAiProviders();
  const primary = providers[0] || settings;
  const probe = asObject(state.aiProviderProbe);
  const probeLabel = !settings.enabled ? "使用本地整理" : probe.status === "ready" ? "连接正常" : probe.status === "unavailable" ? "连接失败" : "已配置，待检测";
  const probeTone = !settings.enabled ? "info" : probe.status === "ready" ? "ok" : probe.status === "unavailable" ? "error" : "warning";
  const breakdown = asArray(usage.breakdown);
  return `
    <section class="usage-hero">
      <div><p class="eyebrow">管理员设置</p><h2>AI 助手${settings.enabled ? "已开启" : "未开启"}</h2><p>AI 只辅助整理口头规则；教师姓名会先替换为临时代号，不发送整份教师表，也不保存原始提示词。</p></div>
      <span class="pill ${probeTone}">${probeLabel}</span>
    </section>
    ${probe.message ? `<p class="usage-probe-note ${probeTone}" role="status">${escapeHtml(probe.message)}</p>` : ""}
    <section class="usage-summary-grid">
      <div><span>本月使用</span><strong>${formatNumber(totals.requests)} 次</strong></div>
      <div><span>预计费用</span><strong>${formatCurrency(totals.cost_microunits)}</strong></div>
      <div><span>当前服务</span><strong>${escapeHtml(primary.model || (settings.enabled ? "待设置模型" : "本地整理"))}</strong></div>
    </section>
    <div class="two-grid usage-simple-grid">
      <section class="card">
        <div class="card-head"><div><h2>辅助录入</h2><p>开启后，教务人员可以用一句话添加规则草案。</p></div></div>
        <div class="form-grid">
          <label for="aiEnabled">AI 助手</label>
          <select id="aiEnabled"><option value="false">关闭，使用本地整理</option><option value="true" ${settings.enabled ? "selected" : ""}>开启 AI 辅助</option></select>
          <label>当前模型</label><div class="field-readonly">${escapeHtml(primary.model || "尚未设置")}</div>
        </div>
        <div class="card-actions form-actions"><button type="button" data-action="save-ai-settings">保存 AI 设置</button></div>
      </section>
      <section class="card">
        <div class="card-head"><div><h2>每月使用上限</h2><p>给学校设置次数或费用上限，0 表示不限制。</p></div></div>
        ${renderQuotaMeters(totals, quota)}
        <div class="form-grid quota-form">
          <label for="quotaRequests">每月最多使用（次）</label><input id="quotaRequests" type="number" min="0" value="${escapeAttr(quota.request_limit || 0)}">
          <label for="quotaCostYuan">每月费用上限</label><input id="quotaCostYuan" type="number" min="0" step="0.01" value="${escapeAttr(microunitsToYuan(quota.cost_limit_microunits || 0))}">
        </div>
        <div class="card-actions form-actions"><button type="button" data-action="save-model-quota">保存使用上限</button></div>
      </section>
    </div>
    <details class="secondary-disclosure technical-disclosure">
      <summary>供应商与计费参数（技术管理员）</summary>
      <div class="disclosure-body stack">
        <section class="card">
          <div class="card-head"><div><h2>模型服务接入</h2><p>兼容 OpenAI Chat Completions 与 Responses；密钥只放服务器环境变量，不写入数据库或浏览器。</p></div></div>
          <div class="form-grid ai-settings-form">
            <label for="aiProviderName">供应商标识</label><input id="aiProviderName" value="${escapeAttr(primary.provider_name || "dashscope")}" placeholder="dashscope / zhipu / deepseek">
            <label for="aiBaseUrl">兼容接口地址</label><input id="aiBaseUrl" type="url" value="${escapeAttr(primary.base_url || "")}" placeholder="https://.../v1">
            <label for="aiModel">模型</label><input id="aiModel" value="${escapeAttr(primary.model || "")}" placeholder="模型标识">
            <label for="aiApiKeyEnv">密钥环境变量名</label><input id="aiApiKeyEnv" value="${escapeAttr(primary.api_key_env || "")}" placeholder="DASHSCOPE_API_KEY">
            <label for="aiWireApi">接口协议</label><select id="aiWireApi"><option value="chat_completions" ${String(primary.wire_api || "chat_completions") === "chat_completions" ? "selected" : ""}>Chat Completions</option><option value="responses" ${String(primary.wire_api || "") === "responses" ? "selected" : ""}>Responses API</option></select>
            <label for="aiReasoningEffort">推理强度</label><select id="aiReasoningEffort"><option value="">供应商默认</option>${["minimal", "low", "medium", "high", "xhigh"].map((value) => `<option value="${value}" ${String(primary.reasoning_effort || "") === value ? "selected" : ""}>${value}</option>`).join("")}</select>
            <label>响应留存</label><div class="field-readonly">关闭（请求固定发送 store: false）</div>
            <label for="aiInputPrice">输入价格（微元/百万 Token；1 元 = 1000000 微元）</label><input id="aiInputPrice" type="number" min="0" value="${escapeAttr(primary.input_price_microunits_per_million || 0)}">
            <label for="aiOutputPrice">输出价格（微元/百万 Token；1 元 = 1000000 微元）</label><input id="aiOutputPrice" type="number" min="0" value="${escapeAttr(primary.output_price_microunits_per_million || 0)}">
            <label for="quotaTokens">Token 上限</label><input id="quotaTokens" type="number" min="0" value="${escapeAttr(quota.token_limit || 0)}">
          </div>
          <div class="card-actions form-actions"><button type="button" data-action="save-ai-settings">保存连接参数</button><button type="button" class="secondary" data-action="test-ai-connection">测试真实连接</button></div>
          ${probe.message ? `<p class="card-note">${escapeHtml(probe.message)}</p>` : ""}
          ${providers.length > 1 ? `<p class="card-note">另有 ${providers.length - 1} 个备用供应商会被原样保留。</p>` : ""}
        </section>
        <section class="card">
          <div class="card-head"><div><h2>用量明细</h2><p>${escapeHtml(usage.period_start ? formatBillingPeriod(usage.period_start) : "本月尚无计费记录")}</p></div></div>
          <div class="table-scroll"><table class="plain-table"><thead><tr><th>供应商</th><th>模型</th><th>状态</th><th>请求</th><th>Token</th><th>成本</th></tr></thead><tbody>
            ${breakdown.map((item) => `<tr><td>${escapeHtml(item.provider_id || "未选择")}</td><td>${escapeHtml(item.model || "未记录")}</td><td>${escapeHtml(modelUsageStatusLabel(item.status))}</td><td>${formatNumber(item.requests)}</td><td>${formatNumber(item.tokens)}</td><td>${formatCurrency(item.cost_microunits)}</td></tr>`).join("") || `<tr><td colspan="6">本月尚无模型调用。</td></tr>`}
          </tbody></table></div>
        </section>
      </div>
    </details>
  `;
}

function renderQuotaMeters(totals, quota) {
  const rows = [
    ["使用次数", Number(totals.requests || 0), Number(quota.request_limit || 0), false],
    ["预计费用", Number(totals.cost_microunits || 0), Number(quota.cost_limit_microunits || 0), true],
  ];
  return `<div class="quota-meters">${rows.map(([label, used, limit, money]) => {
    const pct = limit ? clamp(Math.round((used / limit) * 100), 0, 100) : 0;
    const usedLabel = money ? formatCurrency(used) : formatNumber(used);
    const limitLabel = limit ? (money ? formatCurrency(limit) : formatNumber(limit)) : "不限";
    return `<div class="quota-meter"><div><strong>${label}</strong><span>${usedLabel} / ${limitLabel}</span></div><div class="progress-track"><div class="progress-bar" style="width:${pct}%"></div></div></div>`;
  }).join("")}</div>`;
}

function formatBillingPeriod(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "本月" : `${date.getFullYear()} 年 ${date.getMonth() + 1} 月`;
}

function microunitsToYuan(value) {
  const amount = Number(value || 0) / 1_000_000;
  return amount ? Number(amount.toFixed(6)) : 0;
}

function formatCurrency(value) {
  return `¥${microunitsToYuan(value).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 6 })}`;
}

function modelUsageStatusLabel(status) {
  return ({ succeeded: "成功", failed: "失败", denied: "配额拒绝", reserved: "处理中" })[String(status || "")] || String(status || "未知");
}

function renderAdvancedView() {
  return `
    ${renderConflictTool()}
    <div class="two-grid">
      ${renderLeaveRepairTool()}
      ${renderManualAdjustmentTool()}
    </div>
    ${renderAuditCard()}
    <details class="secondary-disclosure technical-disclosure">
      <summary>系统与跨校适配检查</summary>
      <div class="disclosure-body">${renderProfileCatalogCard()}</div>
    </details>
  `;
}

function renderConflictTool() {
  const summary = state.conflicts?.summary || {};
  const rows = asArray(state.conflicts?.conflicts).slice(0, 8).map((item) => `
    <div class="risk-row ${severityTone(item.severity || "error")}"><strong>${escapeHtml(item.title || item.id || "冲突")}</strong><span>${escapeHtml(item.detail || item.suggestion || "")}</span></div>
  `).join("") || `<div class="empty-state">点击运行后显示确定冲突。</div>`;
  return `
    <section class="card">
      <div class="card-head"><div><h2>冲突检测</h2><p>只展示确定冲突和可操作建议。</p></div><button type="button" data-action="run-conflicts">运行</button></div>
      <div class="mini-metrics">
        <div class="mini-metric"><span>错误</span><strong>${formatNumber(summary.errors)}</strong></div>
        <div class="mini-metric"><span>警告</span><strong>${formatNumber(summary.warnings)}</strong></div>
      </div>
      <div class="risk-list">${rows}</div>
    </section>
  `;
}

function ruleDraftCanApply(rule) {
  return Boolean(rule?.validation?.valid && rule?.solver_supported && Array.isArray(rule?.patches) && rule.patches.length);
}

function renderRuleDraftReview(rule) {
  if (!rule) return `<div class="empty-state">暂无规则草案。</div>`;
  const validation = rule.validation || {};
  const provenance = rule.provenance || {};
  const errors = Array.isArray(validation.errors) ? validation.errors : [];
  const warnings = Array.isArray(validation.warnings) ? validation.warnings : [];
  const confidence = Number.isFinite(Number(rule.confidence)) ? `${Math.round(Number(rule.confidence) * 100)}%` : "待评估";
  const source = provenance.parser === "model"
    ? `AI · ${provenance.provider_id || "已配置供应商"} · ${provenance.model || "模型未标注"}`
    : "本地确定性解析";
  const issueRows = [...errors.map((item) => `错误：${item}`), ...warnings.map((item) => `提示：${item}`)]
    .map((item) => `<li>${escapeHtml(item)}</li>`)
    .join("");
  return `
    <div class="risk-row ${validation.valid ? (rule.solver_supported ? "ok" : "warning") : "error"}">
      <strong>${escapeHtml(rule.description || rule.id || "规则草案")}</strong>
      <span>状态：待人工确认 · 来源：${escapeHtml(source)} · 置信度：${escapeHtml(confidence)}</span>
      ${issueRows ? `<ul>${issueRows}</ul>` : ""}
    </div>
  `;
}

function renderNaturalLanguageTool() {
  return `
    <section class="card">
      <div class="card-head"><div><h2>用一句话添加规则</h2><p>先生成草案给你确认，不会直接修改当前排课规则。</p></div></div>
      <div class="form-grid">
        <label for="nlInput">告诉系统你的要求</label>
        <textarea id="nlInput" placeholder="例如：教师A周日晚自习不能排课">${escapeHtml(state.parsedRule?.source_text || "")}</textarea>
      </div>
      <div class="card-actions" style="padding:0 16px 16px">
        <button type="button" data-action="parse-nl-rule">整理成规则</button>
        <button type="button" class="secondary" data-action="add-nl-rule" ${ruleDraftCanApply(state.parsedRule) ? "" : "disabled"}>确认使用</button>
        <button type="button" class="secondary danger" data-action="remove-nl-rule" ${state.parsedRule ? "" : "disabled"}>删除草案</button>
      </div>
      <div class="risk-list">${renderRuleDraftReview(state.parsedRule)}</div>
    </section>
  `;
}

function renderLeaveRepairTool() {
  return `
    <section class="card">
      <div class="card-head"><div><h2>请假代课局部调整</h2><p>保留候选影响矩阵，先预览再写入全局课表。</p></div></div>
      <div class="form-grid">
        <label for="leaveRepairTeacher">请假教师</label><input id="leaveRepairTeacher" placeholder="如 教师A">
        <label for="leaveRepairDay">星期</label><input id="leaveRepairDay" placeholder="星期一">
        <label for="leaveRepairSlot">节次</label><input id="leaveRepairSlot" placeholder="上午1 / 全天">
        <label for="leaveRepairClass">班级</label><input id="leaveRepairClass" placeholder="可留空自动定位">
        <label for="leaveRepairSubstitute">代课教师</label><input id="leaveRepairSubstitute" placeholder="可留空自动推荐">
      </div>
      <div class="card-actions" style="padding:0 16px 16px">
        <button type="button" class="secondary" data-action="preview-leave-repair">生成局部方案</button>
        <button type="button" data-action="apply-leave-repair">应用到全局课表</button>
      </div>
      ${renderLeaveRepairResult()}
    </section>
  `;
}

function renderLeaveRepairResult() {
  const repair = state.leaveRepairPreview;
  if (!repair) return `<div class="empty-state">暂无候选方案。</div>`;
  const candidates = asArray(repair.repair?.candidate_options || repair.candidate_options);
  if (!candidates.length) {
    return `<div class="risk-list"><div class="risk-row ${repair.ok === false ? "error" : "info"}"><strong>${escapeHtml(repair.message || "预览结果")}</strong><span>${escapeHtml(repair.error || "")}</span></div></div>`;
  }
  return `<div class="candidate-matrix">${candidates.map((candidate) => `
    <div class="candidate-row">
      <div>
        <strong>${escapeHtml(candidate.teacher || candidate.substitute || candidate.name || "候选教师")}</strong>
        <div class="candidate-impact">
          <span>${candidate.recommended ? "系统推荐" : "候选"}</span>
          <span>${escapeHtml(candidate.source_label || candidate.source || "")}</span>
          <span>${escapeHtml(candidate.impact_label || candidate.reason || "")}</span>
        </div>
      </div>
      <span class="pill ${candidate.feasible === false ? "error" : "ok"}">${candidate.feasible === false ? "不可用" : "可用"}</span>
    </div>
  `).join("")}</div>`;
}

function renderManualAdjustmentTool() {
  return `
    <section class="card">
      <div class="card-head"><div><h2>课表微调沙盘</h2><p>直接填写课位，先预览影响再更新全局课表。</p></div></div>
      <div class="form-grid">
        <label for="manualAdjustClass">班级</label><input id="manualAdjustClass" placeholder="如 8班">
        <label for="manualAdjustFromDay">原星期</label><input id="manualAdjustFromDay" placeholder="星期一">
        <label for="manualAdjustFromSlot">原节次</label><input id="manualAdjustFromSlot" placeholder="上午1">
        <label for="manualAdjustToDay">新星期</label><input id="manualAdjustToDay" placeholder="星期二">
        <label for="manualAdjustToSlot">新节次</label><input id="manualAdjustToSlot" placeholder="下午1">
        <label for="manualAdjustTeacher">新教师</label><input id="manualAdjustTeacher" placeholder="可留空">
      </div>
      <div class="card-actions" style="padding:0 16px 16px">
        <button type="button" class="secondary" data-action="preview-manual-adjustment">预览微调影响</button>
        <button type="button" data-action="apply-manual-adjustment">更新全局课表</button>
      </div>
      <div class="risk-list">${state.manualAdjustmentPreview ? `<div class="risk-row ok"><strong>${escapeHtml(state.manualAdjustmentPreview.message || "已生成预览")}</strong><span>${escapeHtml(JSON.stringify(state.manualAdjustmentPreview.summary || {}, null, 2))}</span></div>` : `<div class="empty-state">暂无微调预览。</div>`}</div>
    </section>
  `;
}

function renderAuditCard() {
  const rows = asArray(state.audit?.entries).slice(0, 20).map((entry) => `
    <div class="audit-row"><strong>${escapeHtml(entry.source || "配置变更")}</strong><span>${escapeHtml(entry.created_at || entry.updated_at || "")} · ${escapeHtml(entry.reason || "")}</span></div>
  `).join("") || `<div class="empty-state">暂无审计记录，或尚未加载。</div>`;
  return `
    <section class="card">
      <div class="card-head"><div><h2>配置变更记录</h2><p>保存、导入、规则修复和回滚都会写入审计。</p></div><button type="button" class="secondary" data-action="load-audit">刷新审计</button></div>
      <div class="audit-list">${rows}</div>
    </section>
  `;
}

function updateEditableModel(input) {
  const model = input.dataset.editModel;
  const row = Number(input.dataset.row);
  const col = input.dataset.col;
  const key = input.dataset.tableKey || "";
  if (!col || !Number.isInteger(row)) return;
  if (model === "teacher") {
    if (state.teachers[row]) state.teachers[row][col] = input.value;
  } else if (model === "day") {
    const rows = asArray(state.dayRules[key || state.selectedDayRule]);
    if (rows[row]) rows[row][col] = input.value;
  } else if (model === "academic") {
    const tables = asObject(state.academic?.data?.tables);
    const rows = asArray(tables[key || state.selectedAcademicTable]);
    if (rows[row]) rows[row][col] = input.value;
  }
}

function addBlankRow(kind) {
  if (kind === "teacher") {
    const columns = tableColumns(state.teachers);
    state.teachers.push(Object.fromEntries((columns.length ? columns : ["班级", "学科_1"]).map((col) => [col, ""])));
  } else if (kind === "day") {
    const rows = asArray(state.dayRules[state.selectedDayRule]);
    const columns = tableColumns(rows);
    rows.push(Object.fromEntries((columns.length ? columns : (state.solveMode === "course" ? ({subject_hours: ["学科", "周期课时"], class_overrides: ["班级", "学科", "周期课时"], fixed_slots: ["作用范围", "班级", "星期", "时段", "节次", "学科"], subject_bans: ["学科", "禁排星期", "禁排时段", "节次"]}[state.selectedDayRule] || ["时段节次", "星期一", "星期二", "星期三", "星期四", "星期五"]) : ["时段节次", "星期一", "星期二", "星期三", "星期四", "星期五"])).map((col) => [col, ""])));
    state.dayRules[state.selectedDayRule] = rows;
  } else if (kind === "academic") {
    const tables = asObject(state.academic?.data?.tables);
    const rows = asArray(tables[state.selectedAcademicTable]);
    const columns = tableColumns(rows);
    rows.push(Object.fromEntries((columns.length ? columns : ["名称", "日期", "星期", "说明"]).map((col) => [col, ""])));
    tables[state.selectedAcademicTable] = rows;
    state.academic.data.tables = tables;
  }
  renderShell();
}

async function saveTeachers() {
  await api("/api/teacher-subjects", {
    method: "POST",
    body: {
      rows: state.teachers.map(stripRowIndex),
      source: "base_data.teacher_subjects.save",
      reason: `教师定位表保存 ${state.teachers.length} 行`,
      actor: "web",
    },
  });
  await loadAll({ silent: true });
  toast("教师定位表已保存");
}

async function saveDayRules() {
  const rows = asArray(state.dayRules[state.selectedDayRule]).map(stripRowIndex);
  await api("/api/day-rules", {
    method: "POST",
    body: {
      table: state.selectedDayRule,
      rows,
      source: "base_data.day_rules.save",
      reason: `${DAY_RULE_LABELS[state.selectedDayRule] || state.selectedDayRule} 保存 ${rows.length} 行`,
      actor: "web",
    },
  });
  await loadAll({ silent: true });
  toast("白天规则表已保存");
}

async function saveAcademic() {
  await api("/api/academic-affairs", {
    method: "POST",
    body: {
      academic_affairs: state.academic?.data || {},
      source: "academic_affairs.save",
      reason: `${academicLabel(state.selectedAcademicTable)} 保存`,
      actor: "web",
    },
  });
  await loadAll({ silent: true });
  toast("教务表已保存");
}

function stripRowIndex(row) {
  const next = { ...(row || {}) };
  delete next.row_index;
  return next;
}

async function startSolve(continueFromBest = false) {
  const body = {
    mode: $("solveMode")?.value || state.solveMode || "joint",
    time_limit_seconds: Number($("solveTimeLimit")?.value || 300),
    workers: Number($("solveWorkers")?.value || 8),
    random_seed: $("solveRandomSeed")?.value || "",
    max_keep: Number($("solveMaxKeep")?.value || 10),
    snapshot_interval_sec: Number($("solveSnapshotInterval")?.value || 30),
    enable_snapshots: $("solveEnableSnapshots")?.value === "true",
    continue_from_best: continueFromBest,
    solver_profile: $("solveProfile")?.value || "",
    relative_gap_limit: $("solveRelativeGap")?.value || "",
    absolute_gap_limit: $("solveAbsoluteGap")?.value || "",
  };
  state.solveStatus = await api("/api/solve/start", {
    method: "POST",
    headers: { "Idempotency-Key": createIdempotencyKey() },
    body,
  });
  state.solveJobs = await api("/api/solve/jobs?limit=30").catch(() => state.solveJobs);
  state.solveMode = body.mode;
  updatePolling();
  renderShell();
  toast(continueFromBest ? "已开始继续迭代" : "求解任务已在后台启动");
}

async function pauseSolve() {
  state.solveStatus = await api("/api/solve/pause", { method: "POST", body: {} });
  updatePolling();
  renderShell();
  toast("已请求暂停，系统会导出已捕获候选");
}

async function stopSolve() {
  state.solveStatus = await api("/api/solve/stop", { method: "POST", body: {} });
  updatePolling();
  renderShell();
  toast("已强制停止");
}

async function openRuleEditor(ruleId) {
  const rule = allRules().find((item) => String(item.id || "") === String(ruleId || ""));
  if (!rule) {
    toast("没有找到该规则");
    return;
  }
  const fields = asArray(rule.editor?.fields);
  const body = fields.length ? fields.map(renderRuleField).join("") : `<div class="empty-state">该规则没有可编辑字段。</div>`;
  openModal(
    rule.title || rule.label || rule.name || rule.id || "配置规则",
    `<div class="form-grid" id="ruleEditorFields" data-rule-id="${escapeAttr(rule.id)}">${body}</div>`,
    `<button type="button" class="secondary" data-action="close-modal">取消</button><button type="button" data-action="save-rule-fields">保存配置</button>`
  );
}

function renderRuleField(field, index) {
  const id = `ruleField${index}`;
  const type = field.type || "text";
  const value = field.value ?? "";
  const meta = `data-field-index="${index}" data-field-store="${escapeAttr(field.store || "rules")}" data-field-path="${escapeAttr(field.path || "")}" data-field-type="${escapeAttr(type)}" data-field-label="${escapeAttr(field.label || field.path || "")}"`;
  if (type === "bool" || typeof value === "boolean") {
    return `<label for="${id}">${escapeHtml(field.label || field.path)}</label><select id="${id}" ${meta}><option value="true" ${value ? "selected" : ""}>启用</option><option value="false" ${!value ? "selected" : ""}>关闭</option></select>`;
  }
  if (type === "int" || type === "float" || typeof value === "number") {
    return `<label for="${id}">${escapeHtml(field.label || field.path)}</label><input id="${id}" type="number" value="${escapeAttr(value)}" ${meta}>`;
  }
  if (type === "list" || Array.isArray(value) || type === "checkin_extra_heads") {
    const text = type === "checkin_extra_heads" ? JSON.stringify(value || [], null, 2) : asArray(value).join("、");
    return `<label for="${id}">${escapeHtml(field.label || field.path)}</label><textarea id="${id}" ${meta}>${escapeHtml(text)}</textarea>`;
  }
  const options = asArray(field.options || field.choices);
  if (options.length) {
    return `<label for="${id}">${escapeHtml(field.label || field.path)}</label><select id="${id}" ${meta}>${options.map((option) => `<option value="${escapeAttr(option.value ?? option)}" ${String(option.value ?? option) === String(value) ? "selected" : ""}>${escapeHtml(option.label ?? option.value ?? option)}</option>`).join("")}</select>`;
  }
  return `<label for="${id}">${escapeHtml(field.label || field.path)}</label><input id="${id}" value="${escapeAttr(value)}" ${meta}>`;
}

async function saveRuleFields() {
  const fields = Array.from(document.querySelectorAll("#ruleEditorFields [data-field-path]")).map((node) => ({
    label: node.dataset.fieldLabel,
    store: node.dataset.fieldStore,
    path: node.dataset.fieldPath,
    type: node.dataset.fieldType,
    value: parseRuleFieldValue(node),
  })).filter((field) => field.path);
  await api("/api/rules/configure", {
    method: "POST",
    body: { fields, source: "rules.configure", reason: `规则配置保存 ${fields.length} 项`, actor: "web" },
  });
  closeModal();
  await loadAll({ silent: true });
  toast("规则配置已保存");
}

function parseRuleFieldValue(node) {
  const type = node.dataset.fieldType;
  const raw = node.value;
  if (type === "bool") return raw === "true";
  if (type === "int") return Number.parseInt(raw || "0", 10);
  if (type === "float") return Number.parseFloat(raw || "0");
  if (type === "list") return raw.split(/[\n,，、;；]+/).map((item) => item.trim()).filter(Boolean);
  if (type === "checkin_extra_heads") {
    try {
      return JSON.parse(raw || "[]");
    } catch {
      return raw.split(/\n+/).map((line) => {
        const [name, gender, days] = line.split(/[,，]/).map((part) => part.trim());
        return name ? { name, gender: gender || "", days: days ? days.split(/[、;；]/).filter(Boolean) : [] } : null;
      }).filter(Boolean);
    }
  }
  return raw;
}

function openModal(title, body, actions = "") {
  const root = $("modalRoot");
  root.hidden = false;
  root.innerHTML = `
    <div class="modal" role="dialog" aria-modal="true">
      <div class="modal-head">
        <h2>${escapeHtml(title)}</h2>
        <button type="button" class="secondary" data-action="close-modal">关闭</button>
      </div>
      <div class="modal-body">${body}</div>
      ${actions ? `<div class="card-actions" style="padding:0 18px 18px">${actions}</div>` : ""}
    </div>
  `;
}

function closeModal() {
  const root = $("modalRoot");
  root.hidden = true;
  root.innerHTML = "";
}

async function handleUpload(input) {
  const file = input.files?.[0];
  if (!file) return;
  const form = new FormData();
  form.append("file", file);
  if (input.dataset.upload === "day-rule") {
    form.append("table", state.selectedDayRule);
    const result = await upload("/api/day-rules/import-file", form);
    state.dayRules[result.table || state.selectedDayRule] = asArray(result.rows);
  } else if (input.dataset.upload === "academic") {
    form.append("table", state.selectedAcademicTable);
    const result = await upload("/api/academic-affairs/import-file", form);
    state.academic.data.tables[state.selectedAcademicTable] = asArray(result.rows);
  } else {
    const result = await upload("/api/teacher-subjects/import-file", form);
    state.teachers = asArray(result.rows);
  }
  input.value = "";
  renderShell();
  toast("已解析导入文件，请核对后保存");
}

function download(path) {
  window.location.href = path;
}

async function parseNlRule() {
  const text = $("nlInput")?.value || "";
  const known = state.teachers.flatMap((row) => Object.values(row || {})).map(String).filter((item) => item && item.length <= 12);
  state.parsedRule = await api("/api/nl-rules/parse", { method: "POST", body: { text, known_teachers: Array.from(new Set(known)) } }).then((data) => data.rule || data);
  state.parsedRule.source_text = text;
  renderShell();
  toast("规则草案已生成，请核对后确认");
}

function createIdempotencyKey() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `web-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

async function refreshJobs(silent = false) {
  state.solveJobs = await api("/api/solve/jobs?limit=30");
  state.solveStatus = await api("/api/solve/status").catch(() => state.solveStatus);
  renderShell();
  if (!silent) toast("任务列表已刷新");
}

async function cancelJob(jobId) {
  if (!jobId) throw new Error("缺少任务编号");
  await api(`/api/solve/jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST", body: {} });
  await refreshJobs(true);
  toast("已请求取消任务");
}

async function refreshModelUsage(silent = false) {
  state.modelUsage = await api("/api/model/usage");
  renderShell();
  if (!silent) toast("AI 用量已刷新");
}

async function saveAiSettings() {
  const settings = aiRuleSettings();
  const existing = configuredAiProviders();
  const primary = existing[0] || {};
  const provider = {
    ...primary,
    provider_name: $("aiProviderName")?.value.trim() || "domestic-provider",
    base_url: $("aiBaseUrl")?.value.trim() || "",
    model: $("aiModel")?.value.trim() || "",
    api_key_env: $("aiApiKeyEnv")?.value.trim() || "",
    wire_api: $("aiWireApi")?.value || primary.wire_api || "chat_completions",
    reasoning_effort: $("aiReasoningEffort")?.value || "",
    disable_response_storage: true,
    enabled: $("aiEnabled")?.value === "true",
    priority: Number(primary.priority ?? 10),
    timeout_seconds: Number(primary.timeout_seconds ?? settings.timeout_seconds ?? 30),
    max_completion_tokens: Number(primary.max_completion_tokens ?? settings.max_completion_tokens ?? 2048),
    input_price_microunits_per_million: Number($("aiInputPrice")?.value || 0),
    output_price_microunits_per_million: Number($("aiOutputPrice")?.value || 0),
    circuit_failure_threshold: Number(primary.circuit_failure_threshold ?? 3),
    circuit_cooldown_seconds: Number(primary.circuit_cooldown_seconds ?? 60),
  };
  const enabled = $("aiEnabled")?.value === "true";
  if (enabled && (!provider.base_url || !provider.model || !provider.api_key_env)) {
    throw new Error("启用模型前请填写接口地址、模型和密钥环境变量名");
  }
  if (rule.locked) {
    toast("系统基础规则不可关闭、软化或删除");
    return;
  }
  await api("/api/ai-settings", {
    method: "POST",
    body: { ...settings, enabled, providers: [provider, ...existing.slice(1)] },
  });
  state.aiProviderProbe = null;
  await loadAll({ silent: true });
  toast("AI 模型配置已保存");
}

async function testAiConnection() {
  state.aiProviderProbe = { status: "checking", message: "正在发送真实 JSON 请求…" };
  renderShell();
  try {
    state.aiProviderProbe = await api("/api/ai-settings/test", { method: "POST", body: {} });
  } catch (error) {
    state.aiProviderProbe = {
      status: "unavailable",
      message: error.message || "AI 服务连接失败",
    };
    renderShell();
    throw error;
  }
  renderShell();
  await refreshModelUsage(true);
  toast("AI 服务真实连接验证通过");
}

async function saveModelQuota() {
  const costYuan = Number($("quotaCostYuan")?.value || 0);
  await api("/api/model/quota", {
    method: "POST",
    body: {
      scope_user_id: "",
      request_limit: Number($("quotaRequests")?.value || 0),
      token_limit: Number($("quotaTokens")?.value || 0),
      cost_limit_microunits: Math.max(0, Math.round(costYuan * 1_000_000)),
    },
  });
  await refreshModelUsage(true);
  toast("学校月度配额已保存");
}

async function login(event) {
  event?.preventDefault();
  if (state.loginPending) return;
  state.loginPending = true;
  const submit = $("loginSubmit");
  const errorNode = $("loginError");
  if (submit) {
    submit.disabled = true;
    submit.textContent = "正在登录…";
  }
  if (errorNode) errorNode.hidden = true;
  try {
    state.authSession = await api("/api/auth/login", {
      method: "POST",
      body: {
        username: $("loginUsername")?.value.trim() || "",
        password: $("loginPassword")?.value || "",
      },
    });
    state.accessRole = state.authSession?.user?.role || "viewer";
    state.view = "overview";
    await loadAll();
    if ($("loginPassword")) $("loginPassword").value = "";
    toast("登录成功");
  } catch (error) {
    if (errorNode) {
      errorNode.textContent = error.message || "登录失败";
      errorNode.hidden = false;
    }
  } finally {
    state.loginPending = false;
    if (submit) {
      submit.disabled = false;
      submit.textContent = "登录排课工作台";
    }
  }
}

async function logout() {
  await api("/api/auth/logout", { method: "POST", body: {} });
  clearInterval(state.pollTimer);
  state.pollTimer = null;
  state.authSession = { auth_mode: "required", authenticated: false };
  state.accessContext = null;
  state.solveJobs = { jobs: [], count: 0 };
  state.modelUsage = null;
  renderAuthState();
}

async function applyNlRule(reverse = false) {
  if (!state.parsedRule) await parseNlRule();
  const path = reverse ? "/api/nl-rules/remove" : "/api/nl-rules/add";
  await api(path, { method: "POST", body: { rule: state.parsedRule, confirm: !reverse, actor: "web" } });
  await loadAll({ silent: true });
  toast(reverse ? "规则已移出" : "规则已确认并加入求解");
}

async function runConflicts() {
  state.conflicts = await api("/api/conflicts");
  renderShell();
  toast("冲突检测已完成");
}

async function loadAudit() {
  state.audit = await api("/api/config/audit?limit=30");
  renderShell();
  toast("审计记录已加载");
}

function leaveRepairBody() {
  return {
    teacher: $("leaveRepairTeacher")?.value || "",
    day: $("leaveRepairDay")?.value || "",
    slot: $("leaveRepairSlot")?.value || "",
    class_name: $("leaveRepairClass")?.value || "",
    substitute_teacher: $("leaveRepairSubstitute")?.value || "",
  };
}

async function previewLeaveRepair() {
  state.leaveRepairPreview = await api("/api/academic-affairs/leave-repair/preview", { method: "POST", body: leaveRepairBody() });
  renderShell();
  toast("局部代课方案已生成");
}

async function applyLeaveRepair() {
  const result = await api("/api/academic-affairs/leave-repair/apply", { method: "POST", body: leaveRepairBody() });
  state.leaveRepairPreview = result;
  await refreshSolveStatus(true);
  toast("局部代课已写入当前课表");
}

function manualAdjustmentBody() {
  return {
    class_name: $("manualAdjustClass")?.value || "",
    from_day: $("manualAdjustFromDay")?.value || "",
    from_slot: $("manualAdjustFromSlot")?.value || "",
    to_day: $("manualAdjustToDay")?.value || "",
    to_slot: $("manualAdjustToSlot")?.value || "",
    teacher: $("manualAdjustTeacher")?.value || "",
  };
}

async function previewManualAdjustment() {
  state.manualAdjustmentPreview = await api("/api/academic-affairs/timetable-adjustment/preview", { method: "POST", body: manualAdjustmentBody() });
  renderShell();
  toast("微调影响已生成");
}

async function applyManualAdjustment() {
  state.manualAdjustmentPreview = await api("/api/academic-affairs/timetable-adjustment/apply", { method: "POST", body: manualAdjustmentBody() });
  await refreshSolveStatus(true);
  toast("课表微调已应用");
}

async function handleAction(action, target) {
  const actions = {
    refresh: () => loadAll(),
    logout,
    "refresh-jobs": () => refreshJobs(false),
    "refresh-model-usage": () => refreshModelUsage(false),
    "refresh-results": () => refreshSolveStatus(false),
    "refresh-readiness": async () => {
      state.readiness = await api(`/api/readiness?mode=${encodeURIComponent(state.solveMode || "joint")}`);
      renderShell();
      toast("校验已刷新");
    },
    "save-data-primary": () => state.view === "data" ? saveTeachers() : null,
    "download-teacher-template": () => download("/api/teacher-subjects/template?format=xlsx"),
    "download-teacher-csv-template": () => download("/api/teacher-subjects/template?format=csv"),
    "download-day-template": () => download(`/api/day-rules/template?table=${encodeURIComponent(state.selectedDayRule)}&format=xlsx`),
    "download-academic-template": () => download(`/api/academic-affairs/template?table=${encodeURIComponent(state.selectedAcademicTable)}&format=xlsx`),
    "download-academic-workbook": () => download("/api/academic-affairs/workbook-template"),
    "add-teacher-row": () => addBlankRow("teacher"),
    "add-day-row": () => addBlankRow("day"),
    "add-academic-row": () => addBlankRow("academic"),
    "save-teachers": saveTeachers,
    "save-day-rules": saveDayRules,
    "save-academic": saveAcademic,
    "start-solve": () => startSolve(false),
    "continue-solve": () => startSolve(true),
    "pause-solve": pauseSolve,
    "stop-solve": stopSolve,
    "download-package": () => download("/api/solve/package"),
    "download-file": () => download(`/api/file?path=${encodeURIComponent(target.dataset.path || "")}`),
    "cancel-job": () => cancelJob(target.dataset.jobId),
    "show-more-rules": () => {
      state.ruleLimit += 18;
      renderShell();
    },
    "show-more-files": () => {
      state.fileLimit += 12;
      renderShell();
    },
    "set-rule-mode": () => {
      state.ruleMode = target.dataset.mode || "all";
      renderShell();
    },
    "edit-rule": () => openRuleEditor(target.dataset.ruleId),
    "close-modal": closeModal,
    "save-rule-fields": saveRuleFields,
    "parse-nl-rule": parseNlRule,
    "add-nl-rule": () => applyNlRule(false),
    "remove-nl-rule": () => applyNlRule(true),
    "run-conflicts": runConflicts,
    "load-audit": loadAudit,
    "preview-leave-repair": previewLeaveRepair,
    "apply-leave-repair": applyLeaveRepair,
    "preview-manual-adjustment": previewManualAdjustment,
    "apply-manual-adjustment": applyManualAdjustment,
    "save-ai-settings": saveAiSettings,
    "test-ai-connection": testAiConnection,
    "save-model-quota": saveModelQuota,
  };
  if (actions[action]) await actions[action]();
}

function renderHomeConsole() {
  return `
    <section class="home-console" data-view="home">
      <div class="director-board-body">${renderDirectorBoard()}</div>
      <div id="homeTodoList">待确认名单</div>
      <div id="homeQuickActions">教师定位 规则设置 求解运行 求解结果 教务工作台</div>
      ${renderBellSchedulePanel(state.config?.effective?.calendar || {})}
    </section>
  `;
}

function renderDirectorBoard() {
  const percent = homeProgressPercent(state.readiness?.summary || {});
  return `<strong>主任决策看板</strong><span>${percent}%</span><span>课表风险评估</span><span>建议试运行方案</span>`;
}

function homeProgressPercent(summary = {}) {
  if (summary.can_start_solver) return 100;
  return clamp(100 - (Number(summary.blocking_errors || 0) * 20) - (Number(summary.warnings || 0) * 5), 0, 100);
}

function updateTopClock() {
  const node = $("lastUpdated");
  if (node) node.textContent = `同步于 ${new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}`;
}

function renderBellSchedulePanel(calendar = {}) {
  const periods = asArray(calendar.periods);
  return `
    <section id="bellSchedulePanel" class="card">
      <div class="card-head"><div><h2>作息节次</h2><p>calendar.periods</p></div><button id="saveBellScheduleBtn" type="button">保存</button></div>
      <div class="bell-count-grid">${periods.map((period) => `<span>${escapeHtml(period.label || period.id || period)}</span>`).join("")}</div>
    </section>
  `;
}

async function saveBellSchedule() {
  const payload = { source: "base_data.bell_schedule.save", calendar: { periods: state.config?.effective?.calendar?.periods || [] } };
  await api("/api/config/base-data", { method: "POST", body: payload });
  toast("作息节次已保存");
}

function workbenchReadinessCard(readiness = state.readiness, hardRules = []) {
  const summary = readiness?.summary || {};
  return `<section class="card"><h2>求解前校验</h2><p>${escapeHtml(summary.message || "不代表课表可直接使用")}</p><span>${escapeHtml(hardRules.length)} 条硬规则</span></section>`;
}

function workbenchResultReleaseCard(status = state.solveStatus) {
  const action = resultReleaseAction(status, status?.publish_assessment);
  return `<section class="card"><h2>当前结果</h2>${resultFormalCandidateNotice(status)}${action}</section>`;
}

function resultReleaseAction(status = {}, assessment = null) {
  const deliveryStatus = status?.delivery_status || {};
  const label = deliveryStatus.release_state?.status_label || "结果状态";
  const releaseState = status?.release_state || assessment?.release_state || {};
  const packageLabel = releaseState.package_label || "结果材料";
  const nextAction = releaseState.next_action || "查看剩余差距";
  return `<button id="resultReleaseAction" type="button">${escapeHtml(label)} · ${escapeHtml(packageLabel)} · ${escapeHtml(nextAction)}</button>`;
}

function resultFormalCandidateNotice(status = {}) {
  const candidate = recommendedFormalCandidateSelection(status);
  if (!candidate) return `<div id="resultFormalCandidateNotice" class="result-formal-candidate">当前候选课表继续改善、重新评估剩余差距、收紧目标的顺序复跑</div>`;
  return `<div id="resultFormalCandidateNotice" class="result-formal-candidate">结果页采用质量更好的正式候选：推荐候选文件 ${escapeHtml(candidate.label || candidate.path || "")}，下载将使用推荐的正式候选批次</div>`;
}

function recommendedFormalCandidateSelection(status = {}) {
  const candidates = asArray(status.formal_run_comparison?.recommended_candidates || status.recommended_formal_candidates);
  return candidates[0] || null;
}

function renderWorkbenchSummary() {
  return `${workbenchReadinessCard()}${workbenchResultReleaseCard()}`;
}

function refreshCommercialWorkbenchSummary() {
  renderWorkbenchSummary();
}

function renderRemediationDecisionPoints(option = {}) {
  return `<div class="result-risk-action">${option.action_type === "external_record" ? "走学校既有流程记录" : "人工处理"}</div>`;
}

function parseExtraHeadDays(value) {
  return Array.isArray(value)
    ? value.map(String).filter(Boolean)
    : String(value || "").split(/[、,，\s]+/).map((item) => item.trim()).filter(Boolean);
}

function candidateExtraHeadEntry(candidate) {
  const entry = {
    name: String(candidate?.teacher || candidate?.name || "").trim(),
    gender: String(candidate?.required_gender || candidate?.gender || "").trim(),
  };
  const days = parseExtraHeadDays(candidate?.days || candidate?.day || candidate?.available_days || "");
  if (days.length) entry.days = days;
  return entry;
}

function mergeExtraHeadDraft(originalHeads, draft) {
  const rows = asArray(originalHeads).slice();
  const current = rows.find((item) => item.name === draft.name);
  if (current) {
    current.days = Array.from(new Set([...(current.days || []), ...(draft.days || [])]));
    current.gender = current.gender || draft.gender || "";
  } else {
    rows.push(draft);
  }
  return rows;
}

function renderRemediationCandidateConfig(candidates = []) {
  return `<div class="remediation-candidate-config">${asArray(candidates).map((candidate, index) => {
    const readyToAdd = candidate.status === "ready_to_add";
    return `<div data-extra-head-days="${escapeAttr(parseExtraHeadDays(candidate.days || candidate.day).join(","))}">
      <strong>${readyToAdd ? "确认后试跑" : "确认候选"}</strong>
      <span>${readyToAdd ? "确认后加入晚查寝候选名单，当前结果包仍保持需确认状态。" : "需先确认性别与查寝资格后再试跑；确认无误后保存额外候选名单。"}</span>
      <em>待确认候选草稿 ${index + 1}</em>
    </div>`;
  }).join("")}</div>`;
}

function openExtraHeadsRuleEditor(options = {}) {
  state.pendingExtraHeadDraft = options.draft || null;
  toast("已预填待确认候选草稿");
}

function normalizeExtraHeadsValue(value) {
  return asArray(value).map((item) => ({
    name: item.name || item.teacher || "",
    gender: item.gender || "",
    days: parseExtraHeadDays(item.days || item.day || ""),
  })).filter((item) => item.name);
}

async function applyRemediationCandidate(indexValue, options = {}) {
  const option = state.pendingReadinessRemediation || {};
  const candidates = option.candidate_suggestions || [];
  const index = Number(indexValue);
  const candidate = Number.isInteger(index) ? candidates[index] : null;
  if (!candidate) {
    toast("未找到候选人建议");
    return;
  }
  const scopedEntry = candidateExtraHeadEntry(candidate);
  const readyToAdd = candidate.status === "ready_to_add";
  if (!readyToAdd) {
    openExtraHeadsRuleEditor({
      draft: {
        ...scopedEntry,
        day: candidate.day || "",
        reason: candidate.reason || "",
      },
    });
    toast("已预填候选草稿，确认无误后保存额外候选名单");
    return;
  }
  const shouldStartTrial = Boolean(options.startTrial && readyToAdd);
  const current = normalizeExtraHeadsValue(state.config?.effective?.checkin?.extra_heads || []);
  const next = mergeExtraHeadDraft(current, {
    ...scopedEntry,
    days: [...(scopedEntry.days || [])],
  });
  const result = await api("/api/rules/configure", {
    method: "POST",
    body: {
      fields: [{ label: "额外候选名单", store: "rules", path: "checkin.extra_heads", type: "checkin_extra_heads", value: next }],
      source: "publish.checkin.candidate_suggestion",
      reason: "确认后加入晚查寝候选名单",
    },
  });
  if (state.config) state.config.overrides = result.overrides;
  if (shouldStartTrial) await startCandidateVerificationTrial(candidate);
}

async function startCandidateVerificationTrial(candidate) {
  toast(`确认后试跑：${candidate?.teacher || candidate?.name || "候选人"}`);
}

function saveExtraHeadsDraft(originalHeads, draft, isCandidateReview = false) {
  const value = mergeExtraHeadDraft(originalHeads, draft);
  return api("/api/rules/configure", {
    method: "POST",
    body: {
      fields: [{ label: "额外候选名单", store: "rules", path: "checkin.extra_heads", type: "checkin_extra_heads", value }],
      source: isCandidateReview ? "publish.checkin.candidate_review" : "rules.modal",
    },
  });
}

function renderResultAvailability(status = state.solveStatus) {
  const availability = clientResultAvailability(status);
  return `<section id="resultAvailability" class="result-availability" data-contract="result_availability"><div class="result-availability-primary">${escapeHtml(availability.label)}</div>${renderFileOverflowHint(status)}</section>`;
}

function renderBusinessFloorAdjustedQuality(quality = {}) {
  return `<section class="result-solver-quality" data-contract="business_floor_adjusted_quality"><h3>相对最优与可优化空间</h3><p>当前解牺牲了什么：${escapeHtml(quality.tradeoff || "仍可优化")}</p><strong>尚未确认已无可优化空间</strong><button type="button">更严格的差距目标</button></section>`;
}

function renderPublishGateCandidateRequirements(gate = {}) {
  return `<div class="candidate-requirements"><strong>需补齐候选资料</strong><span>${escapeHtml(gate.capacity_note || "待确认名单不能视为已确认可用人力")}</span></div>`;
}

function renderPublishGateCheckinLedger(gate = {}) {
  return `<section class="checkin-supply-ledger" data-contract="checkin_supply_ledger"><h3>晚查寝供需账本</h3>${renderPublishGateCandidateRequirements(gate)}</section>`;
}

function formatResultNumber(value, fallback = "-") {
  const number = Number(value);
  return Number.isFinite(number) ? number.toLocaleString("zh-CN") : fallback;
}

function formatResultPercent(value) {
  const number = Number(value);
  return Number.isFinite(number) ? `${Math.round(number * 100)}%` : "-";
}

function resultDeliveryStatus(status = {}) {
  return {
    status_snapshot: status.status_snapshot || status.status || "unknown",
    files: prioritizedResultFiles(status),
    release_state: status.release_state || {},
  };
}

function renderResultDeliveryMaterials(status = state.solveStatus) {
  const displayStatus = resultDeliveryStatus(status || {});
  return `<section id="resultDeliveryMaterials" class="result-delivery-materials"><h3>结果材料</h3><p>已生成课表文件、排课结果摘要、课表复盘工作单、结果清单；这些材料用于核对课表例外、候选缺口和后续微调。</p><div class="result-delivery-materials-list">${resultDeliveryMaterialItems(displayStatus).map(renderResultDeliveryMaterialItem).join("")}</div></section>`;
}

function resultDeliveryMaterialItems(displayStatus = {}) {
  const files = asArray(displayStatus.files);
  return files.length ? files : [
    { label: "delivery_manifest.json", path: "delivery_manifest.json" },
    { label: "status.json", path: "status.json" },
    { label: "完整结果包", path: "result_package.zip" },
  ];
}

function renderResultDeliveryMaterialItem(item = {}) {
  return `<a class="result-delivery-material-item" href="/api/file?path=${encodeURIComponent(item.path || "")}">${escapeHtml(item.label || item.path || "结果材料")}</a>`;
}

function normalizeFilePathKey(path = "") {
  return String(path || "").replace(/\\/g, "/").toLowerCase();
}

function clientResultAvailability(status = {}) {
  const files = prioritizedResultFiles(status);
  return {
    label: files.length ? "当前结果：候选课表" : "当前结果：暂无候选课表",
    primary_schedule_files: files.filter((file) => String(file.category || file.path || "").includes("schedule")),
  };
}

function prioritizedResultFiles(status = {}) {
  return asArray(status.primary_schedule_files || status.files).slice().sort((a, b) => normalizeFilePathKey(a.path).localeCompare(normalizeFilePathKey(b.path)));
}

function renderFileOverflowHint(status = {}) {
  const count = asArray(status.files).length;
  return count > 5 ? `<div class="result-file-overflow">另有 ${count - 5} 个文件，可下载完整结果包</div>` : "";
}

function normalizeViewId(viewId = "") {
  const normalized = String(viewId || "").replace(/^#/, "");
  return document.getElementById(viewId)?.classList.contains("view") ? viewId : normalized;
}

function hashViewId(viewId = state.view) {
  return `#${normalizeViewId(viewId || "overview")}`;
}

function syncViewHash(viewId = state.view, method = "replaceState") {
  if (window.history[method]) window.history[method](null, "", hashViewId(viewId));
  if (method !== "pushState" && window.history.pushState) return;
}

function activateInitialView() {
  const viewId = normalizeViewId(window.location.hash || state.view);
  if (VIEW_META[viewId]) state.view = viewId;
}

function installViewHashSync() {
  window.addEventListener("hashchange", () => activateInitialView());
  activateInitialView();
}

function formatRuleSwitchValue(value) {
  return value ? "开启" : "关闭";
}

function formatRuleValue(value) {
  if (value && typeof value === "object" && !Array.isArray(value)) return `已设置 ${Object.keys(value).length} 项`;
  return String(value ?? "").replace(/\bPM1\b/gi, "下午第一节");
}

function renderParsedRuleSummary(result = {}) {
  const rule = result.rule || result;
  return `<div class="parsed-rule-summary"><strong>${escapeHtml(rule.title || "规则影响解释")}</strong><span>${escapeHtml(rule.detail || "规则开关")}</span></div>`;
}

function renderScheduleStatistics(statistics = state.resultPreview?.statistics || {}) {
  const outcome = statistics.outcome || {};
  return `
    <section id="scheduleStatistics" class="schedule-statistics">
      <h2>课表数据驾驶舱</h2>
      <p>求解状态 ${solverStatusLabel(outcome.solverStatus)}</p>
      ${renderScheduleStatBars(statistics)}
      ${renderScheduleLoadList("班级课量", statistics.class_load?.top)}
      ${renderScheduleClassDayLoadList(statistics.class_day_load?.top)}
      ${renderScheduleTeacherDayLoadList(statistics.teacher_day_load?.top)}
      ${renderScheduleTeacherStreakList(statistics.teacher_consecutive_load?.top)}
      ${renderRuleExplain(statistics.rule_explain)}
      ${renderScheduleAdjustmentQueue(statistics.adjustment_suggestions)}
      ${renderScheduleInsights(statistics.insights)}
    </section>
  `;
}

function renderScheduleStatBars(statistics = {}) {
  const metrics = ["subject_distribution", "teacher_load", "teacher_day_balance", "class_day_load_balance", "teacher_day_load_balance", "teacher_consecutive_load"];
  return `<div class="schedule-stat-grid">${metrics.map((key) => `<button type="button" class="schedule-stat-bar" data-stat-preview-kind="${escapeAttr(key)}">${escapeHtml(key)}</button>`).join("")}</div>`;
}

function renderScheduleLoadList(title, items = []) {
  return `<div class="schedule-stat-load"><button type="button">${escapeHtml(title)}</button>${asArray(items).map((item) => `<span>${escapeHtml(item.label || item.class_name || item.teacher || "")}</span>`).join("")}</div>`;
}

function renderScheduleClassDayLoadList(items = []) {
  return `<div class="schedule-stat-load"><strong>班级日课量</strong>${asArray(items).map((item) => `<button type="button" data-schedule-adjustment="${escapeAttr(item.id || "")}" data-schedule-adjustment-label="${escapeAttr(item.label || "班级：")}">班级：${escapeHtml(item.class_name || item.label || "")}</button>`).join("")}</div>`;
}

function renderScheduleTeacherDayLoadList(items = []) {
  return `<div class="schedule-stat-load"><strong>教师日负荷</strong>${asArray(items).map((item) => `<button type="button">教师：${escapeHtml(item.teacher || item.label || "")}</button>`).join("")}</div>`;
}

function renderScheduleTeacherStreakList(items = []) {
  return `<div class="schedule-stat-load"><strong>连续课风险</strong>${asArray(items).map((item) => `<button type="button" data-consecutive-adjustment="${escapeAttr(item.id || "")}">${escapeHtml(item.teacher || item.label || "")}</button>`).join("")}</div>`;
}

function renderScheduleInsights(insights = []) {
  return `<section class="schedule-insight-board"><h3>课表健康洞察</h3><div class="schedule-insight-list">${asArray(insights).map((item) => `<div>${escapeHtml(item.title || "课表风险")}${renderInsightRelated(item)}</div>`).join("")}</div></section>`;
}

function renderInsightRelated(insight = {}) {
  return `<div class="schedule-insight-related"><button type="button" data-insight-preview-kind="${escapeAttr(insight.preview_kind || "")}" data-insight-preview-name="${escapeAttr(insight.preview_name || "")}">打开课表在线预览</button></div>`;
}

function openPreviewFromInsight(insight = {}) {
  state.resultPreviewKind = insight.preview_kind || "class";
  state.resultPreviewItem = insight.preview_name || "";
  state.view = "results";
  renderShell();
}

function renderScheduleAdjustmentQueue(items = []) {
  return `<section class="schedule-adjustment-board"><h3>可执行微调建议</h3><div class="schedule-adjustment-list">${asArray(items).map(renderScheduleAdjustmentSuggestion).join("")}</div></section>`;
}

function renderScheduleAdjustmentSuggestion(item = {}) {
  return `<button type="button" class="schedule-adjustment-item" data-schedule-adjustment="${escapeAttr(item.id || "")}" data-schedule-adjustment-label="${escapeAttr(item.label || item.title || "")}">${escapeHtml(item.title || "教师日负荷均衡")}</button>`;
}

function renderRuleExplain(explain = {}) {
  return `<section class="rule-explain-board"><h3>规则影响解释</h3><div class="rule-explain-list">${asArray(explain.items).map(renderRuleExplainItem).join("")}</div>${renderRuleExplainExamples(explain.examples)}</section>`;
}

function renderRuleExplainItem(item = {}) {
  return `<div class="rule-explain-item"><strong>${escapeHtml(ruleExplainEntityLabel(item.entity || "全局规则"))}</strong><span>${escapeHtml(ruleExplainEventLabel(item.event || "规则开关"))}</span></div>`;
}

function renderRuleExplainExamples(examples = []) {
  return `<div class="rule-explain-examples"><strong>影响样例</strong><span>值班前连续课限制</span><span>晚查寝安排</span><span>语文外语下午第二节偏好权重</span>${asArray(examples).map((item) => `<span>${escapeHtml(item.label || item)}</span>`).join("")}</div>`;
}

function ruleExplainEntityLabel(entity) {
  return ({ global: "全局规则", checkin: "晚查寝安排" }[entity] || entity || "全局规则");
}

function ruleExplainEventLabel(event) {
  return ({ toggle: "规则开关", conflict: "课表风险" }[event] || event || "规则开关");
}

function renderScheduleVersions(versions = state.resultPreview?.schedule_versions || []) {
  return `<section id="scheduleVersions" class="schedule-versions"><h2>课表版本时间线</h2><div class="schedule-version-list">${asArray(versions).map(renderScheduleVersionItem).join("")}</div></section>`;
}

function renderScheduleVersionItem(item = {}) {
  return `<div class="schedule-version-item"><strong>${escapeHtml(item.title || item.version || "当前版本")}</strong><div class="schedule-version-changes">changed_cell_count: ${formatResultNumber(item.changed_cell_count || 0)}</div></div>`;
}

function renderQualityPlanNextStep(plan = {}) {
  return `<div class="quality-plan-next-step">下一轮会换新搜索起点：${escapeHtml(plan.next_seed || "自动选择")}</div>`;
}

function downloadAcademicTemplate(format = "xlsx") {
  return download(`/api/academic-affairs/template?table=${encodeURIComponent(state.selectedAcademicTable)}&format=${format}`);
}

function downloadAcademicWorkbookTemplate() {
  return download("/api/academic-affairs/workbook-template?format=xlsx");
}

function downloadTeacherCsvTemplate(format = "csv") {
  return download(`/api/teacher-subjects/template?format=${format}`);
}

async function importTeacherFile(file) {
  const form = new FormData();
  if (file) form.append("file", file);
  const result = await fetch("/api/teacher-subjects/import-file", { method: "POST", body: form, headers: accessHeaders() });
  $("teacherImportNotice") && ($("teacherImportNotice").textContent = "尚未保存，保存后才会进入正式配置");
  return result;
}

function downloadDayRuleTemplate(format = "xlsx") {
  return download(`/api/day-rules/template?table=${encodeURIComponent(state.selectedDayRule)}&format=${format}`);
}

async function importDayRuleFile(file) {
  const form = new FormData();
  if (file) form.append("file", file);
  const result = await fetch("/api/day-rules/import-file", { method: "POST", body: form, headers: accessHeaders() });
  $("dayRuleImportNotice") && ($("dayRuleImportNotice").textContent = "persisted False");
  return result;
}

async function importAcademicFile(file) {
  const form = new FormData();
  if (file) form.append("file", file);
  const result = await fetch("/api/academic-affairs/import-file", { method: "POST", body: form, headers: accessHeaders() });
  await refreshAcademicPreview();
  return result;
}

async function importAcademicWorkbook(file) {
  const form = new FormData();
  if (file) form.append("file", file);
  const result = await fetch("/api/academic-affairs/import-workbook", { method: "POST", body: form, headers: accessHeaders() });
  $("academicWorkbookImportNotice") && ($("academicWorkbookImportNotice").innerHTML = buildAcademicWorkbookImportImpact({ table_count: 0, row_count: 0, persisted: "False" }));
  await refreshAcademicPreview();
  return result;
}

function buildAcademicWorkbookImportImpact(summary = {}) {
  return `<div class="academic-import-impact"><strong>全量工作簿导入汇总</strong><span>风险变化 ${formatSignedDelta(summary.risk_delta || 0)}</span><span>${formatResultNumber(summary.table_count)} 表 ${formatResultNumber(summary.row_count)} 行，尚未保存，保存后才会进入正式配置</span></div>`;
}

function formatSignedDelta(value) {
  const number = Number(value || 0);
  return `${number >= 0 ? "+" : ""}${number}`;
}

async function importAcademicCsv(file) {
  return importAcademicFile(file);
}

async function refreshAcademicPreview() {
  return api("/api/academic-affairs/preview", { method: "POST", body: { table: state.selectedAcademicTable, rows: state.academic?.data?.tables?.[state.selectedAcademicTable] || [] } });
}

function formatAuditChangeValue(value) {
  if (value && typeof value === "object") return `已设置 ${Object.keys(value).length} 项`;
  return String(value ?? "");
}

function renderTableForAudit(rows, options = { hiddenColumns: ["row_index"] }) {
  const hiddenColumns = new Set(options.hiddenColumns || ["row_index"]);
  return asArray(rows).map((row) => Object.keys(row).filter((key) => !hiddenColumns.has(key)).join(",")).join("\n");
}

function dayRuleTableLabel(tableKey = state.selectedDayRule) {
  return DAY_RULE_LABELS[tableKey] || tableKey;
}

function manualAdjustmentRequestBody() {
  return {
    class_name: $("manualAdjustClass")?.value || "",
    change_id: $("manualAdjustmentChange")?.value || "",
    source: "micro_adjustment",
  };
}

function prefillManualAdjustmentFromScheduleSuggestion(suggestion = {}) {
  state.manualAdjustmentDraft = { type: "class_day_load_balance", ...suggestion };
}

function prefillManualAdjustmentFromConsecutiveSuggestion(suggestion = {}) {
  state.manualAdjustmentDraft = { type: "teacher_consecutive_load", ...suggestion };
}

function renderManualAdjustmentClassSchedule(schedule = []) {
  return `<div class="timetable-adjustment-plan">${asArray(schedule).map((item) => `<span>${escapeHtml(item.subject || item)}</span>`).join("")}</div>`;
}

async function previewManualTimetableAdjustment() {
  return api("/api/academic-affairs/timetable-adjustment/preview", { method: "POST", body: manualAdjustmentRequestBody() });
}

async function applyManualTimetableAdjustment() {
  return api("/api/academic-affairs/timetable-adjustment/apply", { method: "POST", body: manualAdjustmentRequestBody() });
}

function leaveRepairHasSource(body = {}) {
  return Boolean(body.log_id || (body.teacher && body.day && body.slot));
}

function syncLeaveRepairFieldsFromLog(log = {}) {
  const teacher = log.teacher || "";
  const day = log.day || "";
  const slot = log.slot || "";
  const body = {};
  body.teacher = teacher;
  body.day = day;
  body.slot = slot;
  return body;
}

function renderLeaveRepairCandidateMatrix(repair = {}) {
  return `<section class="leave-repair-candidates"><h3>代课候选影响矩阵</h3><p>选择请假日志，或直接填写请假教师、星期和节次</p>${asArray(repair.candidate_options).map(renderLeaveRepairCandidateOption).join("")}</section>`;
}

function renderLeaveRepairCandidateOption(option = {}) {
  return `<button type="button" class="leave-repair-candidate"><strong>${escapeHtml(option.teacher || "系统推荐")}</strong><span class="leave-repair-candidate-impact">${escapeHtml(option.impact || "repair.candidate_options")}</span></button>`;
}

async function previewLeaveSubstitutionRepair(body = syncLeaveRepairFieldsFromLog({})) {
  return api("/api/academic-affairs/leave-repair/preview", { method: "POST", body });
}

async function applyLeaveSubstitutionRepair(body = syncLeaveRepairFieldsFromLog({})) {
  return api("/api/academic-affairs/leave-repair/apply", { method: "POST", body });
}

if ($("scheduleStatistics")) {
  $("scheduleStatistics").addEventListener("click", (event) => {
    const stat = event.target.closest("[data-stat-preview-kind]");
    if (stat) {
      state.resultPreviewKind = stat.dataset.statPreviewKind || "class";
      renderShell();
    }
  });
}

document.addEventListener("click", (event) => {
  const jump = event.target.closest("[data-view-jump]");
  if (jump) {
    state.view = jump.dataset.viewJump;
    renderShell();
    return;
  }
  const nav = event.target.closest("[data-view]");
  if (nav && nav.classList.contains("nav-item")) {
    state.view = nav.dataset.view;
    renderShell();
    return;
  }
  const action = event.target.closest("[data-action]");
  if (!action) return;
  event.preventDefault();
  handleAction(action.dataset.action, action).catch((err) => toast(err.message));
});

document.addEventListener("input", (event) => {
  const input = event.target;
  if (input.matches("[data-edit-model]")) {
    updateEditableModel(input);
  }
  if (input.matches("[data-control='rule-search']")) {
    state.ruleSearch = input.value;
    state.ruleLimit = 18;
    renderShell();
  }
});

document.addEventListener("change", (event) => {
  const input = event.target;
  if (input.matches("[data-upload]")) {
    handleUpload(input).catch((err) => toast(err.message));
  } else if (input.matches("[data-control='day-rule-picker']")) {
    state.selectedDayRule = input.value;
    renderShell();
  } else if (input.matches("[data-control='academic-picker']")) {
    state.selectedAcademicTable = input.value;
    renderShell();
  } else if (input.matches("[data-control='solve-mode']")) {
    state.solveMode = input.value;
    loadAll({ silent: true }).catch((err) => toast(err.message));
  } else if (input.matches("[data-control='preview-kind']")) {
    state.resultPreviewKind = input.value;
    state.resultPreviewItem = "";
    renderShell();
  } else if (input.matches("[data-control='preview-item']")) {
    state.resultPreviewItem = input.value;
    renderShell();
  }
});

$("accessRoleSelect").value = state.accessRole;
$("accessRoleSelect").addEventListener("change", () => {
  if (authIsRequired()) return;
  state.accessRole = $("accessRoleSelect").value || "academic_admin";
  saveStored("scheduler.accessRole", state.accessRole);
  loadAll().then(() => toast("工作身份已切换")).catch((err) => toast(err.message));
});

$("loginForm").addEventListener("submit", login);

$("modalRoot").addEventListener("click", (event) => {
  if (event.target === $("modalRoot")) closeModal();
});

async function bootstrap() {
  renderAuthState();
  try {
    state.authSession = await api("/api/auth/session");
    if (authIsRequired() && state.authSession?.authenticated) {
      state.accessRole = state.authSession.user?.role || "viewer";
    }
    if (!renderAuthState()) {
      $("loginUsername")?.focus();
      return;
    }
    await loadAll();
  } catch (error) {
    state.loading = false;
    state.authSession = state.authSession || { auth_mode: "required", authenticated: false };
    renderAuthState();
    const errorNode = $("loginError");
    if (errorNode && !isAuthenticated()) {
      errorNode.textContent = `无法连接排课服务：${error.message}`;
      errorNode.hidden = false;
    } else {
      renderShell();
      toast(error.message);
    }
  }
}

bootstrap();

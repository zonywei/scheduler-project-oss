/* Formal product surface for education-office users. */

VIEW_META.overview = ["排课项目", "排课项目计划", "按正式流程完成基础设置、规则设置、智能排课、审查优化与发布。"];
VIEW_META.data = ["第 1 阶段", "基础设置", "先定义学期作息，再导入教师定位表并设置各年级学科课时。"];
VIEW_META.rules = ["第 2 阶段", "规则中心", "用列表、课表或 AI 助手设置学校规则，确认后再进入排课。"];
VIEW_META.solve = ["第 3–4 阶段", "AI 智能排课", "AI 审查规则与阻断原因，工业级智能排课引擎负责寻找可行方案和全局优化。"];
VIEW_META.results = ["第 5 阶段", "课表发布", "由当前用户确认版本与生效范围，并按 PDF 或 Excel 下载留档。"];

ACTION_PERMISSIONS["save-foundation-step"] = "base_data.write";
ACTION_PERMISSIONS["next-foundation-step"] = "base_data.write";
ACTION_PERMISSIONS["parse-rule-v2"] = "model.use";
ACTION_PERMISSIONS["save-rule-v2"] = "rules.write";
ACTION_PERMISSIONS["activate-rule-v2"] = "rules.write";
ACTION_PERMISSIONS["toggle-rule-v2"] = "rules.write";
ACTION_PERMISSIONS["delete-rule-v2"] = "rules.write";
ACTION_PERMISSIONS["save-rule-v2-editor"] = "rules.write";
ACTION_PERMISSIONS["parse-optimization-rule"] = "model.use";
ACTION_PERMISSIONS["refresh-ai-block-review"] = "model.use";
ACTION_PERMISSIONS["confirm-rule-and-optimize"] = "solve.run";
ACTION_PERMISSIONS["publish-candidate"] = "schedule.publish";

const FORMAL_STAGE_DEFS = [
  { id: "foundation", label: "基础设置", view: "data", detail: "作息与基础数据" },
  { id: "rules", label: "规则设置", view: "rules", detail: "默认规则与个性化要求" },
  { id: "solve", label: "AI智能排课", view: "solve", detail: "工业级全局求解" },
  { id: "review", label: "方案审查与优化", view: "solve", detail: "比较、解释与调整" },
  { id: "publish", label: "课表发布", view: "results", detail: "确认、下载与留痕" },
];

const FORMAL_FOUNDATION_STEPS = [
  { id: "calendar", label: "学期日历与作息", table: "time_grid" },
  { id: "teachers", label: "教师定位表", table: "teachers" },
  { id: "hours", label: "年级学科课时", table: "subject_hours" },
  { id: "fixed", label: "场地与固定事项", table: "fixed_slots" },
];

const FORMAL_GUIDE_STORAGE_KEY = "scheduler.eduOnboarding.v1.completed";
const FORMAL_FOUNDATION_GUIDANCE = {
  calendar: {
    task: "先确认本学期什么时候可以排课",
    prepare: "校历、日常作息与周末安排",
    done: "上课日、节次和固定公休都已确认",
  },
  teachers: {
    task: "导入并核对教师定位表",
    prepare: "班级、班主任和各学科任课教师表",
    done: "每个班级都能找到对应任课教师",
  },
  hours: {
    task: "确认各年级各学科每周课时",
    prepare: "课程方案或本学期课时标准",
    done: "每个年级学科都有明确周课时",
  },
  fixed: {
    task: "补充不能移动的场地和固定事项",
    prepare: "升旗、教研、活动、场地占用等安排",
    done: "已录入所有不可冲突的固定时间",
  },
};

state.formalRuleExamplesOpen = Boolean(state.formalRuleExamplesOpen);
var formalGuideReturnFocus = null;

function formalMarkGuideSeen() {
  try {
    localStorage.setItem(FORMAL_GUIDE_STORAGE_KEY, "1");
  } catch (_) {
  }
}

function formalPageHintData(kind) {
  let guide;
  if (kind === "foundation") {
    guide = FORMAL_FOUNDATION_GUIDANCE[state.foundationStep] || FORMAL_FOUNDATION_GUIDANCE.calendar;
  } else if (kind === "rules") {
    guide = {
      task: "先说一句本校自己的排课规则",
      prepare: "特殊要求、作用范围、作用时间和例外",
      done: "规则草案已检查并由教务确认",
    };
  } else if (kind === "solve") {
    const blockers = Number(state.readiness?.summary?.blocking_errors || 0);
    guide = blockers ? {
      task: `先处理 ${blockers} 个必须处理项，再启动排课`,
      prepare: "打开“阻断审查”，查看现有局限和解决建议",
      done: "“启动 AI 智能排课”按钮可以点击",
    } : {
      task: "启动一次工业级智能排课",
      prepare: "已确认的基础数据和规则版本",
      done: "求解状态显示完成并生成候选课表",
    };
  } else if (kind === "review") {
    guide = {
      task: "先审查推荐方案，再告诉 AI 想怎么调整",
      prepare: "重点关注硬冲突、教师负担和班级体验",
      done: "确认一版可以进入发布的候选课表",
    };
  } else {
    guide = {
      task: "确认版本、生效范围和发布门禁",
      prepare: "最终候选课表与生效范围",
      done: "课表已按所选格式下载并留下版本记录",
    };
  }
  return guide;
}

function formalCurrentPageHintKind() {
  if (state.view === "overview") return formalOverviewNext()?.stage?.id || "foundation";
  if (state.view === "data") return "foundation";
  if (state.view === "rules") return "rules";
  if (state.view === "solve") {
    if (state.formalSolveSection === "blockers") return "solve";
    if (state.formalSolveSection === "optimization") return "review";
    return formalHasUsableSchedule() && !isRunningStatus() ? "review" : "solve";
  }
  if (state.view === "results") return "publish";
  return "rules";
}

function formalOpenPageHint() {
  const root = $("modalRoot");
  if (!root) return;
  const guide = formalPageHintData(formalCurrentPageHintKind());
  formalGuideReturnFocus = document.activeElement;
  root.hidden = false;
  root.innerHTML = `<div class="formal-page-hint-modal" role="dialog" aria-modal="true" aria-labelledby="formalPageHintTitle">
    <header><span>本页提示</span><h2 id="formalPageHintTitle">${escapeHtml(guide.task)}</h2></header>
    <dl><div><dt>开始前准备</dt><dd>${escapeHtml(guide.prepare)}</dd></div><div><dt>做到这里算完成</dt><dd>${escapeHtml(guide.done)}</dd></div></dl>
    <footer><button type="button" class="secondary" data-action="open-full-guide-from-hint">查看完整操作指南</button><button id="formalPageHintClose" type="button" data-action="close-page-hint">知道了</button></footer>
  </div>`;
  requestAnimationFrame(() => $("formalPageHintClose")?.focus());
}

function formalOpenLoginHelp() {
  formalGuideReturnFocus = document.activeElement;
  openModal(
    "登录帮助",
    `<div class="login-help-content"><p>使用管理员分配的账号和密码登录。</p><p>忘记密码或账号无法使用时，请联系本校系统管理员重置。</p></div>`,
  );
  requestAnimationFrame(() => $("modalRoot")?.querySelector("[data-action='close-modal']")?.focus());
}

function formalGuideSteps() {
  const stageStates = formalStageState();
  return [
    {
      id: "foundation",
      title: "准备基础数据",
      prepare: "校历作息、教师定位表、各年级学科课时",
      action: "设置学期、公休和每天节次，导入教师定位，补齐课时与固定事项",
      done: "基础设置的 4 项都已核对",
      view: "data",
    },
    {
      id: "rules",
      title: "确认学校排课规则",
      prepare: "默认规则、全校统一要求和个别特殊安排",
      action: "先核对规则集，也可在课表中点选禁排时间，或让 AI 助手整理复杂要求",
      done: "规则草案已由教务确认并加入求解",
      view: "rules",
    },
    {
      id: "solve",
      title: "启动 AI 智能排课",
      prepare: "通过排课前检查的数据和规则版本",
      action: "在阻断审查中处理现有局限，再点击启动并观察后台求解状态",
      done: "工业级求解引擎生成无硬冲突候选",
      view: "solve",
    },
    {
      id: "review",
      title: "审查并优化方案",
      prepare: "候选课表、冲突证据和教师负担指标",
      action: "自然语言描述问题或新增规则，确认后重新优化",
      done: "选定一版可发布候选课表",
      view: "solve",
    },
    {
      id: "publish",
      title: "确认并发布课表",
      prepare: "最终版本、生效日期和下载格式",
      action: "检查发布门禁，由当前用户确认范围并下载 PDF 或 Excel",
      done: "发布记录、版本和结果材料完整留存",
      view: "results",
    },
  ].map((step) => ({ ...step, completed: Boolean(stageStates[step.id]?.completed) }));
}

function formalOpenUserGuide(source = "manual") {
  const root = $("modalRoot");
  if (!root) return;
  formalGuideReturnFocus = source === "manual" ? document.activeElement : $("openGuideBtn");
  const steps = formalGuideSteps();
  root.hidden = false;
  root.innerHTML = `<div class="formal-guide-modal" role="dialog" aria-modal="true" aria-labelledby="formalGuideTitle">
    <header class="formal-guide-head">
      <div><span>首次排课引导 · 约 2 分钟</span><h2 id="formalGuideTitle">不用懂算法，按这 5 个阶段完成排课</h2><p>每个页面都会告诉你需要准备什么、现在做什么、做到哪里算完成。</p></div>
      <button type="button" class="secondary" data-action="close-user-guide">稍后再看</button>
    </header>
    <div class="formal-guide-intro"><strong>记住一条就够了：</strong><span>基础数据先准备，个性化规则交给 AI 整理，工业级求解完成排课，最后由教务审查并发布。</span></div>
    <ol class="formal-guide-steps">${steps.map((step, index) => `<li class="${step.completed ? "completed" : ""}">
      <b>${step.completed ? "已完成" : index + 1}</b>
      <div class="formal-guide-step-copy"><h3>${escapeHtml(step.title)}</h3><p><span>准备</span>${escapeHtml(step.prepare)}</p><p><span>操作</span>${escapeHtml(step.action)}</p><p><span>完成标志</span>${escapeHtml(step.done)}</p></div>
      <button type="button" class="secondary" data-action="go-guide-stage" data-view="${escapeAttr(step.view)}" data-stage="${escapeAttr(step.id)}">${step.completed ? "回看" : "去完成"}</button>
    </li>`).join("")}</ol>
    <footer class="formal-guide-actions"><p>关闭后可随时从左侧“操作指南”重新打开。</p><div><button type="button" class="secondary" data-action="dismiss-user-guide">我已了解</button><button id="formalGuideStart" type="button" data-action="start-user-guide">从第 1 步开始</button></div></footer>
  </div>`;
  requestAnimationFrame(() => $("formalGuideStart")?.focus());
}

function formalCloseUserGuide() {
  closeModal();
  const focusTarget = formalGuideReturnFocus;
  formalGuideReturnFocus = null;
  requestAnimationFrame(() => focusTarget?.focus?.());
}

function formalHasUsableSchedule() {
  const preview = state.resultPreview || {};
  const summary = preview.summary || {};
  const availability = preview.availability || {};
  return Boolean(
    Number(summary.schedule_files || availability.schedule_file_count || 0)
    || preview.has_schedule
    || asArray(preview.workbooks).length
    || asArray(preview.class_views).length
    || asArray(preview.teacher_views).length
  );
}

function formalFocusActiveWorkflow() {
  if (window.innerWidth > 760) return;
  const workflow = document.querySelector(".formal-workflow-track");
  const active = workflow?.querySelector(".formal-workflow-step.active");
  if (!workflow || !active || workflow.scrollWidth <= workflow.clientWidth) return;
  workflow.scrollLeft = Math.max(0, active.offsetLeft - ((workflow.clientWidth - active.clientWidth) / 2));
}

function formalFocusActiveNav() {
  if (window.innerWidth > 760) {
    const desktopNav = document.querySelector(".nav-list");
    if (desktopNav) desktopNav.scrollTop = 0;
    return;
  }
  const nav = document.querySelector(".nav-list");
  const active = nav?.querySelector(".nav-item.active, .nav-item.is-active");
  if (nav && active && nav.scrollWidth > nav.clientWidth) {
    nav.scrollLeft = Math.max(0, active.offsetLeft + active.offsetWidth - nav.clientWidth + 18);
  }
  const rail = document.querySelector(".rail");
  if (rail) rail.scrollLeft = 0;
}

const formalLegacyRenderShell = renderShell;
renderShell = function renderShellFormal() {
  formalLegacyRenderShell();
  requestAnimationFrame(() => {
    formalFocusActiveWorkflow();
    formalFocusActiveNav();
    formalMaybeOpenBlockerNotice();
  });
};

renderTopStatus = function renderTopStatusFormal() {
  const badge = $("globalRunBadge");
  const projectLabel = document.querySelector(".project-label");
  const status = state.solveStatus || {};
  const readiness = state.readiness?.summary || {};
  const running = isRunningStatus(status);
  const usable = formalHasUsableSchedule();
  const completedButUnverified = String(status.status || "") === "completed" && !usable;
  const failed = String(status.status || "") === "failed";
  const tone = failed ? "error" : running || completedButUnverified ? "warning" : usable || readiness.can_start_solver ? "ok" : "warning";
  badge.className = `run-badge ${tone}`;
  badge.textContent = failed ? "排课未完成" : running ? "正在排课" : usable ? "结果已生成" : completedButUnverified ? "结果待核验" : readiness.can_start_solver ? "可以开始" : "有待办";
  if (projectLabel) projectLabel.textContent = `${formalCurrentProjectSettings().term_name}排课`;
};

function formalStageState() {
  const apiStages = asArray(state.projectState?.stages);
  const byId = Object.fromEntries(apiStages.map((item) => [item.id, item]));
  const readiness = state.readiness?.summary || {};
  const status = state.solveStatus || {};
  const published = Boolean(state.projectState?.publish?.current);
  const fallback = {
    foundation: Boolean(state.teachers.length && dayRuleTotal()),
    rules: Boolean(state.rulesV2?.summary?.active || readiness.can_start_solver),
    solve: String(status.status || "") === "completed" && formalHasUsableSchedule(),
    review: formalHasUsableSchedule(),
    publish: published,
  };
  return Object.fromEntries(FORMAL_STAGE_DEFS.map((item) => [item.id, {
    ...item,
    completed: byId[item.id]?.completed ?? fallback[item.id],
  }]));
}

function formalCurrentStageId() {
  if (state.view === "data") return "foundation";
  if (state.view === "rules") return "rules";
  if (state.view === "results") return "publish";
  if (state.view === "solve" && formalHasUsableSchedule() && !isRunningStatus()) return "review";
  if (state.view === "solve") return "solve";
  const phase = String(state.projectState?.phase || "");
  return FORMAL_STAGE_DEFS.some((item) => item.id === phase) ? phase : "foundation";
}

function formalWorkflow(currentId = formalCurrentStageId()) {
  const states = formalStageState();
  const solveStatus = state.solveStatus || {};
  const activeIndex = Math.max(0, FORMAL_STAGE_DEFS.findIndex((step) => step.id === currentId));
  const activeStage = FORMAL_STAGE_DEFS[activeIndex];
  const solveTimeline = asArray(solveStatus.phase_timeline);
  const solvePhaseIndex = Math.max(0, solveTimeline.findIndex((item) => ["active", "failed"].includes(String(item.status || ""))));
  const hasSolveProgress = currentId === "solve" && (isRunningStatus(solveStatus) || String(solveStatus.status || "") === "failed") && solveTimeline.length;
  const overallProgress = hasSolveProgress
    ? Math.round(((activeIndex + ((solvePhaseIndex + 1) / solveTimeline.length)) / FORMAL_STAGE_DEFS.length) * 100)
    : Math.round(((activeIndex + 1) / FORMAL_STAGE_DEFS.length) * 100);
  const failed = String(solveStatus.status || "") === "failed";
  const workflowDetail = hasSolveProgress
    ? `${failed ? "停在" : "当前"}：${solveTimeline[solvePhaseIndex]?.label || solveStatus.phase_label || "求解中"}`
    : "";
  return `<section class="formal-workflow ${failed && currentId === "solve" ? "has-error" : ""}" aria-label="正式排课流程">
    <div class="formal-workflow-summary">
      <div class="formal-workflow-summary-main"><span>当前流程</span><strong>第 ${activeIndex + 1} / ${FORMAL_STAGE_DEFS.length} 阶段 · ${escapeHtml(activeStage.label)}</strong>${workflowDetail ? `<em>${escapeHtml(workflowDetail)}</em>` : ""}</div>
      <div class="formal-workflow-summary-progress">${hasSolveProgress ? `<span class="formal-workflow-clock">已用时 ${solveClockMarkup(solveStatus)}</span>` : ""}<span>流程阶段进度 ${overallProgress}%</span><progress max="100" value="${overallProgress}" aria-label="流程阶段进度 ${overallProgress}%"></progress></div>
    </div>
    <div class="formal-workflow-track">${FORMAL_STAGE_DEFS.map((step, index) => {
    const done = Boolean(states[step.id]?.completed);
    const active = step.id === currentId;
    return `<button type="button" class="formal-workflow-step ${done ? "done" : ""} ${active ? "active" : ""}" data-view-jump="${escapeAttr(step.view)}" ${active ? 'aria-current="step"' : ""}>
      <b class="formal-step-number">${done && !active ? "✓" : index + 1}</b>
      <strong>${escapeHtml(step.label)}</strong>
      <span>${escapeHtml(active ? (step.id === "solve" && failed ? "未完成" : step.id === "solve" && isRunningStatus() ? "运行中" : "进行中") : done ? "已完成" : step.detail)}</span>
    </button>`;
  }).join("")}</div></section>`;
}

renderWorkflowStepper = function renderWorkflowStepperFormal() {
  return formalWorkflow();
};

renderPageActions = function renderPageActionsFormal() {
  const actions = $("pageActions");
  if (!actions) return;
  actions.innerHTML = ["data", "rules", "solve", "results"].includes(state.view)
    ? `<button type="button" class="secondary formal-hint-button" data-action="open-page-hint">本页提示</button>`
    : "";
};

function formalStageStatusLabel(done, active = false) {
  if (active) return ["进行中", "warning"];
  if (done) return ["已完成", "ok"];
  return ["未开始", "info"];
}

function formalOverviewNext() {
  const stages = formalStageState();
  if (isRunningStatus()) return { stage: stages.solve, title: state.solveStatus?.phase_label || "工业级求解引擎正在运行", message: state.solveStatus?.message || "可以离开当前页面，后台任务不会中断。" };
  if (formalHasUsableSchedule() && !stages.publish.completed) return { stage: stages.review, title: "先审查候选课表，再决定是否继续优化", message: "查看硬规则冲突、软规则代价与教务风险，也可以用自然语言告诉 AI 想怎样调整。" };
  return { stage: FORMAL_STAGE_DEFS.map((item) => stages[item.id]).find((item) => !item.completed) || stages.publish, title: "继续完成当前排课阶段", message: "系统只展示此刻最需要教务处理的一件事。" };
}

function formalOverviewTask(next) {
  if (isRunningStatus()) return {
    title: next.title,
    message: next.message,
    time: "后台运行",
    prepare: "无需停留在本页",
    done: "出现候选课表",
    action: "查看求解状态",
  };
  const blockers = Number(state.readiness?.summary?.blocking_errors || 0);
  const tasks = {
    foundation: {
      title: "先完成基础设置，系统才能开始排课",
      message: "从学期作息开始，再依次核对教师定位、学科课时和固定事项。",
      time: "约 15–30 分钟",
      prepare: "校历、教师定位表、课时标准",
      done: "基础设置 4 项完成",
      action: "从设置作息开始",
    },
    rules: {
      title: "现在做：告诉 AI 本校特殊排课要求",
      message: "不用先读完所有系统规则。先用一句话描述学校自己的要求，AI 会生成可编辑草案。",
      time: "约 5–10 分钟",
      prepare: "特殊要求、例外和作用时间",
      done: "规则已由教务确认",
      action: "去描述第一条规则",
    },
    solve: {
      title: blockers ? `先处理 ${blockers} 个必须处理项` : "启动工业级 AI 智能排课",
      message: blockers ? "系统已经列出阻断原因；处理后重新检查，按钮会自动恢复可用。" : "确认本次输入快照后启动求解，运行状态会持续显示。",
      time: blockers ? "取决于阻断项" : "可后台运行",
      prepare: blockers ? "排课前检查" : "已确认的数据和规则",
      done: blockers ? "启动按钮恢复可用" : "生成无硬冲突候选",
      action: blockers ? "去处理阻断项" : "开始智能排课",
    },
    review: {
      title: next.title,
      message: next.message,
      time: "约 10–20 分钟",
      prepare: "推荐候选与冲突证据",
      done: "选定可发布方案",
      action: "审查推荐方案",
    },
    publish: {
      title: "确认最终版本并发布课表",
      message: "核对生效范围、日期和发布门禁，由当前用户确认并选择 PDF 或 Excel 下载。",
      time: "约 5 分钟",
      prepare: "最终候选与生效范围",
      done: "生成下载文件与正式版本记录",
      action: "进入课表发布",
    },
  };
  return tasks[next.stage.id] || tasks.foundation;
}

function formalOverviewRows() {
  const stages = formalStageState();
  const teachersReady = state.teachers.length > 0;
  const hoursReady = asArray(state.dayRules?.subject_hours).length > 0;
  const fixedReady = asArray(state.dayRules?.fixed_slots).length > 0;
  const rulesReady = Boolean(state.rulesV2?.summary?.active || state.readiness?.summary?.can_start_solver);
  const systemRules = formalCatalogRules().filter((rule) => rule.enabled !== false).length;
  const customRules = formalCustomRules().filter((rule) => rule.status === "active" && rule.enabled !== false).length;
  const solveStarted = stages.solve.completed;
  return [
    { number: 1, label: "学期与作息", done: foundationStepReady("calendar"), standard: foundationStepReady("calendar") ? `${asArray(state.dayRules?.time_grid).length} 个节次已设置` : "从空白周课表开始设置", view: "data", step: "calendar", action: foundationStepReady("calendar") ? "查看作息" : "开始设置" },
    { number: 2, label: "教师定位表", done: teachersReady, standard: teachersReady ? `${state.teachers.length} 个班级定位已读取` : "下载模板后导入教师定位", view: "data", step: "teachers", action: teachersReady ? "查看" : "导入表格" },
    { number: 3, label: "年级学科课时", done: hoursReady, standard: hoursReady ? `${asArray(state.dayRules?.subject_hours).length} 条课时标准已录入` : "设置各年级各学科周课时", view: "data", step: "hours", action: hoursReady ? "继续设置" : "开始设置" },
    { number: 4, label: "规则设置", done: rulesReady, standard: rulesReady ? `${systemRules} 条默认规则${customRules ? ` · ${customRules} 条个性化规则` : "已就绪"}` : "核对默认规则，按需使用 AI 助手", view: "rules", action: rulesReady ? "查看规则" : "设置规则" },
    { number: 5, label: "智能排课", done: solveStarted, standard: solveStarted ? `${formatNumber(state.solveStatus?.solution_count || 1)} 个候选方案可审查` : "生成至少 1 个无硬冲突候选", view: "solve", action: solveStarted ? "审查方案" : "开始排课" },
  ];
}

renderOverview = function renderOverviewFormal() {
  const next = formalOverviewNext();
  const task = formalOverviewTask(next);
  const nextIndex = Math.max(0, FORMAL_STAGE_DEFS.findIndex((item) => item.id === next.stage.id));
  const rows = formalOverviewRows();
  const completed = rows.filter((item) => item.done).length;
  return `
    ${formalWorkflow(next.stage.id)}
    <section class="formal-next-card">
      <b class="formal-next-number">${nextIndex + 1}</b>
      <div class="formal-next-copy"><span class="formal-next-kicker">下一步只做这件事</span><h2>${escapeHtml(task.title)}</h2><p>${escapeHtml(task.message)}</p></div>
      <div class="formal-next-actions"><button type="button" data-view-jump="${escapeAttr(next.stage.view)}">${escapeHtml(task.action)}</button><button type="button" class="secondary" data-action="open-page-hint">任务提示</button></div>
    </section>
    <section class="overview-task-board" aria-label="本学期排课事项">
      <header><div><span class="overview-task-icon"><i class="ri-calendar-check-line" aria-hidden="true"></i></span><div><h2>本学期排课事项</h2><p>按顺序完成，系统会自动保存每一步状态。</p></div></div><div class="overview-task-progress"><span>已完成 <b>${completed}</b> / ${rows.length} 项</span><i style="--task-progress:${completed / rows.length * 100}%"><b></b></i></div></header>
      <div class="overview-task-grid">${rows.map((item) => {
        const active = !item.done && next.stage.view === item.view;
        const [statusLabel, tone] = formalStageStatusLabel(item.done, active);
        return `<article class="overview-task-card ${active ? "active" : ""} ${item.done ? "done" : ""}"><div class="overview-task-title"><b>${item.number}</b><h3>${escapeHtml(item.label)}</h3><span class="pill ${tone}">${escapeHtml(statusLabel)}</span></div><p><i class="${item.done ? "ri-checkbox-circle-fill" : active ? "ri-time-line" : "ri-checkbox-blank-circle-line"}" aria-hidden="true"></i>${escapeHtml(item.standard)}</p><button type="button" data-view-jump="${escapeAttr(item.view)}" ${item.step ? `data-foundation-step="${escapeAttr(item.step)}"` : ""}>${escapeHtml(item.action)}<i class="ri-arrow-right-s-line" aria-hidden="true"></i></button></article>`;
      }).join("")}</div>
    </section>
    <div class="formal-ai-note">AI 助手负责理解复杂规则，工业级求解引擎负责全局排课；最终规则和课表都由教务确认。</div>
  `;
};

function foundationStepReady(id) {
  if (id === "calendar") return asArray(state.dayRules?.time_grid).length > 0;
  if (id === "teachers") return state.teachers.length > 0;
  if (id === "hours") return asArray(state.dayRules?.subject_hours).length > 0;
  if (id === "fixed") return asArray(state.dayRules?.fixed_slots).length > 0;
  return false;
}

function formalFoundationList() {
  return `<nav class="foundation-step-list" aria-label="基础设置步骤">${FORMAL_FOUNDATION_STEPS.map((step, index) => {
    const ready = foundationStepReady(step.id);
    return `<button type="button" class="foundation-step ${state.foundationStep === step.id ? "active" : ""}" data-action="set-foundation-step" data-step="${step.id}"><b>${index + 1}</b><strong>${escapeHtml(step.label)}</strong><span>${state.foundationStep === step.id ? "进行中" : ready ? "已完成" : "未开始"}</span></button>`;
  }).join("")}</nav>`;
}

const FORMAL_WEEK_DAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"];
const FORMAL_DAY_SHORT = { 星期一: "周一", 星期二: "周二", 星期三: "周三", 星期四: "周四", 星期五: "周五", 星期六: "周六", 星期日: "周日" };

function formalCurrentProjectSettings() {
  const rows = asArray(state.dayRules?.time_grid);
  const saved = asObject(state.projectState?.settings);
  const activeDays = asArray(saved.active_days).length
    ? asArray(saved.active_days)
    : FORMAL_WEEK_DAYS.filter((day) => rows.some((row) => Number(row?.[day] || 0) === 1));
  const savedCounts = { early: 0, morning: 0, afternoon: 0, evening: 0, ...asObject(saved.period_counts) };
  const derivedCounts = rows.reduce((counts, row) => {
    const slot = String(row?.时段节次 || row?.节次 || "");
    if (slot.startsWith("早自习")) counts.early += 1;
    else if (slot.startsWith("上午")) counts.morning += 1;
    else if (slot.startsWith("下午")) counts.afternoon += 1;
    else if (slot.startsWith("晚自习")) counts.evening += 1;
    return counts;
  }, { early: 0, morning: 0, afternoon: 0, evening: 0 });
  const hasSavedCounts = Object.values(savedCounts).some((value) => Number(value) > 0);
  return {
    term_name: saved.term_name || "2026-2027 学年第一学期",
    term_start: saved.term_start || "2026-09-01",
    term_end: saved.term_end || "2027-01-22",
    week_mode: "weekly",
    active_days: activeDays.length ? activeDays : FORMAL_WEEK_DAYS.slice(0, 5),
    public_rest: saved.public_rest || "周六、周日",
    period_counts: hasSavedCounts ? savedCounts : derivedCounts,
  };
}

function formalClassNames() {
  return Array.from(new Set(state.teachers.map((row) => String(row?.班级 || "").trim()).filter(Boolean)));
}

function formalSubjectNames() {
  const reserved = new Set(["row_index", "班级", "班主任", "班主任性别"]);
  const fromTeachers = state.teachers.flatMap((row) => Object.keys(row || {}).filter((key) => !reserved.has(key)));
  const fromHours = asArray(state.dayRules?.subject_hours).flatMap((row) => {
    if (row?.学科) return [String(row.学科)];
    return Object.keys(row || {}).filter((key) => !reserved.has(key) && !["说明", "年级"].includes(key));
  });
  return Array.from(new Set([...fromTeachers, ...fromHours].map((item) => String(item).trim()).filter(Boolean)));
}

function formalFixedSlot(day, slot, className = state.formalCalendarClass) {
  if (!className) return null;
  return asArray(state.dayRules?.fixed_slots).find((item) => String(item?.班级 || "") === className && String(item?.星期 || "") === day && String(item?.节次 || "") === slot) || null;
}

function formalCalendarCellValue(row, day, slot) {
  if (formalFixedSlot(day, slot)) return "fixed";
  return Number(row?.[day] || 0) === 1 ? "open" : "blocked";
}

function formalCalendarRows() {
  const rows = asArray(state.dayRules?.time_grid);
  const classes = formalClassNames();
  if (!state.formalCalendarClass && classes.length) state.formalCalendarClass = classes[0];
  if (!rows.length) return `<div class="calendar-empty"><i class="ri-calendar-schedule-line" aria-hidden="true"></i><h3>先设置每天有几节课</h3><p>系统会生成一周空白课表，再逐格选择“排课、禁排或固定课程”。</p><button type="button" data-action="open-period-settings">设置节次</button></div>`;
  const conflicts = formalCalendarConflicts();
  return `<div class="weekly-schedule-wrap"><div class="weekly-schedule-toolbar"><div><strong>一周班级空白课表</strong><span>每个格子都可以直接选择状态</span></div><label>固定课程班级<select id="formalCalendarClass" data-control="formal-calendar-class"><option value="">选择班级</option>${classes.map((name) => `<option value="${escapeAttr(name)}" ${state.formalCalendarClass === name ? "selected" : ""}>${escapeHtml(name)}</option>`).join("")}</select></label><button type="button" class="secondary" data-action="open-period-settings">修改节次</button></div><div class="weekly-schedule-grid" style="--week-days:${FORMAL_WEEK_DAYS.length}"><div class="weekly-schedule-head">节次</div>${FORMAL_WEEK_DAYS.map((day) => `<div class="weekly-schedule-head">${FORMAL_DAY_SHORT[day]}</div>`).join("")}${rows.map((row) => {
    const slot = String(row?.时段节次 || row?.节次 || "节次");
    return `<div class="weekly-schedule-slot"><strong>${escapeHtml(slot)}</strong><small>${escapeHtml(slot.replace(/\d+$/, ""))}</small></div>${FORMAL_WEEK_DAYS.map((day) => {
      const value = formalCalendarCellValue(row, day, slot);
      const fixed = formalFixedSlot(day, slot);
      return `<label class="weekly-schedule-cell ${value}"><select aria-label="${escapeAttr(`${FORMAL_DAY_SHORT[day]} ${slot}`)}" data-control="formal-calendar-cell" data-day="${escapeAttr(day)}" data-slot="${escapeAttr(slot)}"><option value="open" ${value === "open" ? "selected" : ""}>排课</option><option value="blocked" ${value === "blocked" ? "selected" : ""}>禁排</option><option value="fixed" ${value === "fixed" ? "selected" : ""}>固定排课</option></select>${fixed ? `<small title="${escapeAttr(fixed.学科 || "固定课程")}">${escapeHtml(fixed.学科 || "固定课程")}</small>` : ""}</label>`;
    }).join("")}`;
  }).join("")}</div><div class="weekly-schedule-legend"><span><i class="open"></i>排课</span><span><i class="blocked"></i>禁排</span><span><i class="fixed"></i>固定课程</span><small>选择固定排课后，再选择班级和课程名称。</small></div>${conflicts.length ? `<div class="inline-conflict-alert"><i class="ri-error-warning-line" aria-hidden="true"></i><div><strong>发现 ${conflicts.length} 处时间冲突</strong><span>固定课程落在禁排格中，请把该格改为排课或移除固定课程。</span></div></div>` : ""}</div>`;
}

function formalCalendarPanel() {
  const settings = formalCurrentProjectSettings();
  return `<div class="foundation-calendar-stack">
    <section class="formal-card foundation-panel foundation-term-card">
      <div class="foundation-panel-heading"><div><span>01</span><div><h2>学期与上课周期</h2><p>新项目默认每周使用同一套课表，大小周暂不开放。</p></div></div><div class="card-actions"><button type="button" class="secondary" data-action="download-foundation-template" data-table="time_grid">下载 Excel 模板</button><label class="upload-button">导入作息表<input type="file" hidden accept=".xlsx,.csv,text/csv" data-upload="day-rule" data-table="time_grid"></label></div></div>
      <div class="foundation-form-grid">
        <div class="field-group full"><label for="formalTermName">学期名称</label><input id="formalTermName" value="${escapeAttr(settings.term_name)}"></div>
        <div class="field-group"><label for="formalTermStart">开始日期</label><input id="formalTermStart" type="date" value="${escapeAttr(settings.term_start)}"></div>
        <div class="field-group"><label for="formalTermEnd">结束日期</label><input id="formalTermEnd" type="date" value="${escapeAttr(settings.term_end)}"></div>
        <div class="field-group full"><label>排课周期</label><div class="week-mode-choice"><label class="selected"><input type="radio" name="weekMode" value="weekly" checked>每周相同 <small>当前默认</small></label><label class="disabled" title="正式版首期暂不开放"><input type="radio" name="weekMode" value="ab" disabled>大小周 <small>暂未开放</small></label></div></div>
        <div class="field-group full"><label>上课日</label><div class="check-row-inline">${FORMAL_WEEK_DAYS.map((day) => `<label><input type="checkbox" data-control="formal-active-day" value="${escapeAttr(day)}" ${settings.active_days.includes(day) ? "checked" : ""}>${FORMAL_DAY_SHORT[day]}</label>`).join("")}</div></div>
        <div class="field-group full"><label for="formalPublicRest">固定公休</label><input id="formalPublicRest" value="${escapeAttr(settings.public_rest)}" placeholder="例如：周六、周日；法定节假日按校历执行"></div>
      </div>
    </section>
    <section class="formal-card foundation-panel foundation-schedule-card"><div class="foundation-panel-heading"><div><span>02</span><div><h2>每日作息</h2><p>先设置早、上午、下午和晚自习节数，再在周课表里逐格选择。</p></div></div></div>${formalCalendarRows()}</section>
  </div>`;
}

function formalOpenPeriodSettings() {
  if ($("formalTermName")) {
    state.projectState = { ...state.projectState, settings: formalProjectSettingsPayload() };
  }
  const root = $("modalRoot");
  const counts = formalCurrentProjectSettings().period_counts;
  root.hidden = false;
  root.innerHTML = `<div class="formal-period-modal" role="dialog" aria-modal="true" aria-labelledby="formalPeriodTitle"><header><span>设置作息</span><h2 id="formalPeriodTitle">每天各时间段有几节课？</h2><p>保存后会重新生成一周课表；已有同名节次的设置会保留。</p></header><div class="period-count-grid">${[["early", "早自习"], ["morning", "上午"], ["afternoon", "下午"], ["evening", "晚自习"]].map(([key, label]) => `<label><span>${label}</span><input id="formalPeriod_${key}" type="number" min="0" max="12" value="${Number(counts[key] || 0)}"><small>节</small></label>`).join("")}</div><footer><button type="button" class="secondary" data-action="close-modal">取消</button><button type="button" data-action="save-period-settings">生成周课表</button></footer></div>`;
}

function formalApplyPeriodSettings() {
  const labels = { early: "早自习", morning: "上午", afternoon: "下午", evening: "晚自习" };
  const oldRows = asArray(state.dayRules?.time_grid);
  const oldBySlot = new Map(oldRows.map((row) => [String(row?.时段节次 || row?.节次 || ""), row]));
  const settings = formalCurrentProjectSettings();
  const active = new Set(settings.active_days);
  const counts = {};
  const rows = [];
  Object.entries(labels).forEach(([key, label]) => {
    const count = Math.max(0, Math.min(12, Number($("formalPeriod_" + key)?.value || 0)));
    counts[key] = count;
    for (let index = 1; index <= count; index += 1) {
      const slot = `${label}${index}`;
      const previous = oldBySlot.get(slot);
      const row = { 时段节次: slot };
      FORMAL_WEEK_DAYS.forEach((day) => { row[day] = previous ? Number(previous?.[day] || 0) : active.has(day) ? 1 : 0; });
      rows.push(row);
    }
  });
  state.dayRules = { ...state.dayRules, time_grid: rows };
  state.projectState = { ...state.projectState, settings: { ...settings, period_counts: counts } };
  closeModal();
  renderShell();
  toast(`已生成 ${rows.length} 个节次，请继续设置每个格子`);
}

function formalOpenFixedCourseDialog(day, slot) {
  if ($("formalTermName")) {
    state.projectState = { ...state.projectState, settings: formalProjectSettingsPayload() };
  }
  const root = $("modalRoot");
  const classes = formalClassNames();
  const subjects = formalSubjectNames();
  if (!classes.length) throw new Error("请先导入教师定位表，再设置固定课程");
  const selectedClass = state.formalCalendarClass && classes.includes(state.formalCalendarClass) ? state.formalCalendarClass : classes[0];
  root.hidden = false;
  root.innerHTML = `<div class="formal-fixed-course-modal" role="dialog" aria-modal="true" aria-labelledby="formalFixedCourseTitle"><header><span>${escapeHtml(FORMAL_DAY_SHORT[day])} · ${escapeHtml(slot)}</span><h2 id="formalFixedCourseTitle">选择固定课程</h2><p>固定课程会写入固定课位表，并在排课时优先占用该格。</p></header><div class="editor-grid"><div class="field-group"><label for="formalFixedClass">班级</label><select id="formalFixedClass">${classes.map((name) => `<option value="${escapeAttr(name)}" ${name === selectedClass ? "selected" : ""}>${escapeHtml(name)}</option>`).join("")}</select></div><div class="field-group"><label for="formalFixedSubject">课程名称</label>${subjects.length ? `<select id="formalFixedSubject">${subjects.map((name) => `<option value="${escapeAttr(name)}">${escapeHtml(name)}</option>`).join("")}</select>` : `<input id="formalFixedSubject" placeholder="例如：班会">`}</div></div><footer><button type="button" class="secondary" data-action="close-modal">取消</button><button type="button" data-action="save-fixed-calendar-cell" data-day="${escapeAttr(day)}" data-slot="${escapeAttr(slot)}">确定固定</button></footer></div>`;
}

function formalSaveFixedCalendarCell(day, slot) {
  const className = String($("formalFixedClass")?.value || "").trim();
  const subject = String($("formalFixedSubject")?.value || "").trim();
  if (!className || !subject) throw new Error("请选择班级和课程名称");
  const teacherRow = state.teachers.find((row) => String(row?.班级 || "") === className) || {};
  const teacher = String(teacherRow?.[subject] || "").trim();
  const fixed = asArray(state.dayRules?.fixed_slots).filter((item) => !(String(item?.班级 || "") === className && String(item?.星期 || "") === day && String(item?.节次 || "") === slot));
  fixed.push({ 班级: className, 星期: day, 节次: slot, 学科: subject, 教师: teacher });
  const rows = asArray(state.dayRules?.time_grid).map((row) => String(row?.时段节次 || row?.节次 || "") === slot ? { ...row, [day]: 1 } : row);
  state.dayRules = { ...state.dayRules, fixed_slots: fixed, time_grid: rows };
  state.formalCalendarClass = className;
  closeModal();
  renderShell();
  toast(`${className}${FORMAL_DAY_SHORT[day]}${slot}已固定为${subject}`);
}

function formalCalendarConflicts() {
  const rows = asArray(state.dayRules?.time_grid);
  const bySlot = new Map(rows.map((row) => [String(row?.时段节次 || row?.节次 || ""), row]));
  return asArray(state.dayRules?.fixed_slots).filter((item) => {
    const row = bySlot.get(String(item?.节次 || ""));
    return row && Number(row?.[String(item?.星期 || "")] || 0) !== 1;
  });
}

function formalChangeCalendarCell(select) {
  if ($("formalTermName")) {
    state.projectState = { ...state.projectState, settings: formalProjectSettingsPayload() };
  }
  const day = select.dataset.day || "";
  const slot = select.dataset.slot || "";
  const value = select.value || "open";
  const row = asArray(state.dayRules?.time_grid).find((item) => String(item?.时段节次 || item?.节次 || "") === slot);
  if (!row || !FORMAL_WEEK_DAYS.includes(day)) return;
  if (value === "fixed") {
    select.value = formalCalendarCellValue(row, day, slot);
    formalOpenFixedCourseDialog(day, slot);
    return;
  }
  row[day] = value === "open" ? 1 : 0;
  if (state.formalCalendarClass) {
    state.dayRules.fixed_slots = asArray(state.dayRules?.fixed_slots).filter((item) => !(String(item?.班级 || "") === state.formalCalendarClass && String(item?.星期 || "") === day && String(item?.节次 || "") === slot));
  }
  renderShell();
  const conflicts = formalCalendarConflicts();
  toast(conflicts.length ? `已设置，但有 ${conflicts.length} 个固定课程与禁排格冲突` : `${FORMAL_DAY_SHORT[day]}${slot}已设为${value === "open" ? "排课" : "禁排"}`);
}

function formalProjectSettingsPayload() {
  const current = formalCurrentProjectSettings();
  const checked = Array.from(document.querySelectorAll("[data-control='formal-active-day']:checked")).map((node) => node.value);
  return {
    term_name: String($("formalTermName")?.value || current.term_name).trim(),
    term_start: String($("formalTermStart")?.value || current.term_start).trim(),
    term_end: String($("formalTermEnd")?.value || current.term_end).trim(),
    week_mode: "weekly",
    active_days: checked.length ? checked : current.active_days,
    public_rest: String($("formalPublicRest")?.value || current.public_rest).trim(),
    period_counts: current.period_counts,
  };
}

async function formalSaveCalendarFoundation() {
  const settings = formalProjectSettingsPayload();
  const activeDays = new Set(settings.active_days);
  const rows = asArray(state.dayRules?.time_grid).map((row) => {
    const next = { ...stripRowIndex(row) };
    FORMAL_WEEK_DAYS.forEach((day) => {
      if (!activeDays.has(day)) next[day] = 0;
    });
    return next;
  });
  const conflicts = formalCalendarConflicts();
  if (conflicts.length) throw new Error(`有 ${conflicts.length} 个固定课程落在禁排格，请先调整后保存`);
  await api("/api/project/settings", { method: "POST", body: settings });
  for (const [table, tableRows] of [["time_grid", rows], ["fixed_slots", asArray(state.dayRules?.fixed_slots).map(stripRowIndex)]]) {
    await api("/api/day-rules", { method: "POST", body: { table, rows: tableRows, source: "foundation.calendar.grid", reason: `作息课表保存 ${tableRows.length} 行`, actor: "web" } });
  }
  await loadAll({ silent: true });
}

function formalFoundationTable(step) {
  if (step === "teachers") {
    return `<section class="formal-card foundation-data-card"><div class="foundation-data-head"><div><span class="foundation-start-label">从 0 开始设置</span><h2>教师定位表</h2><p>下载 Excel 模板填写后上传，或直接导入学校现有表格；系统按实际表头识别学科。</p></div><div class="card-actions"><button type="button" class="secondary" data-action="download-teacher-template">下载 Excel 模板</button><label class="upload-button">上传已填写表格<input type="file" hidden accept=".xlsx,.xls,.csv,text/csv" data-upload="teacher"></label><button type="button" data-action="save-teachers">保存定位表</button></div></div>${state.teachers.length ? renderEditableTable("teacher", state.teachers) : `<div class="foundation-upload-empty"><i class="ri-file-excel-2-line" aria-hidden="true"></i><h3>还没有教师定位数据</h3><p>至少提供班级列和一列学科任课教师；班主任、性别列可不提供。</p></div>`}</section>`;
  }
  const tableKey = step === "hours" ? "subject_hours" : "fixed_slots";
  const title = step === "hours" ? "各年级各学科课时" : "场地与固定事项";
  const description = step === "hours" ? "设置早自习、周中和周末课时；班级差异可在覆盖表中单独调整。" : "录入固定课位、统一公休、场地占用和不可移动的教务事项。";
  const rows = asArray(state.dayRules?.[tableKey]);
  return `<section class="formal-card foundation-data-card"><div class="foundation-data-head"><div><span class="foundation-start-label">从 0 开始设置</span><h2>${title}</h2><p>${description}</p></div><div class="card-actions"><button type="button" class="secondary" data-action="download-foundation-template" data-table="${tableKey}">下载 Excel 模板</button><label class="upload-button">上传已填写表格<input type="file" hidden accept=".xlsx,.csv,text/csv" data-upload="day-rule" data-table="${tableKey}"></label><button type="button" data-action="add-foundation-row" data-table="${tableKey}">手动新增</button><button type="button" data-action="save-foundation-step">保存</button></div></div>${rows.length ? renderEditableTable("day", rows, { tableKey }) : `<div class="foundation-upload-empty"><i class="ri-file-excel-2-line" aria-hidden="true"></i><h3>当前还没有数据</h3><p>推荐下载 Excel 模板批量填写；也可以点击“手动新增”逐行录入。</p></div>`}</section>`;
}

renderDataView = function renderDataViewFormal() {
  const step = FORMAL_FOUNDATION_STEPS.find((item) => item.id === state.foundationStep) || FORMAL_FOUNDATION_STEPS[0];
  return `${formalWorkflow("foundation")}<div class="foundation-layout">${formalFoundationList()}<div class="foundation-main">${step.id === "calendar" ? formalCalendarPanel() : formalFoundationTable(step.id)}<div class="foundation-footer"><div class="foundation-footer-note">保存后会重新检查作息、教师、课时和固定事项是否互相冲突。</div><div class="foundation-footer-actions"><button type="button" class="secondary" data-action="save-foundation-step">保存当前设置</button><button type="button" data-action="next-foundation-step">保存并进入下一项</button></div></div></div></div>`;
};

function formalCustomRules() {
  return asArray(state.rulesV2?.rules).map((rule) => ({
    ...rule,
    business_domain: rule.business_domain || "course",
    rule_category: rule.rule_category || (asArray(rule.scope?.teachers).length ? "teacher" : asArray(rule.scope?.subjects).length ? "subject" : "basic"),
    _source: "v2",
  }));
}

function formalCatalogRules() {
  const domains = asArray(state.config?.business_rule_domains);
  if (domains.length) {
    return domains.flatMap((domain) => asArray(domain.sections).flatMap((section) => asArray(section.rules).map((rule) => ({
      id: String(rule.id || ""),
      title: rule.title || rule.label || "未命名规则",
      description: rule.explanation || "",
      policy_level: rule.policy_level || "default",
      business_domain: domain.id || rule.business_domain || "course",
      rule_category: section.id || rule.rule_category || "basic",
      strength: String(rule.mode || "").includes("软") || String(rule.mode || "").toLowerCase() === "soft" ? "soft" : "hard",
      scope: { display: rule.scope || domain.title || "全校" },
      effective_time: rule.effective_time || { mode: "project_term", week_pattern: "all" },
      exceptions: [],
      solver_support: rule.solver_support || { status: "supported" },
      status: rule.enabled === false ? "disabled" : "active",
      enabled: rule.enabled !== false,
      mandatory: rule.mandatory === true,
      locked: rule.locked === true,
      editable: rule.editable !== false,
      solver_bindings: asArray(rule.solver_bindings),
      enforcement: rule.enforcement || "solver",
      conditional: rule.conditional === true,
      _source: "catalog",
      _group: `${domain.title} / ${section.title}`,
    }))));
  }
  const groups = asArray(state.config?.business_rule_groups);
  return groups.flatMap((group) => asArray(group.rules).map((rule) => {
    const groupId = String(group.id || "");
    const level = groupId.includes("teacher") || groupId.includes("temporary") ? "special" : groupId.includes("subject") || groupId.includes("grade") ? "grade_subject" : "schoolwide";
    const mode = String(rule.mode || "");
    return {
      id: String(rule.id || ""),
      title: rule.title || rule.label || "未命名规则",
      description: rule.explanation || "",
      policy_level: level,
      business_domain: groupId === "duty" ? "roster" : "course",
      rule_category: groupId.includes("teacher") ? "teacher" : "basic",
      strength: mode.includes("软") || mode.toLowerCase() === "soft" ? "soft" : "hard",
      scope: { display: rule.scope || group.title || "全校" },
      effective_time: { mode: "project_term", week_pattern: "all" },
      exceptions: [
        ...asArray(rule.application?.exception_teachers),
        ...asArray(rule.application?.exception_subject_groups),
      ],
      solver_support: { status: "supported" },
      status: rule.enabled === false ? "disabled" : "active",
      enabled: rule.enabled !== false,
      _source: "catalog",
      _group: group.title,
    };
  }));
}

function formalAllRules() {
  return [...formalCustomRules(), ...formalCatalogRules()];
}

function formalRuleLevelLabel(level) {
  return ({ default: "默认规则", schoolwide: "统一规则", grade_subject: "年级学科", special: "特殊规则" })[level] || "特殊规则";
}

function formalStrengthLabel(strength) {
  return ({ hard: "硬规则", soft: "软规则", advisory: "建议" })[strength] || "待确认";
}

function formalRuleScopeText(rule) {
  if (rule.scope?.display) return rule.scope.display;
  const scope = rule.scope || {};
  const values = ["grades", "classes", "subjects", "teachers", "rooms"].flatMap((key) => asArray(scope[key]));
  return values.slice(0, 3).join("、") || "全校";
}

function formalRuleTimeText(rule) {
  const time = rule.effective_time || {};
  if (time.mode === "date_range") return `${time.date_from || "?"}–${time.date_to || "?"}`;
  if (time.week_pattern && !["all", "ab"].includes(time.week_pattern)) return String(time.week_pattern).toUpperCase() + " 周";
  return "本学期";
}

function formalFilteredRules() {
  const query = String(state.formalRuleSearch || "").trim().toLowerCase();
  return formalAllRules().filter((rule) => {
    if (state.formalRuleDomain && rule.business_domain !== state.formalRuleDomain) return false;
    if (state.formalRuleCategory && rule.rule_category !== state.formalRuleCategory) return false;
    if (state.formalRuleTab === "draft" && !["draft", "needs_clarification", "validated"].includes(rule.status)) return false;
    if (!["all", "draft"].includes(state.formalRuleTab) && rule.policy_level !== state.formalRuleTab) return false;
    if (["hard", "soft"].includes(state.formalRuleFilter) && rule.strength !== state.formalRuleFilter) return false;
    if (state.formalRuleFilter === "exceptions" && !asArray(rule.exceptions).length) return false;
    if (state.formalRuleFilter === "recent" && rule._source !== "v2") return false;
    if (query && !`${rule.title} ${rule.description} ${formalRuleScopeText(rule)}`.toLowerCase().includes(query)) return false;
    return true;
  });
}

function formalRuleDraftPanel() {
  const rule = state.parsedRuleV2;
  if (!rule) return "";
  const valid = Boolean(rule.validation?.valid);
  const supported = rule.solver_support?.status === "supported";
  const issues = [...asArray(rule.validation?.errors), ...asArray(rule.validation?.warnings)].slice(0, 3).map(formalRuleIssueText);
  const aiUsed = rule.ai_used === true;
  const report = asObject(rule.ai_modeling);
  const understood = asArray(report.interpreted_requirements).length
    ? asArray(report.interpreted_requirements).slice(0, 4)
    : [rule.description || rule.source?.text || "已读取自然语言需求"];
  const mappings = asArray(report.constraint_mapping).length
    ? asArray(report.constraint_mapping).slice(0, 4)
    : [{
      requirement: rule.title || "当前需求",
      rule_v2_type: rule.constraint?.type || "待补充",
      solver_effect: supported ? "将应用到正式排课" : "暂不能进入排课",
    }];
  const limitations = asArray(report.limitations).slice(0, 4);
  const recommendations = asArray(report.recommendations).slice(0, 4);
  const originTitle = aiUsed ? "AI 已实际理解并整理这条规则" : "AI 本次未完成规则整理";
  const originDetail = aiUsed
    ? "AI 已完成需求理解、范围拆分和可执行性检查；只有当前用户确认后，规则才会进入正式排课。"
    : "AI 服务本次未返回可用结果，系统仅保留本地安全草案；下方会明确列出局限和下一步。";
  return `<section class="rule-draft-panel">
    <div class="rule-draft-origin ${aiUsed ? "ai" : "local"}" role="status"><strong>${originTitle}</strong><span>${originDetail}</span></div>
    <div class="rule-draft-heading"><div><h3>${escapeHtml(rule.title || "规则草案")}</h3><p>${escapeHtml(rule.description || rule.source?.text || "")}</p></div><span class="modeling-status ${supported && valid ? "ready" : "limited"}">${supported && valid ? "可以进入排课" : "还需补充"}</span></div>
    <div class="rule-draft-meta"><span>${escapeHtml(formalRuleLevelLabel(rule.policy_level))}</span><span>${escapeHtml(formalStrengthLabel(rule.strength))}</span><span>${escapeHtml(formalRuleScopeText(rule))}</span><span>${escapeHtml(formalRuleTimeText(rule))}</span></div>
    <div class="ai-modeling-grid">
      <article><span>01 · AI 理解</span><strong>识别了哪些需求</strong><ul>${understood.map((item) => `<li>${escapeHtml(typeof item === "string" ? item : item.detail || item.title || "")}</li>`).join("")}</ul></article>
      <article><span>02 · 整理规则</span><strong>系统会怎样执行</strong><ul>${mappings.map((item) => `<li><b>${escapeHtml(item.requirement || rule.title || "当前需求")}</b><small>${escapeHtml(formalConstraintLabel(item.rule_v2_type || rule.constraint?.type))} · ${escapeHtml(item.solver_effect || "等待检查")}</small></li>`).join("")}</ul></article>
      <article><span>03 · 应用检查</span><strong>${supported && valid ? "规则可以真正影响排课" : "暂不能进入正式排课"}</strong><p>${escapeHtml(supported ? "系统已经识别这条规则的作用方式。" : "当前规则仍需补充范围、时间或例外。")}</p></article>
      <article class="${limitations.length || issues.length ? "limited" : "ready"}"><span>04 · 局限与建议</span><strong>${limitations.length || issues.length ? "AI 已标出现有局限" : "未发现当前规则局限"}</strong>${limitations.length || issues.length ? `<ul>${(limitations.length ? limitations : issues).map((item, index) => `<li><b>${escapeHtml(typeof item === "string" ? item : item.title || item.detail || "")}</b><small>${escapeHtml((recommendations[index] && (recommendations[index].action || recommendations[index].title)) || (typeof item === "object" && item.recommendation) || "请编辑草案补充信息后重新检查")}</small></li>`).join("")}</ul>` : `<p>范围、时间、例外和执行方式均已明确。</p>`}</article>
    </div>
    <div class="rule-draft-actions"><button type="button" class="secondary" data-action="edit-parsed-rule-v2">编辑草案</button><button type="button" data-action="save-rule-v2">保存草案</button><button type="button" data-action="activate-rule-v2" ${valid && supported ? "" : "disabled"}>我确认规则，加入求解</button></div>
  </section>`;
}

function formalRuleIssueText(value) {
  const text = String(value || "");
  if (text.includes("prefer_period requires params.period")) return "时段偏好缺少明确的上午、下午或首末节参数";
  if (text.includes("constraint.type is unsupported")) return "当前需求还没有匹配到系统可以执行的规则方式";
  if (text.includes("requires scope.teachers")) return "教师类规则还没有明确作用教师";
  if (text.includes("requires at least one day or slot")) return "禁排规则还没有明确星期或节次";
  if (text.includes("cannot be marked as solver-supported")) return "这条建议还不能直接影响排课，请补充明确条件";
  return text;
}

function formalConstraintLabel(value) {
  return ({
    catalog_ref: "已有规则映射",
    teacher_unavailable: "教师禁排",
    prefer_period: "时段偏好",
    max_daily_lessons: "每日课时上限",
  })[String(value || "")] || "待补充执行方式";
}

function formalRuleCard(rule) {
  const support = rule.solver_support?.status === "supported";
  const exceptionCount = asArray(rule.exceptions).length;
  const editAction = rule._source === "v2" ? "edit-rule-v2" : "edit-catalog-rule";
  const sourceLabel = rule.mandatory ? "系统底层" : rule._source === "v2" ? "AI / 自定义" : "系统规则";
  return `<article class="formal-rule-card ${escapeAttr(rule.strength)} ${escapeAttr(rule.policy_level)} ${rule.mandatory ? "mandatory" : ""}">
    <header><div><span class="rule-tag rule-strength ${escapeAttr(rule.strength)}">${escapeHtml(formalStrengthLabel(rule.strength))}</span>${rule.mandatory ? `<span class="rule-tag rule-locked">不可关闭</span>` : ""}<h3 title="${escapeAttr(rule.title)}">${escapeHtml(rule.title)}</h3></div><small>${escapeHtml(sourceLabel)}</small></header>
    <p class="formal-rule-description">${escapeHtml(rule.description || "")}</p>
    <footer><div class="rule-card-facts"><span><b>范围</b>${escapeHtml(formalRuleScopeText(rule))}</span><span><b>时间</b>${escapeHtml(formalRuleTimeText(rule))}</span></div><span class="${support ? "supported" : "limited"}">${support ? (rule.conditional ? "启用后生效" : "已应用到排课") : "尚未应用"}</span><button type="button" data-action="${rule.mandatory ? "edit-mandatory-rule-warning" : editAction}" data-rule-id="${escapeAttr(rule.id)}">${rule.mandatory ? "查看并调整" : "编辑规则"}</button></footer>
  </article>`;
}

function formalRuleCards() {
  const filtered = formalFilteredRules();
  const pageSize = Math.max(1, Number(state.formalRulePageSize) || 9);
  const pageCount = Math.max(1, Math.ceil(filtered.length / pageSize));
  const page = Math.min(pageCount, Math.max(1, Number(state.formalRulePage) || 1));
  state.formalRulePage = page;
  const rows = filtered.slice((page - 1) * pageSize, page * pageSize);
  return `<div class="formal-rule-card-grid">${rows.map(formalRuleCard).join("") || `<div class="empty-state">当前筛选下没有规则。</div>`}</div>
    <div class="formal-rule-pagination" aria-label="规则集分页">
      <span>第 ${page} / ${pageCount} 页 · 共 ${filtered.length} 条</span>
      <div><button type="button" class="secondary" data-action="previous-formal-rule-page" ${page <= 1 ? "disabled" : ""}>上一页</button><button type="button" data-action="next-formal-rule-page" ${page >= pageCount ? "disabled" : ""}>下一页</button></div>
    </div>`;
}

function formalRuleChecks() {
  const rules = formalAllRules();
  const custom = formalCustomRules();
  const incomplete = custom.filter((rule) => !rule.validation?.valid || rule.solver_support?.status !== "supported").length;
  const invalidTime = custom.filter((rule) => !rule.effective_time?.mode).length;
  const modeling = asObject(state.readiness?.modeling);
  const stats = asObject(modeling.stats);
  const modeled = modeling.ready === true;
  return `<aside class="rule-check-panel"><h3>规则检查结果</h3><div class="rule-check-item ${rules.length ? "ok" : "warning"}"><strong>${rules.length ? "作用范围已记录" : "尚无规则"}</strong><span>${rules.length ? "每条规则都能查看适用对象" : "先添加或启用规则"}</span></div><div class="rule-check-item ${invalidTime ? "warning" : "ok"}"><strong>${invalidTime ? `${invalidTime} 条时间待补充` : "作用时间已明确"}</strong><span>未单独设置时，默认整个当前学期生效</span></div><div class="rule-check-item ${incomplete ? "warning" : "ok"}"><strong>${incomplete ? `${incomplete} 条需要教务确认` : "规则已由当前用户确认"}</strong><span>未确认或暂不支持的草案不会进入正式排课</span></div><div class="rule-check-item ${modeled ? "ok" : "warning"}"><strong>${modeled ? "规则已真正应用" : "还有规则未能应用"}</strong><span>${escapeHtml(modeling.message || "重新检查后，系统会确认每条规则是否真正影响排课")}</span>${modeled ? `<small class="modeling-receipt-stats">已应用 ${formatNumber(stats.compiled_rule_count || rules.length)} 条规则</small>` : ""}</div><div class="rule-check-item ok"><strong>当前版本 v${state.rulesV2?.revision || 0}</strong><span>每次调整都会保留版本，便于回看</span></div></aside>`;
}

function formalVisualRuleSlots() {
  return asArray(state.dayRules?.time_grid).map((row) => String(row?.时段节次 || row?.节次 || "")).filter(Boolean);
}

function formalVisualCellKey(day, slot) {
  return `${day}|||${slot}`;
}

function formalVisualSelectedSet() {
  return new Set(asArray(state.visualRuleSelectedCells));
}

function formalVisualRuleConflicts() {
  const selected = formalVisualSelectedSet();
  const subject = String(state.visualRuleSubject || "").trim();
  const className = String(state.visualRuleClass || "").trim();
  const action = state.visualRuleAction || "ban";
  const conflicts = [];
  asArray(state.dayRules?.subject_bans).forEach((item) => {
    const key = formalVisualCellKey(String(item?.星期 || ""), String(item?.节次 || ""));
    if (!selected.has(key) || String(item?.学科 || "") !== subject) return;
    conflicts.push({ tone: action === "ban" ? "overlap" : "conflict", title: action === "ban" ? "与已有禁排规则重复" : "与已有学科禁排冲突", detail: `${item.学科}${FORMAL_DAY_SHORT[item.星期] || item.星期}${item.节次}` });
  });
  asArray(state.dayRules?.fixed_slots).forEach((item) => {
    const key = formalVisualCellKey(String(item?.星期 || ""), String(item?.节次 || ""));
    if (!selected.has(key)) return;
    if (action === "ban" && String(item?.学科 || "") === subject) conflicts.push({ tone: "conflict", title: "与固定课程冲突", detail: `${item.班级 || "班级"}已固定${item.学科}` });
    if (action === "fixed" && String(item?.班级 || "") === className && String(item?.学科 || "") !== subject) conflicts.push({ tone: "conflict", title: "同一班级同一时间已有课程", detail: `当前为${item.学科 || "固定事项"}` });
  });
  formalCustomRules().forEach((rule) => {
    if (!asArray(rule.scope?.subjects).includes(subject)) return;
    const days = asArray(rule.effective_time?.days);
    const slots = asArray(rule.effective_time?.slots);
    const overlaps = [...selected].some((key) => {
      const [day, slot] = key.split("|||");
      return (!days.length || days.includes(day)) && (!slots.length || slots.includes(slot));
    });
    if (overlaps) conflicts.push({ tone: "notice", title: "与另一种方式设置的规则时间重合", detail: rule.title || "个性化规则" });
  });
  return conflicts;
}

function formalVisualRuleGrid() {
  const slots = formalVisualRuleSlots();
  const selected = formalVisualSelectedSet();
  if (!slots.length) return `<div class="calendar-empty"><i class="ri-calendar-schedule-line" aria-hidden="true"></i><h3>请先完成作息设置</h3><p>这里会直接使用已经设置好的节次生成规则课表。</p><button type="button" data-view-jump="data" data-foundation-step="calendar">去设置作息</button></div>`;
  return `<div class="visual-rule-grid" style="--week-days:${FORMAL_WEEK_DAYS.length}"><div class="visual-rule-head">节次</div>${FORMAL_WEEK_DAYS.map((day) => `<div class="visual-rule-head">${FORMAL_DAY_SHORT[day]}</div>`).join("")}${slots.map((slot) => `<div class="visual-rule-slot">${escapeHtml(slot)}</div>${FORMAL_WEEK_DAYS.map((day) => {
    const key = formalVisualCellKey(day, slot);
    return `<button type="button" class="visual-rule-cell ${selected.has(key) ? "selected" : ""}" data-action="toggle-visual-rule-cell" data-cell-key="${escapeAttr(key)}" aria-pressed="${selected.has(key) ? "true" : "false"}">${selected.has(key) ? `<i class="ri-check-line" aria-hidden="true"></i>` : `<span>选择</span>`}</button>`;
  }).join("")}`).join("")}</div>`;
}

function formalVisualRulePage() {
  const subjects = formalSubjectNames();
  if (!state.visualRuleSubject && subjects.length) state.visualRuleSubject = subjects[0];
  const classes = formalClassNames();
  if (!state.visualRuleClass && classes.length) state.visualRuleClass = classes[0];
  const selected = formalVisualSelectedSet();
  const conflicts = formalVisualRuleConflicts();
  const hardConflicts = conflicts.filter((item) => item.tone === "conflict").length;
  return `<section class="visual-rule-page"><div class="visual-rule-toolbar"><div><span class="visual-rule-kicker">课表式规则设置</span><h2>在一周课表里直接点选</h2><p>适合“某学科在某天某节禁排”或“某班固定一门课”这类时间规则。</p></div><div class="visual-rule-controls"><label>课程<select data-control="visual-rule-subject">${subjects.map((name) => `<option value="${escapeAttr(name)}" ${state.visualRuleSubject === name ? "selected" : ""}>${escapeHtml(name)}</option>`).join("")}</select></label><label>设置为<select data-control="visual-rule-action"><option value="ban" ${state.visualRuleAction === "ban" ? "selected" : ""}>学科禁排（必须满足）</option><option value="fixed" ${state.visualRuleAction === "fixed" ? "selected" : ""}>固定课程（必须满足）</option></select></label>${state.visualRuleAction === "fixed" ? `<label>班级<select data-control="visual-rule-class">${classes.map((name) => `<option value="${escapeAttr(name)}" ${state.visualRuleClass === name ? "selected" : ""}>${escapeHtml(name)}</option>`).join("")}</select></label>` : ""}</div></div><div class="visual-rule-batch"><label>快速选择<select id="visualRuleBatchDay"><option value="星期一">周一</option><option value="星期二">周二</option><option value="星期三">周三</option><option value="星期四">周四</option><option value="星期五">周五</option><option value="星期六">周六</option><option value="星期日">周日</option></select><select id="visualRuleBatchPeriod"><option value="all">全天</option><option value="早自习">早自习</option><option value="上午">上午</option><option value="下午">下午</option><option value="晚自习">晚自习</option></select><button type="button" class="secondary" data-action="select-visual-rule-range">选择这一段</button></label><span>已选 <b>${selected.size}</b> 格 · 默认作用时间为本学期</span><button type="button" class="text-button" data-action="clear-visual-rule-cells" ${selected.size ? "" : "disabled"}>清空选择</button></div>${formalVisualRuleGrid()}<div class="visual-rule-footer"><div class="visual-rule-check ${hardConflicts ? "conflict" : conflicts.length ? "notice" : "ok"}"><i class="${hardConflicts ? "ri-error-warning-line" : conflicts.length ? "ri-information-line" : "ri-shield-check-line"}" aria-hidden="true"></i><div><strong>${hardConflicts ? `发现 ${hardConflicts} 个矛盾` : conflicts.length ? `发现 ${conflicts.length} 处重合` : "未发现重合或矛盾"}</strong><span>${hardConflicts ? "请先调整冲突规则，系统不会保存互相矛盾的设置。" : conflicts.length ? "重复项会自动合并，其他来源的相关规则请一并核对。" : "保存时还会重新检查固定课程、禁排格和其他规则。"}</span>${conflicts.length ? `<ul>${conflicts.slice(0, 4).map((item) => `<li><b>${escapeHtml(item.title)}</b>${escapeHtml(item.detail)}</li>`).join("")}</ul>` : ""}</div></div><button type="button" data-action="save-visual-rule" ${!selected.size || !state.visualRuleSubject || hardConflicts ? "disabled" : ""}>保存为正式规则</button></div></section>`;
}

function formalToggleVisualCell(key) {
  const selected = formalVisualSelectedSet();
  if (selected.has(key)) selected.delete(key); else selected.add(key);
  state.visualRuleSelectedCells = Array.from(selected);
  renderShell();
}

function formalSelectVisualRange() {
  const day = String($("visualRuleBatchDay")?.value || "星期一");
  const period = String($("visualRuleBatchPeriod")?.value || "all");
  const selected = formalVisualSelectedSet();
  formalVisualRuleSlots().filter((slot) => period === "all" || slot.startsWith(period)).forEach((slot) => selected.add(formalVisualCellKey(day, slot)));
  state.visualRuleSelectedCells = Array.from(selected);
  renderShell();
}

async function formalSaveVisualRule() {
  const conflicts = formalVisualRuleConflicts();
  if (conflicts.some((item) => item.tone === "conflict")) throw new Error("当前选择与已有规则冲突，请先处理冲突");
  const selected = [...formalVisualSelectedSet()].map((key) => key.split("|||"));
  const subject = String(state.visualRuleSubject || "").trim();
  if (!selected.length || !subject) throw new Error("请先选择课程和时间格");
  if (state.visualRuleAction === "fixed") {
    const className = String(state.visualRuleClass || "").trim();
    if (!className) throw new Error("固定课程需要先选择班级");
    const teacherRow = state.teachers.find((row) => String(row?.班级 || "") === className) || {};
    const teacher = String(teacherRow?.[subject] || "").trim();
    const rows = asArray(state.dayRules?.fixed_slots).map(stripRowIndex);
    selected.forEach(([day, slot]) => {
      const exists = rows.some((item) => String(item?.班级 || "") === className && String(item?.星期 || "") === day && String(item?.节次 || "") === slot && String(item?.学科 || "") === subject);
      if (!exists) rows.push({ 班级: className, 星期: day, 节次: slot, 学科: subject, 教师: teacher });
    });
    await api("/api/day-rules", { method: "POST", body: { table: "fixed_slots", rows, source: "rules.visual_timetable", reason: `课表式规则：${className}${subject}固定 ${selected.length} 格`, actor: "web" } });
  } else {
    const rows = asArray(state.dayRules?.subject_bans).map(stripRowIndex);
    selected.forEach(([day, slot]) => {
      const exists = rows.some((item) => String(item?.学科 || "") === subject && String(item?.星期 || "") === day && String(item?.节次 || "") === slot);
      if (!exists) rows.push({ 学科: subject, 星期: day, 节次: slot, 原因: "课表式规则设置" });
    });
    await api("/api/day-rules", { method: "POST", body: { table: "subject_bans", rows, source: "rules.visual_timetable", reason: `课表式规则：${subject}禁排 ${selected.length} 格`, actor: "web" } });
  }
  state.visualRuleSelectedCells = [];
  await loadAll({ silent: true });
  toast("课表规则已保存，并重新完成重合与矛盾检查");
}

function formalRuleSubnav() {
  return `<nav class="formal-subnav" aria-label="规则中心子菜单">${[
    ["assistant", "AI 助手"],
    ["visual", "课表设规则"],
    ["ruleset", "规则集"],
    ["checks", "规则检查"],
  ].map(([id, label]) => `<button type="button" class="${state.formalRuleSection === id ? "active" : ""}" data-action="set-formal-rule-section" data-section="${id}">${label}</button>`).join("")}</nav>`;
}

renderRulesView = function renderRulesViewFormal() {
  const custom = formalCustomRules();
  const all = formalAllRules();
  const hard = all.filter((rule) => rule.strength === "hard").length;
  const soft = all.filter((rule) => rule.strength === "soft").length;
  const system = all.filter((rule) => rule._source === "catalog" && rule.enabled !== false).length;
  const customActive = custom.filter((rule) => rule.status === "active" && rule.enabled !== false).length;
  const pending = custom.filter((rule) => ["draft", "needs_clarification", "validated"].includes(rule.status)).length;
  const examples = [
    "高三数学尽量安排在上午，周五第4节除外",
    "教师A周三尽量连续上课，若与固定活动冲突则以活动为准",
    "体育课尽量不安排在下午最后一节",
  ];
  const isParsing = state.formalRuleParsingTarget === "rules";
  const composerText = state.formalRuleInput || state.parsedRuleV2?.source?.text || "";
  const modeling = `<div class="rule-workbench rule-modeling-workbench"><div class="rule-main">
    <section class="ai-rule-composer">
        <div class="ai-rule-composer-head"><div><div class="ai-rule-composer-title"><span class="ai-badge">AI</span>先说一句学校自己的排课规则</div><p>像平时向排课老师交代工作一样描述即可，AI 会整理成可检查、可编辑的草案。</p></div><div class="ai-rule-boundary">AI 负责理解规则，不直接猜课表</div></div>
        <div class="ai-rule-composer-row"><textarea id="ruleV2Input" placeholder="例如：高三数学尽量安排在上午，周五第4节除外。" ${isParsing ? "disabled" : ""}>${escapeHtml(composerText)}</textarea><button type="button" data-action="parse-rule-v2" ${isParsing ? 'disabled aria-busy="true"' : ""}>${isParsing ? "AI 正在理解规则…" : "让 AI 生成规则草案"}</button></div>
        ${isParsing ? `<div class="ai-rule-running" role="status"><span class="ai-rule-spinner" aria-hidden="true"></span><span><strong>正在理解范围、时间与例外</strong><small>复杂规则可能需要 1–2 分钟，请勿重复提交。</small></span></div>` : ""}
        <div class="ai-rule-help-row"><button type="button" class="secondary ai-rule-help-button" data-action="toggle-rule-examples" aria-expanded="${state.formalRuleExamplesOpen ? "true" : "false"}">${state.formalRuleExamplesOpen ? "收起示例" : "查看规则示例"}</button></div>
        ${state.formalRuleExamplesOpen ? `<div class="ai-rule-examples" aria-label="规则描述示例">${examples.map((example) => `<button type="button" class="secondary" data-action="use-rule-example" data-example="${escapeAttr(example)}">${escapeHtml(example)}</button>`).join("")}</div>` : ""}
        <ol class="ai-rule-steps"><li><b>1</b><span><strong>AI 理解需求</strong>识别范围、时间与例外</span></li><li><b>2</b><span><strong>AI 整理规则</strong>判断必须满足或尽量满足</span></li><li><b>3</b><span><strong>教务确认</strong>确认后才会进入智能排课</span></li></ol>
      </section>
      ${formalRuleDraftPanel()}
    </div><aside class="rule-modeling-aside"><strong>AI 助手会做什么</strong><ol><li>理解教务自然语言</li><li>拆分必须满足、尽量满足和例外</li><li>明确作用对象与时间</li><li>检查系统是否能真正执行</li><li>列出局限与解决建议</li></ol><p>AI 不会跳过教务确认；只有当前用户确认的规则才会进入排课。</p></aside></div>`;
  const ruleset = `<section class="rule-set-page">
    <div class="rule-summary-bar"><div class="rule-summary-title"><span>当前规则集</span><strong>${formatNumber(all.length)}</strong></div><div class="rule-summary-metrics"><span>系统规则 <b>${system}</b></span><span>个性化 <b>${customActive}</b></span><span>硬规则 <b>${hard}</b></span><span>软规则 <b>${soft}</b></span><span class="${pending ? "needs-attention" : ""}">待确认 <b>${pending}</b></span></div><button type="button" data-action="new-rule-v2">新增规则</button></div>
    <div class="rule-domain-tabs">${[["course", "课程规则"], ["roster", "排班规则"]].map(([id, label]) => `<button type="button" class="${state.formalRuleDomain === id ? "active" : ""}" data-action="set-formal-rule-domain" data-domain="${id}">${label}</button>`).join("")}</div>
    <div class="rule-tabs">${[["basic", "基础规则"], ["teacher", "教师个性规则"], ["subject", "学科个性规则"]].map(([id, label]) => `<button type="button" class="${state.formalRuleCategory === id ? "active" : ""}" data-action="set-formal-rule-category" data-category="${id}">${label}</button>`).join("")}</div>
    <div class="rule-filters">${[["all", "全部"], ["hard", "必须满足"], ["soft", "尽量满足"], ["exceptions", "有例外"]].map(([id, label]) => `<button type="button" class="${state.formalRuleFilter === id ? "active" : ""}" data-action="set-formal-rule-filter" data-filter="${id}">${label}</button>`).join("")}<input class="rule-search" data-control="formal-rule-search" value="${escapeAttr(state.formalRuleSearch)}" placeholder="搜索规则、教师、班级或学科"></div>
    ${formalRuleCards()}
  </section>`;
  const checks = `<section class="rule-check-page"><div><h2>规则完整性检查</h2><p>集中检查作用范围、作用时间、例外情况和是否真正影响排课，不需要任何第三方确认。</p></div>${formalRuleChecks()}</section>`;
  const content = state.formalRuleSection === "ruleset" ? ruleset : state.formalRuleSection === "checks" ? checks : state.formalRuleSection === "visual" ? formalVisualRulePage() : modeling;
  return `${formalWorkflow("rules")}${formalRuleSubnav()}${content}`;
};

function formalSolveSubnav() {
  const blockerCount = Number(state.readiness?.summary?.blocking_errors || 0);
  const items = [
    ["workspace", "求解工作台", ""],
    ["blockers", "阻断审查", blockerCount ? String(blockerCount) : ""],
    ["optimization", "方案优化", formalHasUsableSchedule() ? "" : "待求解"],
  ];
  return `<nav class="formal-subnav solve-subnav" aria-label="求解与优化子菜单">${items.map(([id, label, badge]) => `<button type="button" class="${state.formalSolveSection === id ? "active" : ""}" data-action="set-formal-solve-section" data-section="${id}"><span>${label}</span>${badge ? `<b>${escapeHtml(badge)}</b>` : ""}</button>`).join("")}</nav>`;
}

function formalBlockerSignature() {
  const items = asArray(state.readiness?.items).filter((item) => ["error", "blocked"].includes(String(item?.severity || "")));
  return items.map((item) => `${item.title || item.domain || ""}:${item.detail || ""}`).join("|").slice(0, 1_500);
}

function formalMaybeOpenBlockerNotice() {
  const blockerCount = Number(state.readiness?.summary?.blocking_errors || 0);
  const root = $("modalRoot");
  const shell = $("appShell");
  if (!blockerCount || !root || !root.hidden || !shell || shell.hidden || document.body.classList.contains("auth-page")) return;
  const signature = formalBlockerSignature() || String(blockerCount);
  const key = `scheduler.blockerNotice.v1.${signature}`;
  try {
    if (sessionStorage.getItem(key) === "1") return;
    sessionStorage.setItem(key, "1");
  } catch (_) {
  }
  formalGuideReturnFocus = document.activeElement;
  root.hidden = false;
  root.innerHTML = `<div class="formal-blocker-notice" role="dialog" aria-modal="true" aria-labelledby="formalBlockerNoticeTitle">
    <span class="blocker-notice-mark">!</span>
    <div><small>全局阻断提醒 · 仅提示一次</small><h2 id="formalBlockerNoticeTitle">发现 ${blockerCount} 个必须先处理的排课问题</h2><p>已为阻断项设置独立审查页。进入后，AI 会列出现有局限并给出可执行的解决建议。</p></div>
    <footer><button type="button" class="secondary" data-action="close-page-hint">稍后处理</button><button type="button" data-action="open-blocker-review">查看阻断审查</button></footer>
  </div>`;
}

function formalBlockingItems() {
  const readinessItems = asArray(state.readiness?.items)
    .filter((item) => ["error", "blocked", "warning"].includes(String(item?.severity || "")));
  const aiItems = asArray(state.aiBlockReview?.items);
  return readinessItems.map((item, index) => {
    const exact = aiItems.find((candidate) => String(candidate.source_title || "") === String(item.title || item.domain || ""));
    const reviewed = exact || aiItems[index] || {};
    return {
      title: item.title || item.domain || "排课阻断项",
      severity: item.severity || "warning",
      limitation: reviewed.limitation || item.detail || "当前数据或规则尚不满足求解条件。",
      solution: reviewed.solution || item.suggestion || "补齐对应数据或调整规则后重新检查。",
      priority: reviewed.priority || (["error", "blocked"].includes(String(item.severity || "")) ? "必须先处理" : "建议处理"),
      solvability: reviewed.solvability || "处理后重新运行求解前检查",
    };
  });
}

async function formalLoadAiBlockReview() {
  if (state.aiBlockReviewLoading) return;
  state.aiBlockReviewLoading = true;
  renderShell();
  try {
    state.aiBlockReview = await api("/api/readiness/ai-review", {
      method: "POST",
      body: { mode: state.solveMode || "joint" },
    });
  } finally {
    state.aiBlockReviewLoading = false;
    renderShell();
  }
}

function formalBlockerReviewPage() {
  const items = formalBlockingItems();
  const blockers = items.filter((item) => ["error", "blocked"].includes(String(item.severity || ""))).length;
  const aiUsed = state.aiBlockReview?.ai_used === true;
  const statusText = state.aiBlockReviewLoading
    ? "AI 正在分析现有局限与处理路径…"
    : aiUsed
      ? "AI 已逐项分析阻断项"
      : state.aiBlockReview
        ? "AI 本次未完成分析，已保留系统建议"
        : "等待 AI 生成处理建议";
  return `<section class="blocker-review-page">
    <header class="blocker-review-head"><div><span>阻断审查</span><h2>${blockers ? `${blockers} 个问题会阻止正式求解` : "当前没有阻止求解的问题"}</h2><p>${escapeHtml(state.aiBlockReview?.summary || "页面先展示系统校验事实；AI 会在此基础上说明当前局限、影响和解决建议。")}</p></div><div class="blocker-review-actions"><button type="button" class="secondary" data-action="refresh-readiness">重新检查</button><button type="button" data-action="refresh-ai-block-review" ${state.aiBlockReviewLoading ? "disabled" : ""}>${state.aiBlockReviewLoading ? "AI 分析中…" : state.aiBlockReview ? "重新生成 AI 建议" : "AI 生成解决建议"}</button></div></header>
    <div class="ai-review-status ${aiUsed ? "ready" : state.aiBlockReviewLoading ? "running" : "fallback"}"><span class="ai-badge">AI</span><strong>${escapeHtml(statusText)}</strong><small>AI 只解释局限并生成处理建议，不会擅自修改规则或课表。</small></div>
    <div class="blocker-review-list">${items.map((item, index) => `<article class="blocker-review-card ${severityTone(item.severity)}">
      <div class="blocker-card-index">${String(index + 1).padStart(2, "0")}</div>
      <div class="blocker-card-body"><header><h3>${escapeHtml(item.title)}</h3><span>${escapeHtml(item.priority)}</span></header>
        <div class="blocker-pair"><section><small>现有局限</small><p>${escapeHtml(safeOperationalText(item.limitation))}</p></section><section><small>解决建议</small><p>${escapeHtml(safeOperationalText(item.solution))}</p></section></div>
        <footer>${escapeHtml(item.solvability)}</footer>
      </div>
    </article>`).join("") || `<div class="empty-state">当前没有需要审查的阻断项。</div>`}</div>
    <div class="solve-footer"><span>处理完成后重新检查；只有阻断数为 0 时才能启动正式求解。</span><div><button type="button" class="secondary" data-action="set-formal-solve-section" data-section="workspace">返回求解工作台</button></div></div>
  </section>`;
}

function formalSolveTimeline(status) {
  const timeline = asArray(status.phase_timeline);
  const labels = ["检查数据与规则", "应用排课规则", "寻找可行方案", "改善课表质量", "生成结果文件"];
  const details = ["检查基础数据", "应用排课规则", "寻找首个可用课表", "优化可调整规则", "整理预览与下载文件"];
  const fallback = labels.map((label, index) => ({ label, status: index === 0 ? "active" : "pending" }));
  const items = timeline.length ? timeline : fallback;
  return `<ol class="solve-phase-line" aria-label="求解阶段">${items.map((item, index) => `<li class="solve-phase-item ${escapeAttr(item.status || "pending")}"><b>${item.status === "completed" ? "✓" : item.status === "failed" ? "!" : index + 1}</b><div><strong>${escapeHtml(item.label)}</strong><span>${escapeHtml(item.status === "failed" ? "任务在此中止" : details[index] || "等待执行")}</span></div></li>`).join("")}</ol>`;
}

function formalSolveRuntime(status) {
  const timeline = asArray(status.phase_timeline);
  const index = Math.max(0, timeline.findIndex((item) => ["active", "failed"].includes(String(item.status || ""))));
  const total = timeline.length || 5;
  const failed = String(status.status || "") === "failed";
  const pct = Math.round(((index + 1) / total) * 100);
  return `<div class="solve-runtime-strip ${failed ? "failed" : ""}" aria-live="polite">
    <div><span>${failed ? "中止阶段" : "当前阶段"}</span><strong>${index + 1} / ${total} · ${escapeHtml(timeline[index]?.label || status.phase_label || "等待启动")}</strong></div>
    <div class="solve-runtime-clock"><span>${failed ? "本次用时" : "已用时"}</span>${solveClockMarkup(status)}</div>
    <div class="solve-runtime-progress"><span>阶段进度 ${pct}%</span><div><i style="width:${pct}%"></i></div></div>
  </div>`;
}

function formalSolveMetrics(status) {
  const assessment = status.publish_assessment?.summary || {};
  const result = status.result || {};
  const metrics = [
    ["当前状态", status.phase_label || solveStatusLabel(status.status)],
    ["硬规则冲突", formatNumber(assessment.errors || status.hard_conflicts || 0)],
    ["软规则代价", formatNumber(status.objective_value ?? result.objective_value ?? status.best_objective ?? 0)],
    ["已发现候选", formatNumber(status.solution_count ?? result.solution_count ?? 0)],
    ["状态更新时间", Number(status.last_update_seconds || 0) < 8 ? "刚刚" : `${formatDuration(status.last_update_seconds)}前`],
  ];
  return `<div class="solve-metric-strip">${metrics.map(([label, value]) => `<div class="solve-metric"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`).join("")}</div>`;
}

function formalSolveEvents(status) {
  const rows = asArray(status.phase_timeline).filter((item) => item.status !== "pending").map((item) => [item.status === "failed" ? "中止" : item.status === "active" ? "当前" : "完成", item.label]);
  if (!rows.length) rows.push(["等待", status.message || "尚未开始求解"]);
  return rows.slice(-5).map(([time, label]) => `<div class="solve-event-row"><span>${escapeHtml(time)}</span><strong>${escapeHtml(label)}</strong></div>`).join("");
}

function formalSolveInputFacts() {
  const classes = state.teachers.length;
  const teachers = new Set(state.teachers.flatMap((row) => Object.entries(row || {}).filter(([key]) => !["班级", "班主任性别"].includes(key)).map(([, value]) => String(value || "").trim()).filter(Boolean))).size;
  const tasks = asArray(state.dayRules?.subject_hours).reduce((sum, row) => sum + Number(row?.周中课时 || 0) + Number(row?.周末课时 || 0) + Number(row?.早自习课时 || 0), 0);
  const modelStats = asObject(state.readiness?.modeling?.stats);
  return [["基础数据", "已确认"], ["规则版本", `v${state.rulesV2?.revision || 0}`], ["规则应用", state.readiness?.modeling?.ready ? "已通过" : "未通过"], ["周课时标准", tasks || asArray(state.dayRules?.subject_hours).length], ["教师", teachers], ["班级", classes]];
}

function formalSolveRunning() {
  const status = state.solveStatus || {};
  if ($("pageTitle")) $("pageTitle").textContent = "AI 智能排课";
  if ($("pageSubtitle")) $("pageSubtitle").textContent = "工业级智能排课引擎正在检查规则、寻找可行方案并执行全局优化。";
  return `<section class="solve-engine-card"><div class="solve-engine-head"><div class="solve-engine-mark" role="img" aria-label="求解中"><i class="ri-loader-4-line" aria-hidden="true"></i></div><div><h2>${escapeHtml(status.phase_label || "工业级求解引擎正在运行")}</h2><p>${escapeHtml(status.message || "正在校验规则、寻找可行方案并执行全局优化。")}</p></div><div class="solve-engine-badges"><span class="pill warning">${escapeHtml(solveStatusLabel(status.status))}</span><span class="engine-badge">工业级求解引擎</span></div></div>${formalSolveRuntime(status)}${formalSolveTimeline(status)}</section>${formalSolveMetrics(status)}<div class="solve-lower-grid"><section class="formal-card solve-detail-card"><h3>求解动态</h3>${formalSolveEvents(status)}</section><section class="formal-card solve-detail-card"><h3>本次求解依据</h3><div class="solve-input-list">${formalSolveInputFacts().map(([label, value]) => `<div class="solve-input-item"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`).join("")}</div></section></div><div class="solve-footer"><span>只有生成无硬规则冲突的可行方案后，才会进入方案审查与优化。</span><div><button type="button" class="secondary" data-action="stop-solve">停止求解</button><button type="button" data-view-jump="overview">返回项目概览</button></div></div>`;
}

function formalSolveFailure() {
  const status = state.solveStatus || {};
  const failure = asObject(status.failure);
  if ($("pageTitle")) $("pageTitle").textContent = "AI 智能排课";
  if ($("pageSubtitle")) $("pageSubtitle").textContent = "本次任务已停止，系统已定位中止阶段并保留任务记录。";
  return `<section class="solve-engine-card solve-failure-card"><div class="solve-engine-head"><div class="solve-engine-mark" role="img" aria-label="求解未完成"><i class="ri-error-warning-line" aria-hidden="true"></i></div><div><h2>${escapeHtml(failure.title || "求解未完成")}</h2><p>${escapeHtml(failure.message || status.message || "本次排课已中止，请重新排课。")}</p></div><div class="solve-engine-badges"><span class="pill error">未完成</span><span class="engine-badge">已保留记录</span></div></div>${formalSolveRuntime(status)}${formalSolveTimeline(status)}</section>
    <section class="solve-failure-actions"><div><strong>下一步怎么做</strong><span>当前故障已修复。重新启动后，页面会持续显示阶段、计时和状态更新。</span></div><div><button type="button" class="secondary" data-action="set-formal-solve-section" data-section="blockers">查看阻断审查</button><button type="button" data-action="start-solve">${escapeHtml(failure.action || "重新启动 AI 智能排课")}</button></div></section>
    ${isAdminRole() ? `<details class="solve-technical-detail admin-only"><summary>管理员诊断信息</summary><code>${escapeHtml(failure.technical_detail || status.error?.message || "未记录诊断详情")}</code></details>` : ""}`;
}

function formalSolvePreflight() {
  const summary = state.readiness?.summary || {};
  const previousResultUnverified = String(state.solveStatus?.status || "") === "completed" && !formalHasUsableSchedule();
  if ($("pageTitle")) $("pageTitle").textContent = "AI 智能排课";
  if ($("pageSubtitle")) $("pageSubtitle").textContent = "AI 帮助理解复杂规则，工业级求解引擎负责生成并持续优化课表。";
  const canStart = Boolean(summary.can_start_solver);
  const headline = previousResultUnverified ? "上一轮结果无法在当前项目中核验，请重新排课" : canStart ? "基础数据和规则已可进入智能排课" : "完成阻断项后再启动智能排课";
  const message = previousResultUnverified ? "系统不会把旧文件或不可访问的结果当作正式课表。重新排课后，只有可以在线查看的方案才会进入审查与发布。" : (summary.message || "系统会先检查数据与规则，再寻找可行方案并持续改善课表质量。");
  const blockerCount = Number(summary.blocking_errors || 0);
  return `<div class="solve-preflight"><section class="formal-card solve-start-card"><div class="solve-start-copy"><span class="engine-badge">工业级求解引擎</span><h2>${escapeHtml(headline)}</h2><p>${escapeHtml(message)}</p><div class="solve-start-actions"><button type="button" data-action="start-solve" ${canStart ? "" : "disabled"}>${previousResultUnverified ? "重新启动 AI 智能排课" : "启动 AI 智能排课"}</button><button type="button" class="secondary" data-action="refresh-readiness">重新检查规则</button></div></div><div class="solve-bridge" aria-label="AI 排课工作原理"><article><b>1</b><div><strong>AI 理解复杂规则</strong><span>整理范围、时间、例外和软硬要求</span></div></article><article><b>2</b><div><strong>系统确认规则生效</strong><span>没有实际影响的规则会在这里被拦下</span></div></article><article><b>3</b><div><strong>工业级全局优化</strong><span>输出候选课表、冲突说明和版本记录</span></div></article></div><div class="solve-preflight-facts"><div class="solve-facts-head"><strong>本次排课输入</strong><span>启动后锁定版本，结果可追溯</span></div><div class="solve-fact-grid">${formalSolveInputFacts().map(([label, value]) => `<div><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`).join("")}</div></div><p class="solve-boundary-note">AI 负责理解和拆分复杂要求；系统确认规则真正生效后，工业级求解引擎才会启动。当前用户负责确认规则，不需要第三方审批。</p></section><aside class="solve-blocker-entry ${blockerCount ? "blocked" : "ready"}"><span>${blockerCount ? "阻断" : "通过"}</span><strong>${blockerCount ? `${blockerCount} 个必须处理项` : "排课前检查已通过"}</strong><p>${blockerCount ? "阻断项已移到独立审查页，AI 会说明现有局限并给出解决建议。" : "每条启用规则都已确认能够实际影响排课，可以启动工业级求解。"}</p><button type="button" class="${blockerCount ? "" : "secondary"}" data-action="set-formal-solve-section" data-section="blockers">${blockerCount ? "打开阻断审查" : "查看检查结果"}</button></aside></div>`;
}

function formalReviewPreview() {
  if (typeof renderSchedulePreviewCard === "function") return renderSchedulePreviewCard();
  return `<section class="formal-card review-panel"><h3>课表预览</h3><div class="empty-state">当前结果没有可在线预览的课表。</div></section>`;
}

function formalPremiumConversationEntry() {
  return `<section class="premium-optimization-entry"><div><span>高级会员</span><strong>进入完整 AI 对话调优</strong><p>自动带入当前候选、规则版本和诊断结果；AI 会继续追问、整理规则并重新排课。</p></div><button type="button" data-action="open-conversation-optimization">用对话继续调优</button></section>`;
}

function formalReviewPage() {
  const status = state.solveStatus || {};
  if ($("pageTitle")) $("pageTitle").textContent = "方案审查与优化";
  if ($("pageSubtitle")) $("pageSubtitle").textContent = "比较候选方案，让 AI 解释问题并生成调整规则，再交给工业级求解引擎继续优化。";
  const assessment = status.publish_assessment || {};
  const summary = assessment.summary || {};
  const gates = asArray(assessment.gates).filter((gate) => gate.severity !== "ok").slice(0, 4);
  const preview = state.resultPreview || {};
  const classCount = asArray(preview.class_views).length;
  const metrics = [["硬规则冲突", summary.errors || 0], ["发布提醒", summary.warnings || 0], ["班级课表", classCount], ["候选解", status.solution_count || 0], ["发布状态", summary.status_label || "待评估"]];
  return `<div class="review-candidate-tabs"><button type="button" class="active">当前推荐方案</button><button type="button">历史候选</button><button type="button">对比方案</button></div><div class="review-score-strip">${metrics.map(([label, value]) => `<div><span>${escapeHtml(label)}</span><strong>${escapeHtml(formatNumber(value, String(value)))}</strong></div>`).join("")}</div><div class="review-grid"><div>${formalReviewPreview()}</div><section class="formal-card review-panel review-ai"><h3>AI 诊断与调整</h3><div class="formal-rule-table" style="margin-bottom:14px">${gates.map((gate) => `<div class="formal-rule-row" style="grid-template-columns:1.6fr .55fr .45fr;min-width:0"><span>${escapeHtml(gate.title || gate.domain || "待检查问题")}</span><span class="pill ${severityTone(gate.severity)}">${escapeHtml(gate.severity === "error" ? "高" : "提醒")}</span><span>${escapeHtml(gate.suggestion ? "调整" : "查看")}</span></div>`).join("") || `<div class="empty-state">当前没有发布阻断问题。</div>`}</div><label for="optimizationInput"><strong>告诉 AI 你想怎么改</strong></label><textarea id="optimizationInput" placeholder="例如：教师A周三尽量连续上课；高三数学周五下午只保留 1 节。">${escapeHtml(state.optimizationRuleV2?.source?.text || "")}</textarea>${state.optimizationRuleV2 ? `<div class="rule-draft-meta"><span>${escapeHtml(state.optimizationRuleV2.title)}</span><span>${state.optimizationRuleV2.validation?.valid ? "已通过规则检查" : "需要澄清"}</span><span>${state.optimizationRuleV2.solver_support?.status === "supported" ? "可以执行" : "暂不支持"}</span></div>` : ""}<div class="review-actions"><button type="button" class="secondary" data-action="parse-optimization-rule">先检查规则草稿</button><button type="button" data-action="confirm-rule-and-optimize" ${state.optimizationRuleV2?.validation?.valid && state.optimizationRuleV2?.solver_support?.status === "supported" ? "" : "disabled"}>我确认规则并继续优化</button></div><p class="ai-rule-hint">当前用户确认后会生成规则集新版本，并由工业级求解引擎重新求解；AI 不直接猜课表。</p></section></div>${formalPremiumConversationEntry()}<div class="solve-footer"><span>基础数据已确认 / 规则 v${state.rulesV2?.revision || 0}</span><div><button type="button" class="secondary" data-action="continue-solve">继续改善当前候选</button><button type="button" data-view-jump="results">进入课表发布</button></div></div>`;
}

renderSolveView = function renderSolveViewFormal() {
  const currentStage = state.formalSolveSection === "optimization" && formalHasUsableSchedule() ? "review" : "solve";
  let content;
  if (state.formalSolveSection === "blockers") content = formalBlockerReviewPage();
  else if (state.formalSolveSection === "optimization") {
    content = formalHasUsableSchedule()
      ? formalReviewPage()
      : `<section class="formal-card optimization-empty"><h2>先生成候选课表，再进入方案优化</h2><p>当前还没有可核验的候选课表。请先处理阻断项并在求解工作台启动工业级求解。</p><button type="button" data-action="set-formal-solve-section" data-section="workspace">返回求解工作台</button></section>`;
  } else if (isRunningStatus()) content = formalSolveRunning();
  else if (String(state.solveStatus?.status || "") === "failed") content = formalSolveFailure();
  else content = formalSolvePreflight();
  return `${formalWorkflow(currentStage)}${formalSolveSubnav()}${content}`;
};

function formalPublishFiles() {
  const files = asArray(state.solveStatus?.files);
  const schedule = files.filter((file) => file.category === "schedule" || /课表|schedule/i.test(String(file.label || file.path || file.name || "")));
  return { files, schedule };
}

function formalPublishGates() {
  const gates = asArray(state.solveStatus?.publish_assessment?.gates).slice();
  if (!formalHasUsableSchedule()) gates.unshift({ title: "可在线核验的课表文件", severity: "error" });
  const visible = gates.length ? gates.slice(0, 7) : [
    { title: "规则已由当前用户确认", severity: "info" },
    { title: "数据版本", severity: "info" },
    { title: "规则版本", severity: "info" },
    { title: "无过期修改", severity: "info" },
  ];
  return visible.map((gate) => `<div class="publish-gate"><span>${escapeHtml(gate.title || gate.domain || "发布检查")}</span><strong style="color:${gate.severity === "error" ? "var(--formal-red)" : gate.severity === "warning" ? "var(--formal-amber)" : "var(--formal-green)"}">${gate.severity === "error" ? "未通过" : gate.severity === "warning" ? "需确认" : "通过"}</strong></div>`).join("");
}

renderResultsView = function renderResultsViewFormal() {
  const status = state.solveStatus || {};
  const publishSummary = status.publish_assessment?.summary || {};
  const hasUsableSchedule = formalHasUsableSchedule();
  const canPublish = hasUsableSchedule && publishSummary.status === "ready" && publishSummary.can_publish === true;
  const current = state.projectState?.publish?.current;
  const projectSettings = formalCurrentProjectSettings();
  const version = current?.version || `课表 V${(state.projectState?.publish?.count || 0) + 1}`;
  const gateMessage = hasUsableSchedule ? (publishSummary.message || "先完成求解和发布评估。") : "当前候选缺少可在线核验的课表文件，请重新求解并生成结果包。";
  return `${formalWorkflow("publish")}${canPublish ? `<div class="publish-approved"><div><strong>当前候选已通过发布门禁</strong><div>${escapeHtml(publishSummary.message || "硬规则、配置版本与结果材料检查通过。")}</div></div><button type="button" class="secondary" data-view-jump="solve">返回方案优化</button></div>` : `<div class="publish-approved warning"><div><strong>发布前仍需处理</strong><div>${escapeHtml(gateMessage)}</div></div><button type="button" class="secondary" data-view-jump="solve">返回求解与优化</button></div>`}
    <section class="publish-download-panel">
      <div><span>课表下载</span><h2>按使用对象选择课表</h2><p>班级、教师和教务总表分别下载；每一类都可以选择 PDF 或 Excel。</p></div>
      <div class="publish-download-groups">${[["class", "班级课表", "按班级分表，适合张贴"], ["teacher", "教师课表", "按教师分表，适合个人查看"], ["academic", "教务总表", "沿用原项目完整工作簿"]].map(([view, label, note]) => `<article><div><strong>${label}</strong><small>${note}</small></div><div><button type="button" class="secondary" data-action="download-result-view" data-export-view="${view}" data-export-format="pdf" ${hasUsableSchedule ? "" : "disabled"}>PDF</button><button type="button" data-action="download-result-view" data-export-view="${view}" data-export-format="xlsx" ${hasUsableSchedule ? "" : "disabled"}>Excel</button></div></article>`).join("")}</div>
    </section>
    <div class="publish-grid"><section class="formal-card publish-card"><h2>版本信息</h2><div class="publish-options"><div class="publish-check-list"><label><span>班级课表</span><span>${formatNumber(asArray(state.resultPreview?.class_views).length)} 份</span></label><label><span>教师课表</span><span>${formatNumber(asArray(state.resultPreview?.teacher_views).length)} 份</span></label><label><span>总课表</span><span>${hasUsableSchedule ? "已生成" : "待生成"}</span></label></div><div class="publish-check-list"><label><span>规则确认</span><span>当前用户</span></label><label><span>结果状态</span><span>${hasUsableSchedule ? "可下载" : "待排课"}</span></label><label><span>发布记录</span><span>自动留痕</span></label></div></div><div class="publish-field-grid"><div class="field-group"><label for="publishVersion">版本</label><input id="publishVersion" value="${escapeAttr(version)}"></div><div class="field-group"><label for="publishTerm">生效学期</label><input id="publishTerm" value="${escapeAttr(projectSettings.term_name)}"></div><div class="field-group"><label for="publishDate">生效日期</label><input id="publishDate" type="date" value="${escapeAttr(projectSettings.term_start)}"></div></div><div class="field-group publish-note"><label for="publishNote">发布说明</label><textarea id="publishNote" placeholder="例如：第一版正式课表；临时调整请在教务系统中留痕。">${escapeHtml(current?.note || "")}</textarea></div><div class="publish-primary-actions"><button type="button" class="secondary" data-action="download-package" ${hasUsableSchedule ? "" : "disabled"}>下载完整结果包</button><button type="button" data-action="publish-candidate" ${canPublish ? "" : "disabled"}>记录为正式版本</button></div></section><aside class="formal-card publish-card"><h2>发布前检查</h2><div class="publish-gate-list">${formalPublishGates()}</div><div class="publish-history"><h3>最近发布记录</h3>${asArray(state.projectState?.publish?.records).slice(-3).reverse().map((record) => `<div class="publish-history-row"><strong>${escapeHtml(record.version)}</strong><span>${escapeHtml(record.published_at || "")} · ${escapeHtml(record.published_by || "")}</span></div>`).join("") || `<p>尚无正式发布记录。</p>`}</div></aside></div>`;
};

function formalRuleForEditor(ruleId) {
  return formalCustomRules().find((rule) => rule.id === ruleId) || state.parsedRuleV2 || {
    id: "",
    title: "新规则",
    description: "",
    policy_level: "special",
    business_domain: state.formalRuleDomain || "course",
    rule_category: state.formalRuleCategory || "basic",
    strength: "soft",
    status: "draft",
    enabled: true,
    scope: { grades: [], classes: [], subjects: [], teachers: [], rooms: [], exclude: {} },
    effective_time: { mode: "project_term", term_id: "current", week_pattern: "all", days: [], slots: [] },
    exceptions: [],
    constraint: { type: "prefer_period", params: { period: "morning" } },
    solver_support: { status: "supported", compiler: "day.rule_v2.v1" },
    confirmation: { required: true, confirmed: false },
    weight: 300,
  };
}

function formalOpenRuleEditor(ruleId = "") {
  const rule = formalRuleForEditor(ruleId);
  const scope = rule.scope || {};
  const time = rule.effective_time || {};
  const exception = asArray(rule.exceptions)[0] || {};
  const params = rule.constraint?.params || {};
  const domain = rule.business_domain || state.formalRuleDomain || "course";
  const category = rule.rule_category || state.formalRuleCategory || "basic";
  const type = rule.constraint?.type || "prefer_period";
  const parameter = type === "max_daily_lessons" ? params.max || 2 : type === "prefer_period" ? params.period || "morning" : type === "catalog_ref" ? rule.constraint?.catalog_id || "" : "";
  const modal = $("modalRoot");
  modal.innerHTML = `<div class="formal-rule-modal simple-rule-editor" role="dialog" aria-modal="true" aria-labelledby="formalEditorTitle">
    <div class="formal-modal-head"><div><span class="editor-kicker">规则编辑</span><h2 id="formalEditorTitle">${escapeHtml(rule.title || "新增规则")}</h2><p>只填写教务含义；保存后系统会重新检查这条规则能否真正影响排课。</p></div><button type="button" class="secondary" data-action="close-modal">关闭</button></div>
    <div class="simple-editor-body"><main class="formal-editor-form">
      <section class="simple-editor-section"><div class="simple-section-title"><b>1</b><div><h3>这条规则要求什么</h3><p>名称简短，说明写清楚实际教务要求。</p></div></div><div class="editor-grid"><div class="field-group"><label for="formalRuleTitle">规则名称</label><input id="formalRuleTitle" value="${escapeAttr(rule.title || "")}" placeholder="例如：高三数学优先排上午"></div><div class="field-group"><label for="formalRuleDescription">具体要求</label><textarea id="formalRuleDescription" placeholder="用教务语言描述，不需要写代码">${escapeHtml(rule.description || rule.source?.text || "")}</textarea></div></div></section>
      <section class="simple-editor-section"><div class="simple-section-title"><b>2</b><div><h3>规则归类与执行方式</h3><p>“必须满足”会阻止违反规则的课表；“尽量满足”会参与优化评分。</p></div></div><div class="editor-grid three"><div class="field-group"><label>所属模块</label><select id="formalBusinessDomain"><option value="course" ${domain === "course" ? "selected" : ""}>课程规则</option><option value="roster" ${domain === "roster" ? "selected" : ""}>排班规则</option></select></div><div class="field-group"><label>规则对象</label><select id="formalRuleCategory"><option value="basic" ${category === "basic" ? "selected" : ""}>基础规则</option><option value="teacher" ${category === "teacher" ? "selected" : ""}>教师个性规则</option><option value="subject" ${category === "subject" ? "selected" : ""}>学科个性规则</option></select></div><div class="field-group"><label>软硬规则</label><select id="formalRuleStrength"><option value="hard" ${rule.strength === "hard" ? "selected" : ""}>必须满足（硬规则）</option><option value="soft" ${rule.strength !== "hard" ? "selected" : ""}>尽量满足（软规则）</option></select></div><div class="field-group"><label>系统如何执行</label><select id="formalConstraintType">${[["teacher_unavailable", "指定教师在指定时间不排课"], ["prefer_period", "优先或要求安排在指定时段"], ["max_daily_lessons", "教师每天最多安排若干节"], ["catalog_ref", "沿用这条基础规则"]].map(([value, label]) => `<option value="${value}" ${type === value ? "selected" : ""}>${label}</option>`).join("")}</select></div>${type === "catalog_ref" ? `<input id="formalConstraintParam" type="hidden" value="${escapeAttr(parameter)}"><div class="field-group editor-span-2"><label>调整说明</label><div class="protected-rule-note">基础安全规则仍然有效；你可以在下方补充适用范围、时间和例外。</div></div>` : `<div class="field-group editor-span-2"><label>具体时段或课时上限</label><input id="formalConstraintParam" value="${escapeAttr(parameter)}" placeholder="例如：上午；每天最多 2 节"></div>`}</div></section>
      <section class="simple-editor-section"><div class="simple-section-title"><b>3</b><div><h3>对谁、在什么时候生效</h3><p>留空表示全校；未指定时间时默认整个当前学期。</p></div></div><div class="editor-grid four"><div class="field-group"><label>年级</label><input id="formalScopeGrades" value="${escapeAttr(asArray(scope.grades).join("、"))}" placeholder="例如：高三"></div><div class="field-group"><label>学科</label><input id="formalScopeSubjects" value="${escapeAttr(asArray(scope.subjects).join("、"))}" placeholder="例如：数学"></div><div class="field-group"><label>班级</label><input id="formalScopeClasses" value="${escapeAttr(asArray(scope.classes).join("、"))}" placeholder="例如：高三1班"></div><div class="field-group"><label>教师</label><input id="formalScopeTeachers" value="${escapeAttr(asArray(scope.teachers).join("、"))}" placeholder="例如：教师001"></div><div class="field-group"><label>作用时间</label><select id="formalTimeMode"><option value="project_term" ${time.mode !== "date_range" ? "selected" : ""}>整个当前学期</option><option value="date_range" ${time.mode === "date_range" ? "selected" : ""}>指定日期范围</option></select></div><div class="field-group"><label>周次</label><select id="formalWeekPattern" disabled><option value="all" selected>每周相同（当前默认）</option></select><small>大小周暂未开放</small></div><div class="field-group"><label>星期</label><input id="formalTimeDays" value="${escapeAttr(asArray(time.days).join("、"))}" placeholder="例如：星期一、星期三"></div><div class="field-group"><label>节次</label><input id="formalTimeSlots" value="${escapeAttr(asArray(time.slots).join("、"))}" placeholder="例如：上午1、第4节"></div></div></section>
      <details class="simple-editor-exceptions" ${asArray(rule.exceptions).length ? "open" : ""}><summary>例外情况（可选）</summary><p>只有确有例外时再展开填写。</p><div class="editor-grid four"><div class="field-group"><label>例外星期</label><input id="formalExceptionDays" value="${escapeAttr(asArray(exception.days).join("、"))}" placeholder="例如：星期五"></div><div class="field-group"><label>例外节次</label><input id="formalExceptionSlots" value="${escapeAttr(asArray(exception.slots).join("、"))}" placeholder="例如：第4节"></div><div class="field-group"><label>处理方式</label><select id="formalExceptionMode"><option value="exclude" ${exception.mode !== "soften" ? "selected" : ""}>例外时间不应用</option><option value="soften" ${exception.mode === "soften" ? "selected" : ""}>例外时间改为尽量满足</option></select></div><div class="field-group"><label>说明</label><input id="formalExceptionNote" value="${escapeAttr(exception.note || "")}" placeholder="填写原因"></div></div></details>
    </main><aside class="formal-editor-checks"><h3>保存后会发生什么</h3><ol class="editor-outcome-list"><li><b>重新检查</b><span>检查范围、时间、例外和软硬属性</span></li><li><b>等待当前用户确认</b><span>系统不要求任何第三方审批</span></li><li><b>真正应用到排课</b><span>确认这条规则会影响候选课表</span></li><li><b>不能应用则阻断</b><span>只有展示卡、没有实际影响的规则不能开跑</span></li></ol><div class="editor-impact"><strong>${formatNumber(formalAffectedTaskEstimate(rule))}</strong><span>个教学任务预计受影响</span></div></aside></div>
    <div class="formal-modal-actions"><span>保存不会立即求解，也不会覆盖已发布课表。</span><div><button type="button" class="secondary" data-action="close-modal">取消</button><button type="button" data-action="save-rule-v2-editor" data-rule-id="${escapeAttr(rule.id || "")}">保存并重新检查</button></div></div></div>`;
  modal.hidden = false;
}

function formalAffectedTaskEstimate(rule) {
  const scope = rule.scope || {};
  const classes = asArray(scope.classes).length || state.teachers.length || 1;
  const subjects = asArray(scope.subjects).length || 1;
  return Math.min(9999, classes * subjects);
}

function formalOpenMandatoryRuleWarning(ruleId) {
  const rule = formalCatalogRules().find((item) => item.id === ruleId);
  if (!rule) throw new Error("未找到这条基础规则");
  const root = $("modalRoot");
  root.hidden = false;
  root.innerHTML = `<div class="mandatory-rule-warning" role="dialog" aria-modal="true" aria-labelledby="mandatoryRuleWarningTitle"><i class="ri-shield-keyhole-line" aria-hidden="true"></i><div><span>基础安全规则</span><h2 id="mandatoryRuleWarningTitle">调整前请先确认影响</h2><p>“${escapeHtml(rule.title)}”用于保证课表可执行。它不能被直接关闭；你可以补充学校适用范围、时间或例外，保存后系统会重新检查是否仍能排出有效课表。</p><ul><li>调整可能让当前候选课表失效</li><li>保存后必须重新检查并由教务确认</li><li>与其他规则冲突时不会进入排课</li></ul><footer><button type="button" class="secondary" data-action="close-modal">暂不调整</button><button type="button" data-action="continue-edit-mandatory-rule" data-rule-id="${escapeAttr(ruleId)}">我已了解，继续调整</button></footer></div></div>`;
}

function formalContinueMandatoryRuleEdit(ruleId) {
  const rule = formalCatalogRules().find((item) => item.id === ruleId);
  if (!rule) throw new Error("未找到这条基础规则");
  state.parsedRuleV2 = {
    id: `adjust.${String(rule.id).replace(/[^a-zA-Z0-9_.-]+/g, "-")}.${Date.now()}`,
    title: `${rule.title}（学校调整）`,
    description: rule.description || "",
    policy_level: "schoolwide",
    business_domain: rule.business_domain || "course",
    rule_category: rule.rule_category || "basic",
    strength: "hard",
    status: "draft",
    enabled: true,
    scope: { grades: [], classes: [], subjects: [], teachers: [], rooms: [], exclude: {} },
    effective_time: { mode: "project_term", term_id: "current", week_pattern: "all", days: [], slots: [] },
    exceptions: [],
    constraint: { type: "catalog_ref", catalog_id: rule.id, params: {} },
    solver_support: { status: "supported", compiler: "day.rule_v2.v1" },
    confirmation: { required: true, confirmed: false },
    weight: 1000,
  };
  closeModal();
  formalOpenRuleEditor(state.parsedRuleV2.id);
}

function formalListValue(id) {
  return String($(id)?.value || "").split(/[、,，/\n]+/).map((item) => item.trim()).filter(Boolean);
}

function formalRuleFromEditor(original) {
  const type = $("formalConstraintType")?.value || "prefer_period";
  const param = String($("formalConstraintParam")?.value || "").trim();
  const exceptionDays = formalListValue("formalExceptionDays");
  const exceptionSlots = formalListValue("formalExceptionSlots");
  return {
    ...original,
    title: $("formalRuleTitle")?.value.trim() || "未命名规则",
    description: $("formalRuleDescription")?.value.trim() || "",
    business_domain: $("formalBusinessDomain")?.value || "course",
    rule_category: $("formalRuleCategory")?.value || "basic",
    policy_level: ({ basic: "schoolwide", teacher: "special", subject: "grade_subject" })[$("formalRuleCategory")?.value || "basic"],
    strength: $("formalRuleStrength")?.value || "soft",
    status: original.status === "active" ? "draft" : (original.status || "draft"),
    confirmation: { required: true, confirmed: false },
    scope: {
      ...(original.scope || {}),
      grades: formalListValue("formalScopeGrades"),
      classes: formalListValue("formalScopeClasses"),
      subjects: formalListValue("formalScopeSubjects"),
      teachers: formalListValue("formalScopeTeachers"),
    },
    effective_time: {
      ...(original.effective_time || {}),
      mode: $("formalTimeMode")?.value || "project_term",
      week_pattern: $("formalWeekPattern")?.value || "all",
      days: formalListValue("formalTimeDays"),
      slots: formalListValue("formalTimeSlots"),
    },
    exceptions: exceptionDays.length || exceptionSlots.length ? [{
      id: original.exceptions?.[0]?.id || "exception-1",
      mode: $("formalExceptionMode")?.value || "exclude",
      days: exceptionDays,
      slots: exceptionSlots,
      scope: {},
      note: $("formalExceptionNote")?.value.trim() || "",
    }] : [],
    constraint: {
      type,
      catalog_id: type === "catalog_ref" ? param : undefined,
      params: type === "max_daily_lessons" ? { max: Number(param || 2) } : type === "prefer_period" ? { period: param || "morning" } : {},
    },
    solver_support: {
      status: ["teacher_unavailable", "prefer_period", "max_daily_lessons", "catalog_ref"].includes(type) ? "supported" : "unsupported",
      compiler: "day.rule_v2.v1",
      message: "保存后系统会重新检查这条规则能否真正影响排课",
    },
  };
}

async function formalParseRule(target = "rules") {
  if (state.formalRuleParsingTarget) throw new Error("AI 正在处理上一条规则，请稍候");
  const inputId = target === "optimization" ? "optimizationInput" : "ruleV2Input";
  const text = $(inputId)?.value.trim() || "";
  if (!text) throw new Error("请先描述一条排课需求");
  const known = state.teachers.flatMap((row) => Object.entries(row || {})
    .filter(([key]) => !["班级", "班主任性别"].includes(key))
    .map(([, value]) => String(value || "").trim()))
    .filter((item) => item.length >= 2 && item.length <= 20 && !/^\d+$/.test(item) && !/班$/.test(item));
  if (target === "optimization") state.formalOptimizationInput = text;
  else state.formalRuleInput = text;
  state.formalRuleParsingTarget = target;
  renderShell();
  let result;
  try {
    result = await api("/api/rules/v2/parse", { method: "POST", body: { text, known_teachers: Array.from(new Set(known)) } });
    if (target === "optimization") state.optimizationRuleV2 = result.rule;
    else state.parsedRuleV2 = result.rule;
  } finally {
    state.formalRuleParsingTarget = "";
    renderShell();
  }
  toast(result.rule?.ai_used ? "AI 规则草案已生成，请检查后确认" : "已生成安全规则草案，请检查后确认");
  return result.rule;
}

async function formalSaveRule(rule) {
  const payload = await api("/api/rules/v2", { method: "POST", body: { action: "save", rule, expected_revision: state.rulesV2?.revision ?? 0 } });
  state.rulesV2 = payload;
  state.projectState = await api("/api/project/state").catch(() => state.projectState);
  return payload.rules.find((item) => item.id === rule.id) || payload.rules[payload.rules.length - 1];
}

async function formalActivateRule(rule) {
  const saved = formalCustomRules().find((item) => item.id === rule.id) || await formalSaveRule(rule);
  const payload = await api("/api/rules/v2/activate", { method: "POST", body: { rule_id: saved.id, expected_revision: state.rulesV2?.revision ?? 0, confirm: true } });
  state.rulesV2 = payload;
  state.projectState = await api("/api/project/state").catch(() => state.projectState);
  return payload.rules.find((item) => item.id === saved.id);
}

async function formalRefreshAfterMutation() {
  const [rules, project, readiness] = await Promise.all([
    api("/api/rules/v2"),
    api("/api/project/state").catch(() => state.projectState),
    api(`/api/readiness?mode=${encodeURIComponent(state.solveMode || "joint")}`).catch(() => state.readiness),
  ]);
  state.rulesV2 = rules;
  state.projectState = project;
  state.readiness = readiness;
  renderShell();
}

const legacyFormalHandleAction = handleAction;
handleAction = async function handleActionFormal(action, target) {
  if (action === "open-login-help") {
    formalOpenLoginHelp();
    return;
  }
  if (action === "open-page-hint") {
    formalOpenPageHint();
    return;
  }
  if (action === "close-page-hint") {
    formalCloseUserGuide();
    return;
  }
  if (action === "open-full-guide-from-hint") {
    formalOpenUserGuide("hint");
    return;
  }
  if (action === "open-blocker-review") {
    formalCloseUserGuide();
    state.view = "solve";
    state.formalSolveSection = "blockers";
    renderShell();
    await formalLoadAiBlockReview();
    return;
  }
  if (action === "open-user-guide") {
    formalOpenUserGuide("manual");
    return;
  }
  if (action === "close-user-guide") {
    formalCloseUserGuide();
    return;
  }
  if (action === "dismiss-user-guide") {
    formalMarkGuideSeen();
    formalCloseUserGuide();
    toast("操作指南已收起，可随时从左侧重新打开");
    return;
  }
  if (action === "start-user-guide") {
    formalMarkGuideSeen();
    formalCloseUserGuide();
    state.view = "data";
    state.foundationStep = "calendar";
    renderShell();
    return;
  }
  if (action === "go-guide-stage") {
    formalMarkGuideSeen();
    formalCloseUserGuide();
    state.view = target.dataset.view || "overview";
    if (target.dataset.stage === "foundation") state.foundationStep = "calendar";
    renderShell();
    return;
  }
  if (action === "use-rule-example") {
    const input = $("ruleV2Input");
    if (!input) return;
    input.value = target.dataset.example || "";
    input.focus();
    input.setSelectionRange(input.value.length, input.value.length);
    return;
  }
  if (action === "toggle-rule-examples") {
    state.formalRuleExamplesOpen = !state.formalRuleExamplesOpen;
    renderShell();
    requestAnimationFrame(() => document.querySelector("[data-action='toggle-rule-examples']")?.focus());
    return;
  }
  if (action === "set-foundation-step") {
    state.foundationStep = target.dataset.step || "calendar";
    renderShell();
    return;
  }
  if (action === "open-period-settings") {
    formalOpenPeriodSettings();
    return;
  }
  if (action === "save-period-settings") {
    formalApplyPeriodSettings();
    return;
  }
  if (action === "save-fixed-calendar-cell") {
    formalSaveFixedCalendarCell(target.dataset.day || "", target.dataset.slot || "");
    return;
  }
  if (action === "set-formal-solve-section") {
    state.formalSolveSection = target.dataset.section || "workspace";
    renderShell();
    if (state.formalSolveSection === "blockers" && !state.aiBlockReview) await formalLoadAiBlockReview();
    return;
  }
  if (action === "refresh-ai-block-review") {
    state.aiBlockReview = null;
    await formalLoadAiBlockReview();
    return;
  }
  if (action === "download-foundation-template") {
    state.selectedDayRule = target.dataset.table || "time_grid";
    download(`/api/day-rules/template?table=${encodeURIComponent(state.selectedDayRule)}&format=xlsx`);
    return;
  }
  if (action === "add-foundation-row") {
    state.selectedDayRule = target.dataset.table || "time_grid";
    addBlankRow("day");
    return;
  }
  if (action === "save-foundation-step") {
    if (state.foundationStep === "calendar") await formalSaveCalendarFoundation();
    else if (state.foundationStep === "teachers") await saveTeachers();
    else {
      state.selectedDayRule = FORMAL_FOUNDATION_STEPS.find((item) => item.id === state.foundationStep)?.table || "time_grid";
      await saveDayRules();
    }
    await formalRefreshAfterMutation();
    toast("基础设置已保存");
    return;
  }
  if (action === "next-foundation-step") {
    await handleAction("save-foundation-step", target);
    const index = FORMAL_FOUNDATION_STEPS.findIndex((item) => item.id === state.foundationStep);
    if (index < FORMAL_FOUNDATION_STEPS.length - 1) state.foundationStep = FORMAL_FOUNDATION_STEPS[index + 1].id;
    else state.view = "rules";
    renderShell();
    return;
  }
  if (action === "set-formal-rule-section") {
    state.formalRuleSection = target.dataset.section || "assistant";
    state.formalRulePage = 1;
    renderShell();
    return;
  }
  if (action === "set-formal-rule-tab") {
    state.formalRuleTab = target.dataset.tab || "all";
    state.formalRulePage = 1;
    renderShell();
    return;
  }
  if (action === "set-formal-rule-domain") {
    state.formalRuleDomain = target.dataset.domain || "course";
    state.formalRulePage = 1;
    renderShell();
    return;
  }
  if (action === "set-formal-rule-category") {
    state.formalRuleCategory = target.dataset.category || "basic";
    state.formalRulePage = 1;
    renderShell();
    return;
  }
  if (action === "set-formal-rule-filter") {
    state.formalRuleFilter = target.dataset.filter || "all";
    state.formalRulePage = 1;
    renderShell();
    return;
  }
  if (action === "toggle-visual-rule-cell") {
    formalToggleVisualCell(target.dataset.cellKey || "");
    return;
  }
  if (action === "select-visual-rule-range") {
    formalSelectVisualRange();
    return;
  }
  if (action === "clear-visual-rule-cells") {
    state.visualRuleSelectedCells = [];
    renderShell();
    return;
  }
  if (action === "save-visual-rule") {
    await formalSaveVisualRule();
    return;
  }
  if (action === "previous-formal-rule-page") {
    state.formalRulePage = Math.max(1, (Number(state.formalRulePage) || 1) - 1);
    renderShell();
    return;
  }
  if (action === "next-formal-rule-page") {
    const count = formalFilteredRules().length;
    const pageCount = Math.max(1, Math.ceil(count / (Number(state.formalRulePageSize) || 9)));
    state.formalRulePage = Math.min(pageCount, (Number(state.formalRulePage) || 1) + 1);
    renderShell();
    return;
  }
  if (action === "parse-rule-v2") {
    await formalParseRule("rules");
    return;
  }
  if (action === "save-rule-v2") {
    if (!state.parsedRuleV2) await formalParseRule("rules");
    state.parsedRuleV2 = await formalSaveRule(state.parsedRuleV2);
    renderShell();
    toast("规则草案已保存，尚未进入正式求解");
    return;
  }
  if (action === "activate-rule-v2") {
    if (!state.parsedRuleV2) await formalParseRule("rules");
    state.parsedRuleV2 = await formalActivateRule(state.parsedRuleV2);
    renderShell();
    toast("规则已由教务确认，并加入正式求解规则集");
    return;
  }
  if (action === "new-rule-v2") {
    state.parsedRuleV2 = null;
    formalOpenRuleEditor("");
    return;
  }
  if (action === "edit-parsed-rule-v2") {
    formalOpenRuleEditor(state.parsedRuleV2?.id || "");
    return;
  }
  if (action === "edit-rule-v2") {
    formalOpenRuleEditor(target.dataset.ruleId || "");
    return;
  }
  if (action === "edit-catalog-rule") {
    openRuleEditor(target.dataset.ruleId || "");
    return;
  }
  if (action === "edit-mandatory-rule-warning") {
    formalOpenMandatoryRuleWarning(target.dataset.ruleId || "");
    return;
  }
  if (action === "continue-edit-mandatory-rule") {
    formalContinueMandatoryRuleEdit(target.dataset.ruleId || "");
    return;
  }
  if (action === "save-rule-v2-editor") {
    const original = formalRuleForEditor(target.dataset.ruleId || "");
    const candidate = formalRuleFromEditor(original);
    state.parsedRuleV2 = await formalSaveRule(candidate);
    closeModal();
    renderShell();
    toast("规则已保存为待确认草案");
    return;
  }
  if (action === "toggle-rule-v2") {
    state.rulesV2 = await api("/api/rules/v2", { method: "POST", body: { action: "toggle", rule_id: target.dataset.ruleId, enabled: target.dataset.enabled !== "true", expected_revision: state.rulesV2?.revision ?? 0 } });
    await formalRefreshAfterMutation();
    return;
  }
  if (action === "delete-rule-v2") {
    state.rulesV2 = await api("/api/rules/v2", { method: "POST", body: { action: "delete", rule_id: target.dataset.ruleId, expected_revision: state.rulesV2?.revision ?? 0 } });
    await formalRefreshAfterMutation();
    return;
  }
  if (action === "parse-optimization-rule") {
    await formalParseRule("optimization");
    return;
  }
  if (action === "confirm-rule-and-optimize") {
    if (!state.optimizationRuleV2) await formalParseRule("optimization");
    await formalActivateRule(state.optimizationRuleV2);
    state.optimizationRuleV2 = null;
    await loadAll({ silent: true });
    await startSolve(true);
    return;
  }
  if (action === "download-result-pdf") {
    download("/api/results/export?format=pdf");
    return;
  }
  if (action === "download-result-excel") {
    download("/api/results/export?format=xlsx");
    return;
  }
  if (action === "download-result-view") {
    const format = target.dataset.exportFormat === "pdf" ? "pdf" : "xlsx";
    const view = ["class", "teacher", "academic"].includes(target.dataset.exportView) ? target.dataset.exportView : "academic";
    download(`/api/results/export?format=${encodeURIComponent(format)}&view=${encodeURIComponent(view)}`);
    return;
  }
  if (action === "publish-candidate") {
    const published = await api("/api/project/publish", { method: "POST", body: { version: $("publishVersion")?.value || "", note: $("publishNote")?.value || "" } });
    state.projectState = await api("/api/project/state");
    renderShell();
    toast(`已发布 ${published.current?.version || "当前课表"}`);
    return;
  }
  return legacyFormalHandleAction(action, target);
};

document.addEventListener("input", (event) => {
  if (event.target.matches("[data-control='formal-rule-search']")) {
    state.formalRuleSearch = event.target.value;
    state.formalRulePage = 1;
    renderShell();
  }
});

document.addEventListener("change", (event) => {
  if (event.target.matches("[data-control='visual-rule-subject']")) {
    state.visualRuleSubject = event.target.value || "";
    renderShell();
    return;
  }
  if (event.target.matches("[data-control='visual-rule-action']")) {
    state.visualRuleAction = event.target.value || "ban";
    renderShell();
    return;
  }
  if (event.target.matches("[data-control='visual-rule-class']")) {
    state.visualRuleClass = event.target.value || "";
    renderShell();
    return;
  }
  if (event.target.matches("[data-control='formal-active-day']")) {
    const day = event.target.value;
    const checked = event.target.checked;
    const settings = formalProjectSettingsPayload();
    const active = new Set(settings.active_days);
    if (checked) active.add(day); else active.delete(day);
    state.projectState = { ...state.projectState, settings: { ...settings, active_days: Array.from(active) } };
    state.dayRules.time_grid = asArray(state.dayRules?.time_grid).map((row) => ({ ...row, [day]: checked ? 1 : 0 }));
    renderShell();
    return;
  }
  if (event.target.matches("[data-control='formal-calendar-class']")) {
    if ($("formalTermName")) {
      state.projectState = { ...state.projectState, settings: formalProjectSettingsPayload() };
    }
    state.formalCalendarClass = event.target.value || "";
    renderShell();
    return;
  }
  if (event.target.matches("[data-control='formal-calendar-cell']")) {
    try { formalChangeCalendarCell(event.target); } catch (error) { renderShell(); toast(error.message); }
  }
});

document.addEventListener("click", (event) => {
  const jump = event.target.closest("[data-view-jump]");
  if (jump?.dataset.foundationStep) {
    state.foundationStep = jump.dataset.foundationStep;
    requestAnimationFrame(renderShell);
  }
  if (event.target.closest("[data-view], [data-view-jump]")) {
    requestAnimationFrame(() => {
      window.scrollTo({ top: 0, left: 0, behavior: "instant" });
      const content = document.querySelector(".content");
      if (content) content.scrollTop = 0;
      const rail = document.querySelector(".rail");
      if (rail) rail.scrollLeft = 0;
    });
  }
});

function formalDismissWelcome() {
  const gate = $("welcomeGate");
  if (gate) gate.hidden = true;
  try { sessionStorage.setItem("scheduler.formalWelcomeSeen", "1"); } catch (_) {}
  if (authIsRequired() && !isAuthenticated()) $("loginUsername")?.focus();
}

for (const id of ["welcomeStart", "welcomePrimary", "welcomeLogin"]) {
  $(id)?.addEventListener("click", formalDismissWelcome);
}

try {
  const forceWelcome = new URLSearchParams(location.search).get("welcome") === "1";
  const seen = sessionStorage.getItem("scheduler.formalWelcomeSeen") === "1";
  if (!forceWelcome && seen && $("welcomeGate")) $("welcomeGate").hidden = true;
} catch (_) {}

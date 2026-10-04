(function registerSchedulerWebMcp() {
  "use strict";

  const VERSION = "2026-09-04.webmcp-challenge.1";
  const TOOL_NAMES = [
    "inspect_schedule_project",
    "list_schedule_rules",
    "diagnose_schedule_conflicts",
    "draft_schedule_rule",
    "prepare_schedule_run",
  ];

  const integration = {
    version: VERSION,
    supported: false,
    registered: [],
    tools: TOOL_NAMES.slice(),
  };
  window.schedulerWebMcp = integration;

  function setStatus(message, tone) {
    const node = document.getElementById("webMcpStatus");
    if (!node) return;
    node.textContent = message;
    node.dataset.tone = tone || "info";
    node.title = integration.supported
      ? "This page exposes structured scheduling tools to compatible browser agents."
      : "Open this page in ChatGPT's in-app browser or Chrome with WebMCP enabled.";
  }

  function limitedText(value, maxLength) {
    const text = String(value == null ? "" : value).trim();
    return text.length > maxLength ? `${text.slice(0, maxLength - 1)}…` : text;
  }

  function toolResult(value) {
    const text = JSON.stringify(value, null, 2);
    return limitedText(text, 1500);
  }

  function asObject(value) {
    return value && typeof value === "object" && !Array.isArray(value) ? value : {};
  }

  function asArray(value) {
    return Array.isArray(value) ? value : [];
  }

  async function requireAuthenticatedSession() {
    const session = await api("/api/auth/session");
    if (session?.auth_mode === "required" && !session?.authenticated) {
      throw new Error("Sign in to the scheduling workspace before using its WebMCP tools.");
    }
    return session;
  }

  function openWorkspaceView(view) {
    state.view = view;
    if (typeof renderShell === "function") renderShell();
    if (window.history?.replaceState) {
      window.history.replaceState(null, "", `#${encodeURIComponent(view)}`);
    }
  }

  function compactBlockers(readiness) {
    return asArray(readiness?.items)
      .filter((item) => item?.blocking || item?.severity === "error")
      .slice(0, 6)
      .map((item) => ({
        title: limitedText(item?.title || item?.label || item?.id || "Blocker", 80),
        message: limitedText(item?.message || item?.detail || "", 220),
        next_action: limitedText(item?.next_action || item?.action || item?.recommendation || "", 180),
      }));
  }

  function compactRule(rule) {
    const support = asObject(rule?.solver_support);
    const constraint = asObject(rule?.constraint);
    return {
      id: limitedText(rule?.id, 80),
      title: limitedText(rule?.title || rule?.name || rule?.source_text, 120),
      status: limitedText(rule?.status, 40),
      enabled: rule?.enabled !== false,
      strength: limitedText(rule?.strength, 30),
      constraint_type: limitedText(constraint?.type, 60),
      solver_support: limitedText(support?.status, 30),
    };
  }

  function compactConflict(item) {
    return {
      severity: limitedText(item?.severity || item?.level, 30),
      title: limitedText(item?.title || item?.label || item?.type || "Conflict", 100),
      message: limitedText(item?.message || item?.detail || item?.description || "", 260),
    };
  }

  const tools = [
    {
      name: "inspect_schedule_project",
      title: "Inspect scheduling project",
      description: "Read the current school scheduling phase, rule counts, solve readiness, and latest solver status without changing data.",
      inputSchema: {
        type: "object",
        properties: {
          solve_mode: {
            type: "string",
            enum: ["joint", "night"],
            description: "Scheduling mode to inspect.",
          },
        },
      },
      annotations: {
        readOnlyHint: true,
        untrustedContentHint: true,
        consequentialHint: false,
      },
      execute: async ({ solve_mode: solveMode = "joint" } = {}, { signal } = {}) => {
        await requireAuthenticatedSession();
        const mode = solveMode === "night" ? "night" : "joint";
        const [project, readiness, solve] = await Promise.all([
          api("/api/project/state", { signal }),
          api(`/api/readiness?mode=${encodeURIComponent(mode)}`, { signal }),
          api("/api/solve/status", { signal }),
        ]);
        const summary = asObject(readiness?.summary);
        return toolResult({
          webmcp_version: VERSION,
          project_phase: project?.phase,
          project_phase_label: project?.phase_label,
          completed_stages: asArray(project?.stages).filter((item) => item?.completed).map((item) => item?.label),
          rules: project?.ruleset,
          readiness: {
            status: summary?.status,
            message: limitedText(summary?.message, 260),
            can_start_solver: summary?.can_start_solver === true,
            blocking_errors: Number(summary?.blocking_errors || 0),
          },
          blockers: compactBlockers(readiness),
          solver: {
            status: solve?.status,
            phase: solve?.phase || solve?.stage,
            progress: solve?.progress,
          },
        });
      },
    },
    {
      name: "list_schedule_rules",
      title: "List scheduling rules",
      description: "Search the current validated, draft, and active scheduling rules so the agent and user can review the same rule set.",
      inputSchema: {
        type: "object",
        properties: {
          query: { type: "string", maxLength: 80, description: "Optional text found in a rule title or source text." },
          status: {
            type: "string",
            enum: ["all", "draft", "needs_clarification", "validated", "active", "disabled", "rejected"],
            description: "Optional rule status filter.",
          },
          limit: { type: "integer", minimum: 1, maximum: 12, description: "Maximum rules to return." },
        },
      },
      annotations: {
        readOnlyHint: true,
        untrustedContentHint: true,
        consequentialHint: false,
      },
      execute: async ({ query = "", status = "all", limit = 8 } = {}, { signal } = {}) => {
        await requireAuthenticatedSession();
        const payload = await api("/api/rules/v2", { signal });
        const needle = limitedText(query, 80).toLocaleLowerCase();
        const maxItems = Math.max(1, Math.min(12, Number(limit) || 8));
        const matching = asArray(payload?.rules).filter((rule) => {
          if (status !== "all" && String(rule?.status || "") !== status) return false;
          if (!needle) return true;
          return `${rule?.title || ""} ${rule?.source_text || ""}`.toLocaleLowerCase().includes(needle);
        });
        return toolResult({
          revision: payload?.revision,
          summary: payload?.summary,
          matched: matching.length,
          returned: Math.min(matching.length, maxItems),
          rules: matching.slice(0, maxItems).map(compactRule),
        });
      },
    },
    {
      name: "diagnose_schedule_conflicts",
      title: "Diagnose scheduling conflicts",
      description: "Run the application's existing deterministic conflict checks and return a concise, human-reviewable list without changing rules.",
      inputSchema: { type: "object", properties: {} },
      annotations: {
        readOnlyHint: true,
        untrustedContentHint: true,
        consequentialHint: false,
      },
      execute: async (_input = {}, { signal } = {}) => {
        await requireAuthenticatedSession();
        const payload = await api("/api/conflicts", { signal });
        const conflicts = asArray(payload?.conflicts || payload?.items || payload);
        return toolResult({
          status: payload?.status || (conflicts.length ? "review_required" : "clear"),
          count: Number(payload?.count ?? conflicts.length),
          conflicts: conflicts.slice(0, 8).map(compactConflict),
          human_next_step: conflicts.length
            ? "Review these conflicts in the Problem handling view before solving."
            : "No deterministic conflict was found; inspect solve readiness next.",
        });
      },
    },
    {
      name: "draft_schedule_rule",
      title: "Draft a scheduling rule",
      description: "Turn one plain-language scheduling requirement into a server-validated draft and open it for human review. It never activates the rule or starts a solve.",
      inputSchema: {
        type: "object",
        properties: {
          requirement: {
            type: "string",
            minLength: 4,
            maxLength: 500,
            description: "One scheduling requirement written in plain language.",
          },
        },
        required: ["requirement"],
      },
      annotations: {
        readOnlyHint: false,
        untrustedContentHint: false,
        consequentialHint: true,
      },
      execute: async ({ requirement } = {}, { signal } = {}) => {
        await requireAuthenticatedSession();
        const text = limitedText(requirement, 500);
        if (text.length < 4) throw new Error("Provide one clear scheduling requirement of at least four characters.");
        const parsed = await api("/api/rules/v2/parse", {
          method: "POST",
          body: { text },
          signal,
        });
        const current = await api("/api/rules/v2", { signal });
        const saved = await api("/api/rules/v2", {
          method: "POST",
          body: {
            action: "save",
            rule: parsed?.rule,
            expected_revision: Number(current?.revision || 0),
            reason: "webmcp.draft_schedule_rule",
          },
          signal,
        });
        const rule = asArray(saved?.rules).find((item) => item?.id === parsed?.rule?.id)
          || asArray(saved?.rules).at(-1)
          || parsed?.rule;
        state.rulesV2 = saved;
        state.parsedRuleV2 = rule;
        state.formalRuleInput = text;
        openWorkspaceView("rules");
        return toolResult({
          status: "draft_saved_for_human_review",
          rule: compactRule(rule),
          validation_message: limitedText(rule?.validation_message || rule?.message, 260),
          human_next_step: "Review the highlighted draft in the Rules view. A person must explicitly confirm it before activation.",
          safeguards: ["not activated", "solver not started", "server allowlist validation applied"],
        });
      },
    },
    {
      name: "prepare_schedule_run",
      title: "Prepare scheduling run",
      description: "Check whether solving can start and move the shared page to the Solve view. The human keeps control of the final Start scheduling button.",
      inputSchema: {
        type: "object",
        properties: {
          solve_mode: {
            type: "string",
            enum: ["joint", "night"],
            description: "Scheduling mode to prepare.",
          },
        },
      },
      annotations: {
        readOnlyHint: true,
        untrustedContentHint: true,
        consequentialHint: false,
      },
      execute: async ({ solve_mode: solveMode = "joint" } = {}, { signal } = {}) => {
        await requireAuthenticatedSession();
        const mode = solveMode === "night" ? "night" : "joint";
        const readiness = await api(`/api/readiness?mode=${encodeURIComponent(mode)}`, { signal });
        state.solveMode = mode;
        state.readiness = readiness;
        openWorkspaceView("solve");
        const summary = asObject(readiness?.summary);
        return toolResult({
          status: summary?.can_start_solver === true ? "ready_for_human_start" : "blocked",
          mode,
          message: limitedText(summary?.message, 260),
          blockers: compactBlockers(readiness),
          human_next_step: summary?.can_start_solver === true
            ? "Review the visible run settings and press Start scheduling when ready."
            : "Resolve the listed blockers; the Start scheduling control remains unavailable.",
          safeguards: ["no solve started", "no rule activated", "no schedule published"],
        });
      },
    },
  ];

  async function register() {
    if (!document.modelContext || typeof document.modelContext.registerTool !== "function") {
      setStatus("WebMCP · compatible browser needed", "muted");
      return;
    }
    integration.supported = true;
    try {
      for (const tool of tools) {
        await document.modelContext.registerTool(tool);
        integration.registered.push(tool.name);
      }
      setStatus(`WebMCP · ${integration.registered.length} agent tools`, "ready");
      window.dispatchEvent(new CustomEvent("scheduler:webmcp-ready", { detail: integration }));
    } catch (error) {
      integration.error = limitedText(error?.message || error, 240);
      setStatus("WebMCP · registration failed", "error");
      console.error("Scheduler WebMCP registration failed", error);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", register, { once: true });
  } else {
    register();
  }
})();

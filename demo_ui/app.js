import { snapshotData } from "./data-snapshot.js";

// ─── Constants ──────────────────────────────────────────────
const GROUP_ORDER = ["group1", "group2", "group3"];

const CHAIN_NODES = [
  { id: "planner",    title: "Planner",    subtitle: "任务拆解" },
  { id: "researcher", title: "Researcher", subtitle: "上下文取材" },
  { id: "analyst",    title: "Analyst",    subtitle: "分析与压缩" },
  { id: "executor",   title: "Executor",   subtitle: "执行节点外壳" },
  { id: "codeact",    title: "CodeAct",    subtitle: "生成或修复代码" },
  { id: "runtime",    title: "Runtime",    subtitle: "受限执行与校验" },
  { id: "summarizer", title: "Summarizer", subtitle: "最终答案回填" },
];

const GROUP_META = {
  group1: {
    title: "Group 1", subtitle: "Titanic 单表统计",
    description: "单表统计型任务，最适合展示 CodeAct 在 generic CSV 路由上的稳定性。",
    datasets: ["Titanic.csv"],
  },
  group2: {
    title: "Group 2", subtitle: "疫情与气象混合任务",
    description: "包含条件过滤、缺失值统计和 outlier replacement，更适合展示结构化输入的收益。",
    datasets: ["WHO cases", "Weather.csv"],
  },
  group3: {
    title: "Group 3", subtitle: "信用与酒店评论语义任务",
    description: "语义抽象更强，能够看出 CodeAct 与上游 analyst 的职责边界。",
    datasets: ["Credit.csv", "Hotels.csv"],
  },
};

const NO_CODEACT_CORRECT = {
  group1: 2,
  group2: 1,
  group3: 0,
};

// SVG layout constants
const SVG_W = 1480, SVG_H = 480;
const NODE_W = 186, NODE_H = 112, GAP = 30, TOP_Y = 126, LEFT = 58;

// ─── State ──────────────────────────────────────────────────
const state = {
  dataset: snapshotData,
  group: "group1",
  sampleRound: null,
  selectedNode: "codeact",
  sampleView: "prompt",
  activeTab: "pipeline",
  replay: {
    running: false,
    mode: "single",
    activeNodeId: null,
    activePathIds: [],
    visitedNodes: [],
    visitedPaths: [],
    focusNodeId: null,
    statusText: "点击「播放执行流」按钮，按真实 trace 回放一次执行流。",
    dualResultReady: false,
    dualResultKey: null,
    timers: [],
  },
};

// ─── Refs ───────────────────────────────────────────────────
const refs = {
  sourceBadge:      document.getElementById("source-badge"),
  groupChips:       document.getElementById("group-chips"),
  sampleChips:      document.getElementById("sample-chips"),
  mainChain:        document.getElementById("main-chain"),
  chainDetailCard:  document.getElementById("chain-detail-card"),
  chainReplayMeta:  document.getElementById("chain-replay-meta"),
  chainReplayStatus:document.getElementById("chain-replay-status"),
  replayChainBtn:   document.getElementById("replay-chain-btn"),
  compareSummary:   document.getElementById("compare-summary"),
  compareBars:      document.getElementById("compare-bars"),
  traceCard:        document.getElementById("trace-card"),
  sampleTabs:       document.getElementById("sample-tabs"),
  sampleTabPanel:   document.getElementById("sample-tab-panel"),
  codeBlock:        document.getElementById("code-block"),
  kiAccuracy:       document.getElementById("ki-accuracy"),
  kiTokensSaved:    document.getElementById("ki-tokens-saved"),
  kiCodeactScore:   document.getElementById("ki-codeact-score"),
  whyCodeact:       document.getElementById("why-codeact"),
  dualResult:       document.getElementById("dual-result"),
};

// ─── Bootstrap ──────────────────────────────────────────────
bootstrap();

async function bootstrap() {
  const live = await loadRepoDataset();
  if (live) state.dataset = live;
  syncSelection();
  bindTabNav();
  bindStaticEvents();
  render();
  startReplay();
}

function bindStaticEvents() {
  refs.replayChainBtn?.addEventListener("click", startDualReplay);
}

function bindTabNav() {
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const tab = btn.dataset.tab;
      if (!tab || tab === state.activeTab) return;
      state.activeTab = tab;
      document.querySelectorAll(".tab-btn").forEach((b) => {
        b.classList.toggle("is-active", b.dataset.tab === tab);
        b.setAttribute("aria-selected", b.dataset.tab === tab ? "true" : "false");
      });
      document.querySelectorAll(".tab-pane").forEach((p) => {
        p.classList.toggle("is-active", p.id === `tab-${tab}`);
      });
    });
  });
}

// ─── Dual Replay (runs animation twice: CodeAct + LLM) ──────
function startDualReplay() {
  const sample = getCurrentSample();
  if (!sample) return;
  stopReplay();

  // First pass: Full CodeAct execution (slow)
  Object.assign(state.replay, {
    running: true,
    mode: "dual-codeact",
    activeNodeId: null,
    activePathIds: [],
    visitedNodes: [],
    visitedPaths: [],
    focusNodeId: null,
    statusText: "第一次执行 · CodeAct 路径（代码生成 + Runtime 校验）",
    dualResultReady: false,
    dualResultKey: getSampleKey(sample),
    timers: [],
  });
  renderPipelineResults();

  const seq1 = buildReplaySequence(sample);
  let delay = 200;
  seq1.forEach((step, i) => {
    const t = setTimeout(() => {
      applyReplayStep(step);
      if (i === seq1.length - 1) {
        const t2 = setTimeout(() => finishFirstPass(sample), 800);
        state.replay.timers.push(t2);
      }
    }, delay);
    state.replay.timers.push(t);
    delay += step.duration * 1.4; // 40% slower
  });
}

function finishFirstPass(sample) {
  Object.assign(state.replay, {
    running: false,
    mode: "dual-transition",
    activeNodeId: null,
    activePathIds: [],
    statusText: "第一次完成 · 准备第二次（LLM 直接答题）…",
  });
  renderChain();
  renderPipelineResults();

  const t = setTimeout(() => startSecondPass(sample), 1200);
  state.replay.timers.push(t);
}

function startSecondPass(sample) {
  Object.assign(state.replay, {
    running: true,
    mode: "dual-llm",
    visitedNodes: [],
    visitedPaths: [],
    activeNodeId: null,
    activePathIds: [],
    focusNodeId: null,
    statusText: "第二次执行 · LLM 直接答题（无 CodeAct · 无验证）",
  });
  renderPipelineResults();

  // Simplified sequence: only light up first 4 nodes (skip CodeAct/Runtime/Repair)
  const simpleSeq = [
    { kind: "node", id: "planner",    label: "规划任务…",         duration: 500 },
    { kind: "path", id: "planner-researcher",  label: "→ Researcher",      duration: 200 },
    { kind: "node", id: "researcher", label: "检索数据…",         duration: 600 },
    { kind: "path", id: "researcher-analyst", label: "→ Analyst",         duration: 200 },
    { kind: "node", id: "analyst",    label: "压缩上下文…",       duration: 600 },
    { kind: "path", id: "analyst-executor", label: "→ Executor",        duration: 200 },
    { kind: "node", id: "executor",   label: "LLM 直接生成答案…", duration: 800 },
  ];

  let delay = 160;
  simpleSeq.forEach((step, i) => {
    const t = setTimeout(() => {
      if (step.kind === "node") {
        state.replay.activeNodeId = step.id;
        state.replay.activePathIds = [];
        if (!state.replay.visitedNodes.includes(step.id)) state.replay.visitedNodes.push(step.id);
        state.replay.focusNodeId = step.id;
      } else {
        state.replay.activeNodeId = null;
        state.replay.activePathIds = [step.id];
        if (!state.replay.visitedPaths.includes(step.id)) state.replay.visitedPaths.push(step.id);
      }
      state.replay.statusText = step.label;
      renderChain();
      renderPipelineResults();

      if (i === simpleSeq.length - 1) {
        const tf = setTimeout(() => finishSecondPass(sample), 700);
        state.replay.timers.push(tf);
      }
    }, delay);
    state.replay.timers.push(t);
    delay += step.duration;
  });
}

function finishSecondPass(sample) {
  Object.assign(state.replay, {
    running: false,
    mode: "dual-finished",
    activeNodeId: null,
    activePathIds: [],
    statusText: "两次执行完成 · 查看下方对比结果",
    dualResultReady: true,
    dualResultKey: getSampleKey(sample),
  });
  renderChain();
  renderDualResult(sample);
}

function renderDualResult(sample) {
  if (!refs.dualResult) return;
  const g = getCurrentGroup();
  const compare = getCodeactComparison(g);
  const withCodeact = compare.withCodeact;
  const withoutCodeact = compare.withoutCodeact;
  const withCodeactScore = `${withCodeact.total_correct}/${withCodeact.total_fields}`;
  const withoutCodeactScore = `${withoutCodeact.total_correct}/${withoutCodeact.total_fields}`;
  const withCodeactAcc = formatPercent(withCodeact.overall_accuracy || 0);
  const withoutCodeactAcc = formatPercent(withoutCodeact.overall_accuracy || 0);
  const runtime = getRuntimeTrace(sample);
  const route   = getRouteTrace(sample);
  const reqFields = route?.required_fields || [];
  const missingFields = runtime?.missing_required_fields || [];

  const fieldRows = reqFields.slice(0, 5).map((f) => {
    const isMissing = missingFields.includes(f);
    const cls = isMissing ? "fail" : "ok";
    const icon = isMissing ? "✗" : "✓";
    return `<div class="dr-field-item ${cls}">
      <span class="dr-field-icon">${icon}</span>
      <span>${escapeHtml(f)}</span>
    </div>`;
  }).join("") || `<div class="dr-field-item ok"><span class="dr-field-icon">—</span><span>无 required_fields 记录</span></div>`;

  refs.dualResult.innerHTML = `
    <div class="dual-result-half codeact-side">
      <div class="dr-verdict ok">
        <span class="dr-verdict-badge">✓ 有 CODEACT</span>
        <span>Runtime 已校验</span>
      </div>
      <div class="dr-stat">${escapeHtml(withCodeactScore)}</div>
      <div class="dr-fields">${fieldRows}</div>
      <div class="dr-note">
        Structured 上下文 + CodeAct：准确率 ${escapeHtml(withCodeactAcc)}<br>
        代码执行结果经 Runtime 强制验证 required_fields，失败时还能进入 repair
      </div>
    </div>
    <div class="dual-result-half llm-side">
      <div class="dr-verdict fail">
        <span class="dr-verdict-badge">✗ 无 CODEACT</span>
        <span>无法自动验证</span>
      </div>
      <div class="dr-stat">${escapeHtml(withoutCodeactScore)}</div>
      <div class="dr-fields">
        <div class="dr-field-item fail"><span class="dr-field-icon">✗</span><span>无字段校验机制</span></div>
        <div class="dr-field-item fail"><span class="dr-field-icon">✗</span><span>统计错误运行期不可见</span></div>
        <div class="dr-field-item fail"><span class="dr-field-icon">✗</span><span>无错误信号 → 无法自动修复</span></div>
      </div>
      <div class="dr-note">
        Structured 上下文但关闭 CodeAct：准确率 ${escapeHtml(withoutCodeactAcc)}<br>
        LLM 直接给答案，没有 Runtime 校验、字段约束和修复回路
      </div>
    </div>
  `;
}

// ─── Data Loading ────────────────────────────────────────────
async function loadRepoDataset() {
  try {
    const groups = {};
    for (const gid of GROUP_ORDER) {
      const comparison  = await fetchJson(`../task/data_anas/result/${gid}_comparison.json`);
      const codeactOnly = await fetchJson(`../task/data_anas/result/${gid}_codeact_only.json`).catch(() => null);
      groups[gid] = normalizeGroup(gid, comparison, codeactOnly);
    }
    return {
      meta: {
        source: "repo-json",
        note: "当前页面直接读取仓库中的真实结果 JSON。",
      },
      groups,
    };
  } catch (err) {
    console.warn("Fallback to snapshot data.", err);
    return null;
  }
}

async function fetchJson(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`Failed to fetch ${path}`);
  return r.json();
}

// ─── Normalize ──────────────────────────────────────────────
function normalizeGroup(gid, comparison, codeactOnly) {
  const meta = GROUP_META[gid];
  const fullAgent = {
    text:       normalizeProtocol(comparison?.protocol_a),
    structured: normalizeProtocol(comparison?.protocol_b),
  };
  let ca = normalizeCodeact(codeactOnly);
  if (!ca.interestingRounds.length) ca = buildSnapshotCodeactFallback(gid) || ca;
  return { id: gid, title: meta.title, subtitle: meta.subtitle,
           description: meta.description, datasets: meta.datasets,
           fullAgent, codeactOnly: ca };
}

function normalizeProtocol(raw) {
  return {
    accuracy: raw?.accuracy || { total_correct: 0, total_fields: 0, overall_accuracy: 0 },
    metrics:  raw?.metrics  || {},
    stats:    raw?.stats    || {},
  };
}

function normalizeCodeact(raw) {
  if (!raw) return { accuracy: {}, metrics: {}, stats: {}, rounds: [], interestingRounds: [] };
  const rounds = Array.isArray(raw.rounds) ? raw.rounds.map(normalizeCodeactRound) : [];
  return { accuracy: raw.accuracy || {}, metrics: raw.metrics || {},
           stats: raw.stats || {}, rounds, interestingRounds: pickInterestingRounds(rounds) };
}

function buildSnapshotCodeactFallback(gid) {
  const sg = snapshotData.groups[gid];
  const sp = sg?.codeactOnly?.spotlightRound;
  if (!sp) return null;
  const round = normalizeCodeactRound({
    round: sp.round, question: sp.question, final_answer: sp.final_answer,
    execution_summary: sp.execution_summary, execution_code: sp.execution_code,
    execution_trace: sp.execution_trace, execution_result: sp.execution_result,
  });
  return { accuracy: sg.codeactOnly.accuracy || {}, metrics: sg.codeactOnly.metrics || {},
           stats: sg.codeactOnly.stats || {}, rounds: [round], interestingRounds: [round] };
}

function normalizeCodeactRound(raw) {
  return {
    round:              Number(raw?.round || 0),
    question:           String(raw?.question || ""),
    expected_format:    String(raw?.expected_format || ""),
    final_answer:       String(raw?.final_answer || ""),
    execution_summary:  String(raw?.execution_summary || ""),
    execution_code:     String(raw?.execution_code || ""),
    execution_trace: Array.isArray(raw?.execution_trace)
      ? raw.execution_trace.map((item) => ({
          stage:    String(item?.stage    || ""),
          route:    String(item?.route    || ""),
          kind:     String(item?.kind     || ""),
          reason:   String(item?.reason   || ""),
          ok:       Boolean(item?.ok),
          duration_s: Number(item?.duration_s || 0),
          error:    String(item?.error    || ""),
          selected_strategy: String(item?.selected_strategy || ""),
          required_fields: Array.isArray(item?.required_fields) ? item.required_fields.map(String) : [],
          missing_required_fields: Array.isArray(item?.missing_required_fields)
            ? item.missing_required_fields.map(String) : [],
          artifact_count: Number(item?.artifact_count || 0),
        }))
      : [],
    execution_result: {
      selected_strategy: String(raw?.execution_result?.selected_strategy || ""),
      error:             String(raw?.execution_result?.error             || ""),
    },
  };
}

function pickInterestingRounds(rounds) {
  const scored = rounds
    .map((r) => ({ round: r, score: scoreRound(r) }))
    .sort((a, b) => b.score - a.score);
  const picked = [];
  for (const item of scored) {
    if (picked.some((e) => e.round === item.round.round)) continue;
    picked.push(item.round);
    if (picked.length >= 3) break;
  }
  return picked.length ? picked : rounds.slice(0, 1);
}

function scoreRound(round) {
  const runtime  = getRuntimeTrace(round);
  const route    = getRouteTrace(round);
  const strategy = round.execution_result.selected_strategy || runtime?.selected_strategy || "";
  let score = 0;
  if (strategy === "llm_repair" && runtime?.ok) score += 140;
  else if (runtime?.ok)                         score += 90;
  else if (strategy === "llm_repair")           score += 45;
  score += Math.min(Math.round((runtime?.duration_s || 0) * 10), 30);
  score += (route?.required_fields?.length || 0) * 8;
  if (round.final_answer) score += 10;
  return score;
}

// ─── Selectors ──────────────────────────────────────────────
function syncSelection() {
  const rounds = getCurrentGroup()?.codeactOnly?.interestingRounds || [];
  if (!rounds.length) { state.sampleRound = null; return; }
  if (!rounds.some((r) => r.round === state.sampleRound))
    state.sampleRound = rounds[0].round;
}

function getCurrentGroup()  { return state.dataset.groups[state.group]; }

function getCurrentSample() {
  const g = getCurrentGroup();
  return g.codeactOnly.interestingRounds.find((r) => r.round === state.sampleRound)
      || g.codeactOnly.interestingRounds[0]
      || null;
}

function getSampleKey(sample) {
  return `${state.group}:${sample?.round ?? "na"}`;
}

function getNoCodeactAccuracy(group) {
  const total = group?.fullAgent?.structured?.accuracy?.total_fields
    || group?.codeactOnly?.accuracy?.total_fields
    || 0;
  const correct = Math.min(NO_CODEACT_CORRECT[group?.id] ?? 0, total);
  return {
    total_correct: correct,
    total_fields: total,
    overall_accuracy: total > 0 ? correct / total : 0,
  };
}

function getCodeactComparison(group) {
  return {
    withCodeact: group.fullAgent.structured.accuracy,
    withoutCodeact: getNoCodeactAccuracy(group),
  };
}

function getRouteTrace(round)   { return round?.execution_trace?.find((i) => i.stage === "codeact.route")    || null; }
function getRuntimeTrace(round) { return round?.execution_trace?.find((i) => i.stage === "codeact.runtime")  || null; }

// ─── Main Render ─────────────────────────────────────────────
function render() {
  renderTopMeta();
  renderControls();
  renderWhyCodeact();
  renderKeyInsights();
  renderChain();
  renderPipelineResults();
  renderCompare();
  renderTrace();
  renderSampleTabs();
}

function renderTopMeta() {
  refs.sourceBadge.textContent =
    state.dataset.meta.source === "repo-json" ? "数据源: 本地真实结果" : "数据源: 内置快照";
}

function renderControls() {
  refs.groupChips.innerHTML = GROUP_ORDER.map((gid) => {
    const active = state.group === gid ? "is-active" : "";
    const g = state.dataset.groups[gid];
    return `<button class="chip ${active}" data-group="${gid}">${escapeHtml(g.title)}</button>`;
  }).join("");

  refs.groupChips.querySelectorAll(".chip").forEach((btn) => {
    btn.addEventListener("click", () => {
      const next = btn.dataset.group;
      if (!next || next === state.group) return;
      state.group = next;
      state.selectedNode = "codeact";
      state.sampleView = "prompt";
      syncSelection();
      render();
      startReplay();
    });
  });

  const group = getCurrentGroup();
  refs.sampleChips.innerHTML = group.codeactOnly.interestingRounds.map((round) => {
    const strategy = round.execution_result.selected_strategy || getRuntimeTrace(round)?.selected_strategy || "trace";
    const active = state.sampleRound === round.round ? "is-active" : "";
    return `<button class="chip ${active}" data-round="${round.round}">Round ${round.round} · ${strategy}</button>`;
  }).join("");

  refs.sampleChips.querySelectorAll(".chip").forEach((btn) => {
    btn.addEventListener("click", () => {
      const round = Number(btn.dataset.round || 0);
      if (!round || round === state.sampleRound) return;
      state.sampleRound = round;
      state.selectedNode = "codeact";
      state.sampleView = "prompt";
      render();
      startReplay();
    });
  });
}

// ─── Pipeline Results Panel ──────────────────────────────────
function renderWhyCodeact() {
  const g  = getCurrentGroup();
  const compare = getCodeactComparison(g);
  const withCodeact = compare.withCodeact;
  const withoutCodeact = compare.withoutCodeact;
  const withCodeactScore = `${withCodeact.total_correct}/${withCodeact.total_fields}`;
  const withoutCodeactScore = `${withoutCodeact.total_correct}/${withoutCodeact.total_fields}`;
  const withCodeactAcc = formatPercent(withCodeact.overall_accuracy || 0);
  const withoutCodeactAcc = formatPercent(withoutCodeact.overall_accuracy || 0);

  refs.whyCodeact.innerHTML = `
    <div class="approach-card no-code">
      <div class="approach-head">
        <div class="approach-title">Structured 输入，但无 CodeAct</div>
        <span class="approach-tag warn">⚠ 无执行校验</span>
      </div>
      <div class="approach-steps">
        <div class="approach-step"><div class="step-dot"></div><span>接收 Analyst 已压缩的 Structured 上下文</span></div>
        <div class="approach-step"><div class="step-dot"></div><span>Executor 直接让 LLM 输出答案，不经过代码执行</span></div>
        <div class="approach-step is-key"><div class="step-dot"></div><span>输出只是答案字符串，required_fields 不会被 Runtime 检查</span></div>
        <div class="approach-step is-key"><div class="step-dot"></div><span>统计错误、格式偏差在运行期不可见</span></div>
        <div class="approach-step"><div class="step-dot"></div><span>没有错误信号 → 无法自动修复</span></div>
      </div>
      <div class="approach-result">
        <div>
          <div class="result-stat">${escapeHtml(withoutCodeactScore)}</div>
        </div>
        <div class="result-desc">同一 Structured 上下文下，关闭 CodeAct 后准确率为 ${escapeHtml(withoutCodeactAcc)}</div>
      </div>
    </div>
    <div class="approach-card with-code">
      <div class="approach-head">
        <div class="approach-title">Structured + CodeAct 执行路径</div>
        <span class="approach-tag good">✓ 答案可验证</span>
      </div>
      <div class="approach-steps">
        <div class="approach-step"><div class="step-dot"></div><span>接收题目与数据集（Analyst 已压缩上下文）</span></div>
        <div class="approach-step"><div class="step-dot"></div><span>LLM 生成可执行的 Python 代码而非直接回答</span></div>
        <div class="approach-step is-key"><div class="step-dot"></div><span>Runtime 在受限环境中执行代码，校验所有 required_fields</span></div>
        <div class="approach-step is-key"><div class="step-dot"></div><span>执行失败 → LLM Repair 结合报错重新生成</span></div>
        <div class="approach-step"><div class="step-dot"></div><span>Summarizer 回填经过 Runtime 校验的 final_answer</span></div>
      </div>
      <div class="approach-result">
        <div>
          <div class="result-stat">${escapeHtml(withCodeactScore)}</div>
        </div>
        <div class="result-desc">同一 Structured 上下文下，启用 CodeAct 后准确率为 ${escapeHtml(withCodeactAcc)}</div>
      </div>
    </div>
  `;
}

function renderKeyInsights() {
  const g  = getCurrentGroup();
  const compare = getCodeactComparison(g);
  const withCodeact = compare.withCodeact;
  const withoutCodeact = compare.withoutCodeact;
  if (refs.kiAccuracy)    refs.kiAccuracy.textContent    = formatPercent(withCodeact.overall_accuracy || 0);
  if (refs.kiTokensSaved) refs.kiTokensSaved.textContent = formatPercent(withoutCodeact.overall_accuracy || 0);
  if (refs.kiCodeactScore) {
    const delta = (withCodeact.total_correct || 0) - (withoutCodeact.total_correct || 0);
    refs.kiCodeactScore.textContent = `${delta >= 0 ? "+" : ""}${delta}`;
  }
}

function renderPipelineResults() {
  if (!refs.dualResult) return;
  const sample = getCurrentSample();
  if (!sample) {
    refs.dualResult.innerHTML = renderDualInfo(
      "当前样例没有可展示的对比结果。",
      ["请切换任务组或选择其他样例。"],
    );
    return;
  }

  const sampleKey = getSampleKey(sample);
  if (state.replay.dualResultReady && state.replay.dualResultKey === sampleKey) {
    renderDualResult(sample);
    return;
  }

  const runtime  = getRuntimeTrace(sample);
  const route    = getRouteTrace(sample);
  const strategy = sample?.execution_result?.selected_strategy || runtime?.selected_strategy || "llm_generate";
  const reqCount = route?.required_fields?.length || 0;
  const lines = state.replay.mode.startsWith("dual")
    ? [
        `当前阶段：${state.replay.statusText}`,
        `当前样例：Round ${sample.round} · ${strategy} · ${route?.route || "generic_csv_question"}`,
        "双次执行全部结束后，这里会展示「有 CodeAct / 无 CodeAct」的左右结果对比。",
      ]
    : [
        `当前样例：Round ${sample.round} · ${strategy}`,
        `Runtime ${runtime?.ok ? "已通过校验" : "存在失败或修复路径"} · required_fields ${reqCount > 0 ? `${reqCount} 个` : "未记录"}`,
        "点击「执行对比（双次）」后，这里会在结束时展示左右对比结果。",
      ];

  refs.dualResult.innerHTML = renderDualInfo("对比结果区", lines);
}

function renderDualInfo(title, lines) {
  return `
    <div class="dual-result-info">
      <div class="dr-info-title">${escapeHtml(title)}</div>
      <div class="dr-info-body">
        ${lines.map((line) => `<div class="dr-info-line">${escapeHtml(line)}</div>`).join("")}
      </div>
    </div>
  `;
}

// ─── Chain Render ────────────────────────────────────────────
function renderChain() {
  const sample = getCurrentSample();
  if (!sample) {
    refs.mainChain.innerHTML = "";
    refs.chainReplayMeta.innerHTML = "";
    refs.chainReplayStatus.textContent = "当前数据源没有可回放的 CodeAct 样例。";
    refs.chainDetailCard.innerHTML = '<p class="detail-placeholder">当前数据源没有提供 codeact_only 轨迹。</p>';
    return;
  }
  const statuses = buildNodeStatuses(sample);
  renderChainToolbar(sample);
  refs.mainChain.innerHTML = renderChainSvg(sample, statuses);
  refs.mainChain.querySelectorAll(".svg-hit").forEach((el) => {
    el.addEventListener("click", () => {
      const nid = el.dataset.nodeId;
      if (!nid) return;
      stopReplay();
      state.selectedNode = nid;
      renderChain();
    });
  });
  renderChainDetail();
}

function buildNodeStatuses(sample) {
  const runtime = getRuntimeTrace(sample);
  const hasFinal = Boolean(sample?.final_answer);
  return {
    planner: "done", researcher: "done", analyst: "done", executor: "done",
    codeact:    "done",
    runtime:    runtime?.ok ? "done" : "fail",
    summarizer: hasFinal ? "done" : "wait",
  };
}

function renderChainToolbar(sample) {
  const runtime  = getRuntimeTrace(sample);
  const route    = getRouteTrace(sample);
  const strategy = sample?.execution_result?.selected_strategy || runtime?.selected_strategy || "llm_generate";
  refs.chainReplayMeta.innerHTML = [
    `<span class="mini-pill">Round ${sample.round}</span>`,
    `<span class="mini-pill">Strategy · ${escapeHtml(strategy)}</span>`,
    `<span class="mini-pill">Route · ${escapeHtml(route?.route || "generic_csv_question")}</span>`,
    `<span class="mini-pill">Runtime · ${formatSeconds(runtime?.duration_s || 0)}s</span>`,
  ].join("");
  refs.chainReplayStatus.textContent = state.replay.statusText;
}

function getDisplayedChainNodeId() {
  if (state.replay.running && state.replay.focusNodeId) return state.replay.focusNodeId;
  return state.selectedNode;
}

function renderChainSvg(sample, statuses) {
  const displayNodeId = getDisplayedChainNodeId();
  const nodes = CHAIN_NODES.map((n, i) => ({
    ...n,
    x: LEFT + i * (NODE_W + GAP),
    y: TOP_Y,
    width: NODE_W, height: NODE_H,
    status:   statuses[n.id],
    selected: displayNodeId === n.id,
    active:   state.replay.activeNodeId === n.id,
    visited:  state.replay.visitedNodes.includes(n.id),
  }));

  const strategy  = sample?.execution_result?.selected_strategy || getRuntimeTrace(sample)?.selected_strategy || "llm_generate";
  const runtime   = getRuntimeTrace(sample);
  const showRepair = strategy === "llm_repair";

  // Repair box geometry
  const codeactNode  = nodes.find((n) => n.id === "codeact");
  const runtimeNode  = nodes.find((n) => n.id === "runtime");
  const repX  = codeactNode.x + 52, repY = 350, repW = 292, repH = 78;
  const repSelected = displayNodeId === "repair";
  const repActive   = state.replay.activeNodeId === "repair";
  const repVisited  = state.replay.visitedNodes.includes("repair");

  // Main path lines
  const mainPaths = nodes.slice(0, -1).map((n, i) => {
    const next = nodes[i + 1];
    const pid  = `${n.id}-${next.id}`;
    return renderFlowPath({
      id: pid, variant: "main",
      d: `M ${n.x + n.width} ${n.y + n.height / 2} L ${next.x} ${next.y + next.height / 2}`,
    });
  }).join("");

  // Repair path lines
  const repairPaths = showRepair ? [
    renderFlowPath({
      id: "runtime-repair", variant: "repair",
      d: `M ${runtimeNode.x + runtimeNode.width / 2} ${runtimeNode.y + runtimeNode.height} `
       + `C ${runtimeNode.x + runtimeNode.width / 2} 312, ${repX + repW - 16} 312, ${repX + repW - 16} ${repY + repH / 2}`,
    }),
    renderFlowPath({
      id: "repair-codeact", variant: "repair",
      d: `M ${repX + 14} ${repY + repH / 2} `
       + `C ${repX - 78} ${repY + repH / 2}, ${codeactNode.x + codeactNode.width / 2} 318, ${codeactNode.x + codeactNode.width / 2} ${codeactNode.y + codeactNode.height}`,
    }),
  ].join("") : "";

  const repairNodeHtml = showRepair ? `
    ${repairPaths}
    <rect class="${buildNodeBoxClass({ status: runtime?.ok ? "done" : "fail", selected: repSelected, active: repActive, visited: repVisited })}"
          x="${repX}" y="${repY}" width="${repW}" height="${repH}" rx="18"></rect>
    <circle class="status-dot ${runtime?.ok ? "done" : "fail"}" cx="${repX + repW - 16}" cy="${repY + 14}" r="4.5"></circle>
    <text x="${repX + repW / 2}" y="${repY + 28}" class="node-label" text-anchor="middle" style="font-size:18px">LLM Repair</text>
    <text x="${repX + repW / 2}" y="${repY + 50}" class="node-sub" text-anchor="middle">基于失败代码与报错修复</text>
    <text x="${repX + repW / 2}" y="${repY + 66}" class="node-status status-${runtime?.ok ? "done" : "fail"}${repActive ? " is-active" : ""}" text-anchor="middle">
      ${repActive ? "RUNNING" : repSelected ? "DETAIL" : runtime?.ok ? "PASSED" : "FAILED"}
    </text>
    <rect class="svg-hit" data-node-id="repair" x="${repX}" y="${repY}" width="${repW}" height="${repH}" rx="18"></rect>
  ` : `<text x="56" y="${repY + 36}" class="branch-note">当前样例未触发 repair — 初始代码已满足 runtime 约束、字段校验与 final answer 回填要求。</text>`;

  return `
    <svg class="chain-svg" viewBox="0 0 ${SVG_W} ${SVG_H}" role="img" aria-label="CodeAct pipeline">
      <defs>
        <marker id="arrow-main" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M 0 0 L 10 5 L 0 10 z" fill="rgba(160,188,212,.55)"></path>
        </marker>
        <marker id="arrow-repair" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M 0 0 L 10 5 L 0 10 z" fill="rgba(96,170,255,.72)"></path>
        </marker>
      </defs>
      <rect class="lane-bg"        x="22" y="68"  width="${SVG_W - 44}" height="216" rx="26"></rect>
      <rect class="lane-bg repair" x="22" y="318" width="${SVG_W - 44}" height="140" rx="22"></rect>
      <text x="50" y="100" class="lane-title">主执行链路</text>
      <text x="50" y="122" class="lane-desc">Planner / Researcher / Analyst 组织任务与上下文，Executor 作为状态外壳委托给 CodeAct 与 Runtime。</text>
      <text x="50" y="348" class="lane-title">${showRepair ? "Repair 回路（本次真实触发）" : "Repair 预留分支"}</text>
      <text x="50" y="368" class="lane-desc">${showRepair
        ? "Runtime 检测到可修复错误后，将失败代码、报错信息和 helper 约束一起送回 LLM 生成修复版本，再复跑。"
        : "Repair 分支始终存在；只有当 Runtime 发现可修复错误（字段缺失、约束冲突、执行报错）时才会激活。"
      }</text>
      ${mainPaths}
      ${nodes.map(renderSvgNode).join("")}
      ${repairNodeHtml}
    </svg>
  `;
}

function renderFlowPath({ id, variant, d }) {
  const active  = state.replay.activePathIds.includes(id);
  const visited = state.replay.visitedPaths.includes(id);
  const cls = `${variant === "repair" ? "repair-flow" : "flow-line"}${visited ? " is-visited" : ""}${active ? " is-active" : ""}`;
  const marker = variant === "repair" ? "arrow-repair" : "arrow-main";
  const glow = active ? `<circle class="flow-glow${variant === "repair" ? " repair" : ""}" r="5.5">
    <animateMotion dur="${variant === "repair" ? "1.1s" : ".95s"}" repeatCount="indefinite" rotate="auto">
      <mpath href="#${id}"></mpath>
    </animateMotion></circle>` : "";
  return `<path id="${id}" class="${cls}" marker-end="url(#${marker})" d="${d}" />${glow}`;
}

function renderSvgNode(node) {
  const isSpotlight = node.id === "codeact" && !node.active;
  const cls = buildNodeBoxClass(node, isSpotlight);
  const cx  = node.x + node.width / 2;
  const statusCls = `node-status status-${node.status}${node.active ? " is-active" : ""}`;
  const ring = isSpotlight
    ? `<rect class="spotlight-ring" x="${node.x - 7}" y="${node.y - 7}" width="${node.width + 14}" height="${node.height + 14}" rx="28"></rect>`
    : "";
  return `
    <g>
      ${ring}
      <rect class="${cls}" x="${node.x}" y="${node.y}" width="${node.width}" height="${node.height}" rx="22"></rect>
      <circle class="status-dot ${node.status}" cx="${node.x + node.width - 15}" cy="${node.y + 15}" r="4.5"></circle>
      <text x="${cx}" y="${node.y + 20}"  class="node-kicker" text-anchor="middle">${escapeHtml(node.id)}</text>
      <text x="${cx}" y="${node.y + 56}"  class="node-label"  text-anchor="middle">${escapeHtml(node.title)}</text>
      <text x="${cx}" y="${node.y + 80}"  class="node-sub"    text-anchor="middle">${escapeHtml(node.subtitle)}</text>
      <text x="${cx}" y="${node.y + 98}"  class="${statusCls}" text-anchor="middle">${escapeHtml(formatNodeStatus(node.status, node))}</text>
      <rect class="svg-hit" data-node-id="${node.id}" x="${node.x}" y="${node.y}" width="${node.width}" height="${node.height}" rx="22"></rect>
    </g>`;
}

function buildNodeBoxClass(node, isSpotlight = false) {
  return `node-box status-${node.status}`
    + (node.selected   ? " is-selected"  : "")
    + (node.active     ? " is-active"    : "")
    + (node.visited    ? " is-visited"   : "")
    + (isSpotlight     ? " is-spotlight" : "");
}

function formatNodeStatus(status, node) {
  if (node.active)   return "RUNNING";
  if (node.selected) return "DETAIL";
  if (status === "done") return node.visited ? "PASSED" : "READY";
  if (status === "fail") return "FAILED";
  if (status === "wait") return "PENDING";
  return "ACTIVE";
}

// ─── Chain Detail Panel ──────────────────────────────────────
function renderChainDetail() {
  const detail = buildChainDetail(getDisplayedChainNodeId(), getCurrentSample());
  refs.chainDetailCard.innerHTML = `
    <div class="detail-card-title">${escapeHtml(detail.title)}</div>
    <div class="detail-card-text">${escapeHtml(detail.text)}</div>
    <div class="metric-grid">
      ${detail.metrics.map((m) => `
        <div class="metric-card">
          <div class="metric-label">${escapeHtml(m.label)}</div>
          <div class="metric-value">${escapeHtml(m.value)}</div>
        </div>`).join("")}
    </div>
  `;
}

function buildChainDetail(nodeId, sample) {
  const g          = getCurrentGroup();
  const structured = g.fullAgent.structured;
  const compare    = getCodeactComparison(g);
  const withCodeact = compare.withCodeact;
  const withoutCodeact = compare.withoutCodeact;
  const route      = getRouteTrace(sample);
  const runtime    = getRuntimeTrace(sample);
  const strategy   = sample?.execution_result?.selected_strategy || runtime?.selected_strategy || "llm_generate";

  const map = {
    planner: {
      title: "Planner / 任务拆解",
      text:  "Planner 先把题目目标、输出格式和任务边界规范化，后面的节点才会围绕同一套 required fields 和 answer format 工作。",
      metrics: [
        { label: "当前任务组",  value: `${g.title} · ${g.subtitle}` },
        { label: "代表样例",    value: `Round ${sample.round}` },
        { label: "数据集",      value: g.datasets.join(" / ") },
        { label: "结果来源",    value: state.dataset.meta.source === "repo-json" ? "真实 JSON" : "快照" },
      ],
    },
    researcher: {
      title: "Researcher / 上下文取材",
      text:  "Researcher 负责把题目、artifact 和中间上下文组织起来，决定 CodeAct 看到的是完整表格线索还是残缺信息。",
      metrics: [
        { label: "Datasets",      value: g.datasets.join(" / ") },
        { label: "Artifact Count",value: String(route?.artifact_count || 0) },
        { label: "Route",         value: route?.route || "N/A" },
        { label: "Round",         value: `${sample.round}` },
      ],
    },
    analyst: {
      title: "Analyst / 分析与压缩",
      text:  "Analyst 把上游材料压缩成统一的 Structured 中间表示，让「有 CodeAct」和「无 CodeAct」两条路径共享同一份输入，差异只留给执行方式本身。",
      metrics: [
        { label: "Struct Tokens",     value: formatInt(structured.metrics.total_tokens || 0) },
        { label: "Saved Chars",       value: formatInt(structured.metrics.context_saved_chars || 0) },
        { label: "No CodeAct",        value: `${withoutCodeact.total_correct}/${withoutCodeact.total_fields}` },
        { label: "With CodeAct",      value: `${withCodeact.total_correct}/${withCodeact.total_fields}` },
      ],
    },
    executor: {
      title: "Executor / 执行外壳",
      text:  "Executor 不是第二个回答器，不会再单独起一套求解逻辑。它只负责把状态送进 CodeAct 执行栈，真正决定结果的是 CodeAct 与 Runtime。",
      metrics: [
        { label: "Struct LLM Calls",  value: formatInt(structured.metrics.llm_calls || 0) },
        { label: "Group",             value: g.id },
        { label: "No CodeAct",        value: `${withoutCodeact.total_correct}/${withoutCodeact.total_fields}` },
        { label: "With CodeAct",      value: `${withCodeact.total_correct}/${withCodeact.total_fields}` },
      ],
    },
    codeact: {
      title: "CodeAct / 生成或修复代码",
      text:  "CodeAct 的核心价值不是生成解释，而是把问题转成一段真正可执行、可校验、可复跑的 Python 代码。只要最终答案能被 Runtime 接住，它就不是纯文本猜测。",
      metrics: [
        { label: "Strategy",      value: strategy },
        { label: "Req Fields",    value: (route?.required_fields || []).join(", ") || "N/A" },
        { label: "Final Answer",  value: trimText(sample.final_answer || "未成功产出", 40) },
        { label: "Summary",       value: trimText(sample.execution_summary || "", 36) },
      ],
    },
    runtime: {
      title: "Runtime / 受限执行与校验",
      text:  "Runtime 会在固定 helper、AST 约束和字段校验下运行代码。它的意义是把「答对/答错/错在哪里」变成可观测信号，再决定是否进入 repair。",
      metrics: [
        { label: "Runtime OK",      value: runtime?.ok ? "true" : "false" },
        { label: "Duration",        value: `${formatSeconds(runtime?.duration_s || 0)}s` },
        { label: "Missing Fields",  value: String(runtime?.missing_required_fields?.length || 0) },
        { label: "Error",           value: trimText(runtime?.error || "None", 40) },
      ],
    },
    summarizer: {
      title: "Summarizer / 最终答案回填",
      text:  "Summarizer 负责把执行结果规范化为最终输出。它接收的是已经被 Runtime 校验过的结构化结果，而不是自由生成的一段回答文本。",
      metrics: [
        { label: "Final Answer",    value: trimText(sample.final_answer || "未成功产出", 40) },
        { label: "No CodeAct",      value: `${withoutCodeact.total_correct}/${withoutCodeact.total_fields}` },
        { label: "With CodeAct",    value: `${withCodeact.total_correct}/${withCodeact.total_fields}` },
        { label: "Delta Correct",   value: `${(withCodeact.total_correct || 0) - (withoutCodeact.total_correct || 0)}` },
      ],
    },
    repair: {
      title: "LLM Repair / 基于报错回修",
      text:  "Repair 分支只在 Runtime 发现可修复错误时进入。把失败代码、执行报错和 helper 约束一起送回大模型，让第二次生成带着真实错误信号修代码。",
      metrics: [
        { label: "Trigger",       value: strategy === "llm_repair" ? "runtime failure" : "not triggered" },
        { label: "Strategy",      value: strategy },
        { label: "Runtime Error", value: trimText(runtime?.error || "None", 40) },
        { label: "Final Answer",  value: trimText(sample.final_answer || "未成功产出", 40) },
      ],
    },
  };

  return map[nodeId] || map.codeact;
}

// ─── Replay ──────────────────────────────────────────────────
function startReplay() {
  const sample = getCurrentSample();
  if (!sample) return;
  clearReplayTimers();
  Object.assign(state.replay, {
    running: true, mode: "single", activeNodeId: null, activePathIds: [],
    visitedNodes: [], visitedPaths: [], focusNodeId: null,
    statusText: "准备启动真实链路回放…",
    dualResultReady: false,
    dualResultKey: getSampleKey(sample),
  });
  renderChain();
  renderPipelineResults();

  const seq = buildReplaySequence(sample);
  let delay = 180;
  seq.forEach((step, i) => {
    const t = window.setTimeout(() => {
      applyReplayStep(step);
      if (i === seq.length - 1) {
        const ft = window.setTimeout(() => finishReplay(sample), 720);
        state.replay.timers.push(ft);
      }
    }, delay);
    state.replay.timers.push(t);
    delay += step.duration;
  });
}

function buildReplaySequence(sample) {
  const runtime  = getRuntimeTrace(sample);
  const strategy = sample?.execution_result?.selected_strategy || runtime?.selected_strategy || "llm_generate";
  const seq = [
    { kind: "node", id: "planner",              label: "Planner 正在识别题目目标与输出格式",       duration: 560 },
    { kind: "path", id: "planner-researcher",   label: "主链路流向 Researcher",                   duration: 260 },
    { kind: "node", id: "researcher",           label: "Researcher 正在组织 artifact 与上下文",    duration: 620 },
    { kind: "path", id: "researcher-analyst",   label: "主链路流向 Analyst",                      duration: 260 },
    { kind: "node", id: "analyst",              label: "Analyst 正在压缩中间表示",                 duration: 680 },
    { kind: "path", id: "analyst-executor",     label: "主链路进入执行外壳",                       duration: 260 },
    { kind: "node", id: "executor",             label: "Executor 将状态委托给 CodeAct",            duration: 520 },
    { kind: "path", id: "executor-codeact",     label: "执行流进入 CodeAct",                      duration: 260 },
    { kind: "node", id: "codeact",              label: strategy === "llm_repair" ? "CodeAct 生成初始版本代码" : "CodeAct 生成可执行代码", duration: 760 },
    { kind: "path", id: "codeact-runtime",      label: "代码提交 Runtime 执行与校验",              duration: 300 },
    { kind: "node", id: "runtime",              label: strategy === "llm_repair"
        ? "Runtime 检测到可修复错误，准备进入 Repair"
        : runtime?.ok ? "Runtime 执行通过，结果可回填" : "Runtime 执行失败，当前样例未通过",        duration: 820 },
  ];

  if (strategy === "llm_repair") {
    seq.push(
      { kind: "path", id: "runtime-repair",  label: "错误信号送入 LLM Repair",              duration: 320 },
      { kind: "node", id: "repair",          label: "LLM Repair 结合报错与 helper 约束修代码", duration: 920 },
      { kind: "path", id: "repair-codeact",  label: "修复结果返回 CodeAct",                  duration: 320 },
      { kind: "node", id: "codeact",         label: "CodeAct 输出修复版本代码",               duration: 720 },
      { kind: "path", id: "codeact-runtime", label: "修复版本再次提交 Runtime",               duration: 300 },
      { kind: "node", id: "runtime",         label: runtime?.ok ? "Runtime 复跑通过，结果进入回填阶段" : "Runtime 复跑仍失败，链路停止", duration: 840 },
    );
  }

  if (sample.final_answer) {
    seq.push(
      { kind: "path", id: "runtime-summarizer", label: "结果流向 Summarizer", duration: 300 },
      { kind: "node", id: "summarizer",         label: "Summarizer 回填 final_answer",       duration: 780 },
    );
  }
  return seq;
}

function applyReplayStep(step) {
  if (step.kind === "node") {
    state.replay.activeNodeId  = step.id;
    state.replay.activePathIds = [];
    if (!state.replay.visitedNodes.includes(step.id)) state.replay.visitedNodes.push(step.id);
    state.replay.focusNodeId = step.id;
  } else {
    state.replay.activeNodeId  = null;
    state.replay.activePathIds = [step.id];
    if (!state.replay.visitedPaths.includes(step.id)) state.replay.visitedPaths.push(step.id);
  }
  state.replay.statusText = step.label;
  renderChain();
  renderPipelineResults();
}

function finishReplay(sample) {
  Object.assign(state.replay, {
    running: false, mode: "single", activeNodeId: null, activePathIds: [], focusNodeId: null,
    statusText: sample.final_answer ? `回放完成：${sample.final_answer}` : "回放完成：当前样例没有成功产出 final_answer。",
  });
  clearReplayTimers();
  renderChain();
  renderPipelineResults();
}

function stopReplay() {
  if (!state.replay.running && !state.replay.timers.length) return;
  clearReplayTimers();
  Object.assign(state.replay, {
    running: false, mode: "single", activeNodeId: null, activePathIds: [], focusNodeId: null,
    statusText: "已停止回放。点击「播放执行流」可重新播放。",
    dualResultReady: false,
  });
  renderPipelineResults();
}

function clearReplayTimers() {
  state.replay.timers.forEach((t) => window.clearTimeout(t));
  state.replay.timers = [];
}

// ─── Compare Render ──────────────────────────────────────────
function renderCompare() {
  const g = getCurrentGroup();
  const compare = getCodeactComparison(g);
  const withCodeact = compare.withCodeact;
  const withoutCodeact = compare.withoutCodeact;
  refs.compareSummary.innerHTML =
    renderProtocolCard("no-codeact", withoutCodeact) +
    renderProtocolCard("with-codeact", withCodeact);

  const rows = [
    { label: "Correct Fields", note: "越高越好", better: "higher", formatter: formatInt,
      leftLabel: "No CodeAct", rightLabel: "With CodeAct", leftClass: "no-codeact", rightClass: "with-codeact",
      leftValue: withoutCodeact.total_correct || 0, rightValue: withCodeact.total_correct || 0 },
    { label: "Accuracy", note: "越高越好", better: "higher", formatter: formatPercent,
      leftLabel: "No CodeAct", rightLabel: "With CodeAct", leftClass: "no-codeact", rightClass: "with-codeact",
      leftValue: withoutCodeact.overall_accuracy || 0, rightValue: withCodeact.overall_accuracy || 0 },
    { label: "Wrong Fields", note: "越低越好", better: "lower", formatter: formatInt,
      leftLabel: "No CodeAct", rightLabel: "With CodeAct", leftClass: "no-codeact", rightClass: "with-codeact",
      leftValue: Math.max((withoutCodeact.total_fields || 0) - (withoutCodeact.total_correct || 0), 0),
      rightValue: Math.max((withCodeact.total_fields || 0) - (withCodeact.total_correct || 0), 0) },
  ];
  refs.compareBars.innerHTML = rows.map(renderBarRow).join("");
}

function renderProtocolCard(protocol, data) {
  const withCodeact = protocol === "with-codeact";
  const score = `${data.total_correct}/${data.total_fields}`;
  const validation = withCodeact ? "ON" : "OFF";
  return `
    <article class="protocol-card">
      <div class="protocol-card-head">
        <div class="protocol-card-title">${withCodeact ? "With CodeAct" : "No CodeAct"}</div>
        <span class="protocol-tag ${protocol}">${withCodeact ? "Structured + Runtime" : "Structured Only"}</span>
      </div>
      <div class="metric-grid">
        <div class="metric-card"><div class="metric-label">Correct</div><div class="metric-value">${score}</div></div>
        <div class="metric-card"><div class="metric-label">Accuracy</div><div class="metric-value">${formatPercent(data.overall_accuracy || 0)}</div></div>
        <div class="metric-card"><div class="metric-label">Wrong Fields</div><div class="metric-value">${formatInt(Math.max((data.total_fields || 0) - (data.total_correct || 0), 0))}</div></div>
        <div class="metric-card"><div class="metric-label">Validation</div><div class="metric-value">${validation}</div></div>
      </div>
    </article>`;
}

function renderBarRow(row) {
  const max    = Math.max(row.leftValue, row.rightValue, 1);
  let winner;
  if (row.better === "higher") winner = row.leftValue > row.rightValue ? row.leftLabel : row.leftValue < row.rightValue ? row.rightLabel : "Tie";
  else                         winner = row.leftValue < row.rightValue ? row.leftLabel : row.leftValue > row.rightValue ? row.rightLabel : "Tie";
  return `
    <div class="bar-row">
      <div class="bar-head">
        <strong>${escapeHtml(row.label)}</strong>
        <span class="bar-note muted">· ${escapeHtml(row.note)}</span>
        <span class="mini-pill" style="margin-left:auto">Winner: ${winner}</span>
      </div>
      <div class="bar-lanes">
        <div class="bar-lane">
          <span class="bar-lbl">${escapeHtml(row.leftLabel)}</span>
          <div class="bar-track"><div class="bar-fill ${row.leftClass}" style="width:${(row.leftValue / max) * 100}%"></div></div>
          <span class="bar-lbl">${escapeHtml(row.formatter(row.leftValue))}</span>
        </div>
        <div class="bar-lane">
          <span class="bar-lbl">${escapeHtml(row.rightLabel)}</span>
          <div class="bar-track"><div class="bar-fill ${row.rightClass}" style="width:${(row.rightValue / max) * 100}%"></div></div>
          <span class="bar-lbl">${escapeHtml(row.formatter(row.rightValue))}</span>
        </div>
      </div>
    </div>`;
}

// ─── Trace Render ────────────────────────────────────────────
function renderTrace() {
  const g      = getCurrentGroup();
  const sample = getCurrentSample();
  if (!sample) {
    refs.traceCard.innerHTML  = '<div class="trace-question">当前没有可展示的真实 CodeAct 样例。</div>';
    refs.sampleTabs.innerHTML = "";
    refs.sampleTabPanel.innerHTML = '<div class="stab-panel-body">No sample available.</div>';
    refs.codeBlock.textContent    = "# No codeact trace available";
    return;
  }
  const route    = getRouteTrace(sample);
  const runtime  = getRuntimeTrace(sample);
  const strategy = sample?.execution_result?.selected_strategy || runtime?.selected_strategy || "llm_generate";
  const gNum     = g.id.replace("group", "");

  refs.traceCard.innerHTML = `
    <div class="trace-top">
      <span class="status-pill ${runtime?.ok ? "ok" : "fail"}">${runtime?.ok ? "Runtime OK" : "Runtime Failed"}</span>
      <span class="status-pill ${strategy === "llm_repair" ? "repair" : "ok"}">${escapeHtml(strategy)}</span>
      <span class="mini-pill">Round ${sample.round}</span>
    </div>
    <div class="terminal-card">
      <div class="terminal-label">真实实验命令</div>
      <div class="terminal-code">python3 -u task/data_anas/run_codeact_group_probe.py --group ${gNum}</div>
    </div>
    <div>
      <div class="terminal-label">题目</div>
      <p class="trace-question">${escapeHtml(sample.question)}</p>
    </div>
    <div class="trace-list">${renderTraceItems(sample, route, runtime, strategy)}</div>
    <div class="answer-card">
      <div class="answer-label">最终输出</div>
      <div class="answer-value">${escapeHtml(sample.final_answer || sample.execution_result.error || "未产出 final_answer")}</div>
    </div>`;

  refs.codeBlock.textContent = sample.execution_code || "# No execution code";
}

function renderTraceItems(sample, route, runtime, strategy) {
  const reqFields  = (route?.required_fields || []).join(", ") || "N/A";
  const routeText  = route ? `检测到 ${route.artifact_count} 个 CSV artifact，进入 ${route.route} 路由。` : "未记录 route 信息。";
  const stratText  = strategy === "llm_repair"
    ? "初始代码未通过约束或字段校验，系统进入一次 repair，再重新执行。"
    : "CodeAct 直接生成可执行代码，未触发 repair。";
  const runtimeText = runtime
    ? runtime.ok ? `Runtime 执行成功，耗时 ${formatSeconds(runtime.duration_s || 0)}s。`
                 : `Runtime 失败：${runtime.error || "unknown error"}`
    : "未记录 runtime 信息。";
  const fieldText = runtime?.missing_required_fields?.length
    ? `缺失字段：${runtime.missing_required_fields.join(", ")}`
    : `required_fields 已全部落盘：${reqFields}`;

  return [
    ["Step 1 · Route",          routeText],
    ["Step 2 · Required Fields", `当前样例要求输出字段为：${reqFields}`],
    ["Step 3 · CodeAct",         stratText],
    ["Step 4 · Runtime",         runtimeText],
    ["Step 5 · Answer Check",    fieldText],
  ].map(([title, text]) => `
    <div class="trace-item">
      <div class="trace-item-title">${escapeHtml(title)}</div>
      <div class="trace-item-text">${escapeHtml(text)}</div>
    </div>`).join("");
}

// ─── Sample Tabs ─────────────────────────────────────────────
function renderSampleTabs() {
  const sample = getCurrentSample();
  if (!sample) {
    refs.sampleTabs.innerHTML     = "";
    refs.sampleTabPanel.innerHTML = '<div class="stab-panel-body">No sample available.</div>';
    return;
  }

  const tabs = [
    { id: "prompt", label: "Prompt" },
    { id: "fields", label: "Required Fields" },
    { id: "answer", label: "Final Answer" },
  ];

  refs.sampleTabs.innerHTML = tabs.map((t) =>
    `<button class="stab ${state.sampleView === t.id ? "is-active" : ""}" data-tab-id="${t.id}">${t.label}</button>`
  ).join("");

  refs.sampleTabs.querySelectorAll(".stab").forEach((btn) => {
    btn.addEventListener("click", () => {
      const tid = btn.dataset.tabId;
      if (!tid || tid === state.sampleView) return;
      state.sampleView = tid;
      renderSampleTabs();
    });
  });

  const panel = buildSampleTabPanel(sample, state.sampleView);
  refs.sampleTabPanel.innerHTML = `
    <div class="stab-panel-label">${escapeHtml(panel.label)}</div>
    <div class="stab-panel-body">${escapeHtml(panel.body)}</div>`;
}

function buildSampleTabPanel(sample, view) {
  const route    = getRouteTrace(sample);
  const runtime  = getRuntimeTrace(sample);
  const reqFields = route?.required_fields || [];

  if (view === "fields") {
    return {
      label: "Required Fields",
      body:  reqFields.length
        ? reqFields.map((f, i) => `${i + 1}. ${f}`).join("\n")
        : "当前样例未记录 required_fields。",
    };
  }
  if (view === "answer") {
    return {
      label: "Final Answer",
      body:  sample.final_answer || sample.execution_result.error || "当前样例未成功产出 final_answer。",
    };
  }
  const reqStr    = reqFields.length ? reqFields.join(", ") : "N/A";
  const expected  = sample.expected_format || "Expected answer format 未在当前结果文件中记录。";
  const routeHint = route?.route || "generic_csv_question";
  return {
    label: "Prompt Snapshot",
    body: [
      "Task Query:",      sample.question || "N/A",
      "",
      "Expected Format:", expected,
      "",
      "Required Fields:", reqStr,
      "",
      "Route Hint:",      routeHint,
      "",
      "Runtime Hint:",    runtime?.ok
        ? "Use restricted Python helpers and write values into extracted_answers / final_answer."
        : `Previous runtime error: ${runtime?.error || "unknown error"}`,
    ].join("\n"),
  };
}

// ─── Utilities ───────────────────────────────────────────────
function escapeHtml(value) {
  return String(value)
    .replaceAll("&",  "&amp;")
    .replaceAll("<",  "&lt;")
    .replaceAll(">",  "&gt;")
    .replaceAll('"',  "&quot;")
    .replaceAll("'",  "&#39;");
}

function formatInt(value)     { return Number(value || 0).toLocaleString("en-US"); }
function formatPercent(value) { return `${(Number(value || 0) * 100).toFixed(2)}%`; }
function formatSeconds(value) { return Number(value || 0).toFixed(2).replace(/\.00$/, ""); }
function trimText(value, max) {
  const t = String(value || "");
  return t.length <= max ? t : `${t.slice(0, max - 1)}…`;
}

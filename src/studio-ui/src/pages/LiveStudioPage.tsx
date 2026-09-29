import {
  Activity,
  Archive,
  Boxes,
  BrainCircuit,
  Check,
  CheckCircle2,
  CircleStop,
  Clock3,
  Code2,
  Database,
  FileCheck2,
  FileCode2,
  Fingerprint,
  FlaskConical,
  History,
  Layers3,
  ListFilter,
  PanelLeftClose,
  PanelLeftOpen,
  Pin,
  Play,
  Radio,
  RefreshCw,
  RotateCcw,
  Search,
  ShieldCheck,
  TableProperties,
  TerminalSquare,
  Waypoints,
  X,
  XCircle,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { studioApi } from "../api";
import { AgentFlowCanvas, type FlowVisualState } from "../components/AgentFlowCanvas";
import { DatasetDrawer } from "../components/DatasetDrawer";
import { formatBytes, formatNumber, formatTimestamp, shortHash } from "../format";
import type {
  Catalog,
  GeneratedProgram,
  Recipe,
  RunEvent,
  RunMode,
  RunStatus,
  RunView,
  SystemHealth,
  TaskFlow,
  TaskFlowIndex,
  TaskFlowStep,
} from "../types";

type RecordTab = "agents" | "program" | "receipts" | "artifacts" | "quality" | "events";

interface ArtifactItem {
  path: string;
  size_bytes: number;
}

const modeLabels: Array<{ id: RunMode; label: string; icon: typeof Play }> = [
  { id: "quick", label: "快速任务", icon: Play },
  { id: "scenario", label: "连续场景", icon: Waypoints },
  { id: "experiment", label: "正式实验", icon: FlaskConical },
];

const roleDefinitions = [
  { id: "planner", label: "规划 Agent", english: "Planner", icon: BrainCircuit },
  { id: "retriever", label: "检索 Agent", english: "Retriever", icon: Search },
  { id: "executor", label: "执行 Agent", english: "Executor", icon: Code2 },
  { id: "summarizer", label: "总结 Agent", english: "Summarizer", icon: FileCheck2 },
] as const;

const recordTabs: Array<{ id: RecordTab; label: string; icon: typeof Activity }> = [
  { id: "agents", label: "Agent 输入输出", icon: Waypoints },
  { id: "program", label: "生成代码 / DSL", icon: FileCode2 },
  { id: "receipts", label: "状态与回执", icon: Fingerprint },
  { id: "artifacts", label: "执行产物", icon: Archive },
  { id: "quality", label: "质量验证", icon: ShieldCheck },
  { id: "events", label: "技术事件", icon: ListFilter },
];

const terminalStatuses: RunStatus[] = ["completed", "failed", "canceled"];

function statusLabel(status: RunStatus | string) {
  return {
    queued: "排队中",
    running: "运行中",
    completed: "已完成",
    failed: "失败",
    canceled: "已取消",
    pending: "等待中",
  }[status] ?? status;
}

function roleLabel(role: string) {
  return roleDefinitions.find((item) => item.id === role.toLowerCase())?.label ?? role;
}

function eventLabel(type: string) {
  const labels: Record<string, string> = {
    RUN_QUEUED: "任务已进入队列",
    RUN_STARTED: "Runtime 已启动",
    RUN_STAGE: "运行阶段更新",
    RUN_COMPLETED: "运行完成",
    RUN_FAILED: "运行失败",
    RUN_CANCELED: "运行已取消",
    STEP_DISPATCHED: "步骤已调度",
    STEP_RUNNING: "步骤执行中",
    STEP_COMPLETED: "步骤完成",
    STEP_FAILED: "步骤失败",
    STEP_REJECTED_PRE_DISPATCH: "步骤在调度前被拒绝",
    STATE_PUBLISHED: "StateRef 已发布",
    STATE_CONSUMED: "StateRef 已消费",
    STATE_RELEASED: "StateRef 已释放",
    ARTIFACT_PUBLISHED: "ExecutionArtifactRef 已发布",
    ARTIFACT_VALIDATED: "执行产物验证通过",
    ARTIFACT_INVALIDATED: "执行产物验证失败",
    MEMORY_HYBRID_QUERIED: "共享记忆混合检索",
    REPLAY_DECIDED: "记忆兼容门完成决策",
    MEMORY_COMMIT_VERIFIED: "MemoryCommit 已验证",
    TASK_SUMMARY_METRICS: "任务指标已汇总",
    EVIDENCE_PACK_BUILT: "EvidencePack 已建立",
    RETRIEVAL_PRUNED: "重复检索已裁剪",
    ADAPTIVE_PLAN_APPROVED: "ApprovedPlan 已批准",
  };
  return labels[type] ?? type.replaceAll("_", " ");
}

function latestMetric(events: RunEvent[], key: string): number | null {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const value = events[index].metrics?.[key];
    if (typeof value === "number") return value;
  }
  return null;
}

function mergeEvents(current: RunEvent[], incoming: RunEvent) {
  if (current.some((event) => event.sequence === incoming.sequence)) return current;
  return [...current, incoming].sort((left, right) => left.sequence - right.sequence).slice(-180);
}

function hasContent(value: unknown) {
  if (Array.isArray(value)) return value.length > 0;
  if (value && typeof value === "object") return Object.keys(value).length > 0;
  return value !== null && value !== undefined && value !== "";
}

function prettyJson(value: unknown) {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function pickText(value: unknown, keys: string[]): string {
  if (!value || typeof value !== "object") return "";
  const record = value as Record<string, unknown>;
  for (const key of keys) {
    const candidate = record[key];
    if (typeof candidate === "string" && candidate.trim()) return candidate.trim();
  }
  for (const candidate of Object.values(record)) {
    if (candidate && typeof candidate === "object") {
      const nested = pickText(candidate, keys);
      if (nested) return nested;
    }
  }
  return "";
}

function roleFromStepId(stepId: string) {
  if (stepId.includes("retrieve")) return "retriever";
  if (stepId.includes("execute")) return "executor";
  if (stepId.includes("compose") || stepId.includes("summary")) return "summarizer";
  if (stepId.includes("plan")) return "planner";
  return "";
}

function inferActiveRole(run: RunView | null, flow: TaskFlow | null) {
  if (!run) return "planner";
  for (const event of [...run.latest_events].reverse()) {
    const rawRole = String(event.role || "").toLowerCase();
    const eventRole = ["planner", "retriever", "executor", "summarizer"].includes(rawRole)
      ? rawRole
      : roleFromStepId(event.step_id || "");
    if (eventRole && /STEP_|ARTIFACT_|EVIDENCE_|ADAPTIVE_PLAN/.test(event.event_type || "")) return eventRole;
  }
  const stage = `${run.current_stage} ${run.error}`.toLowerCase();
  if (stage.includes("planner")) return "planner";
  if (stage.includes("retriev")) return "retriever";
  if (stage.includes("executor") || stage.includes("code") || stage.includes("artifact")) return "executor";
  if (stage.includes("summar")) return "summarizer";
  if (run.status === "completed") return "summarizer";
  const pending = flow?.steps.find((step) => !["completed", "failed"].includes(step.status.toLowerCase()));
  return pending?.role || "planner";
}

function buildRoleStates(run: RunView | null, flow: TaskFlow | null, activeRole: string) {
  const states: Record<string, FlowVisualState> = {
    planner: "waiting",
    retriever: "waiting",
    executor: "waiting",
    summarizer: "waiting",
  };
  for (const step of flow?.steps ?? []) {
    const status = step.status.toLowerCase();
    if (status === "completed") states[step.role] = "done";
    else if (status.includes("fail") || status.includes("reject")) states[step.role] = "error";
    else if (status === "running") states[step.role] = "active";
  }
  if (run?.status === "running" || run?.status === "queued") {
    if (states[activeRole] !== "done") states[activeRole] = "active";
  }
  if (run?.status === "failed") states[activeRole] = "error";
  if (run?.status === "completed") {
    for (const role of Object.keys(states)) states[role] = "done";
  }
  return states;
}

function JsonInspector({ value, empty = "暂无结构化数据" }: { value: unknown; empty?: string }) {
  if (!hasContent(value)) return <div className="live-json-empty">{empty}</div>;
  return <pre className="live-json"><code>{prettyJson(value)}</code></pre>;
}

function RefList({ refs }: { refs: string[] }) {
  if (!refs.length) return null;
  return <div className="live-ref-list">{refs.map((ref) => <code title={ref} key={ref}>{shortHash(ref, 24)}</code>)}</div>;
}

function EmptyState({ title, detail }: { title: string; detail: string }) {
  return <div className="live-empty"><Activity size={22} /><strong>{title}</strong><span>{detail}</span></div>;
}

function transformSummary(step: TaskFlowStep) {
  if (step.role === "planner") return "模型生成候选 DAG，Controller 校验 Capability、合同和 Ref 依赖后编译为 ApprovedPlan。";
  if (step.role === "retriever") return "将任务目标转换为受限查询，在批准的数据范围内检索并组装带定位信息的 EvidencePack。";
  if (step.role === "executor" && step.execution_kind === "python") return "生成受限 Python，通过 AST/Policy 审计后在非 root bwrap 中执行。";
  if (step.role === "executor") return "生成 Transform DSL，经 Schema 校验后由确定性解释器执行。";
  if (step.role === "summarizer") return "消费 EvidencePack 与 ExecutionArtifactRef，生成带引用的 ClaimSet。";
  return step.transform.summary;
}

function ProgramStages({ program }: { program: GeneratedProgram | null }) {
  const python = program?.kind === "python";
  const stages = python
    ? ["模型生成 Python", "AST / Policy", "非 root bwrap", "产物验证"]
    : ["模型生成 DSL", "Schema 校验", "确定性解释器", "产物验证"];
  return (
    <div className="live-program-stages">
      {stages.map((stage, index) => <div className={program?.source ? "is-done" : index === 0 ? "is-active" : ""} key={stage}><span>{program?.source ? <Check size={10} /> : index + 1}</span><strong>{stage}</strong></div>)}
    </div>
  );
}

function AgentInspector({
  step,
  program,
  follow,
  onFollow,
  showFollow = true,
}: {
  step: TaskFlowStep | null;
  program: GeneratedProgram | null;
  follow: boolean;
  onFollow: () => void;
  showFollow?: boolean;
}) {
  if (!step) return (
    <section className="live-agent-inspector live-agent-inspector--empty">
      <header className="live-agent-inspector__header">
        <div><span><Activity size={16} /></span><div><strong>当前 Agent</strong><small>等待类型化运行数据</small></div></div>
        <div><span className="validation-badge validation-badge--pending">等待输出</span></div>
      </header>
      <EmptyState title="等待 Agent 结构化输出" detail="流程画布会持续保留；Planner 产物形成后，这里自动展示输入对象、转换过程和验证输出。" />
    </section>
  );
  const definition = roleDefinitions.find((item) => item.id === step.role) ?? roleDefinitions[0];
  const Icon = definition.icon;
  const showProgram = step.role === "executor" && program && program.kind !== "none";
  return (
    <section className="live-agent-inspector">
      <header className="live-agent-inspector__header">
        <div><span><Icon size={16} /></span><div><strong>{definition.label}</strong><small>{definition.english} · {step.step_id}</small></div></div>
        <div><code>{step.capability_id}</code><span className={`validation-badge validation-badge--${step.validation.status}`}>{step.validation.status === "verified" ? "验证通过" : statusLabel(step.status)}</span>{showFollow && <button className={follow ? "follow-button is-active" : "follow-button"} onClick={onFollow} title="自动跟随当前 Agent"><Pin size={13} />{follow ? "跟随运行" : "已固定"}</button>}</div>
      </header>
      <div className="live-agent-inspector__grid">
        <article className="live-io-column live-io-column--input">
          <div className="live-io-column__heading"><span>01</span><div><strong>输入对象</strong><small>{step.input.object_type}</small></div></div>
          <p>{step.input.summary || "由 Runtime 注入已验证对象。"}</p>
          <RefList refs={step.input.refs} />
          <JsonInspector value={step.input.data} />
        </article>
        <article className="live-io-column live-io-column--transform">
          <div className="live-io-column__heading"><span>02</span><div><strong>转换与执行</strong><small>{step.execution_kind}</small></div></div>
          <p>{transformSummary(step)}</p>
          {step.role === "executor" && <ProgramStages program={showProgram ? program : null} />}
          {showProgram ? (
            <div className="live-code-block"><div><span>{program.kind === "python" ? "模型生成 Python" : "TransformProgram JSON"}</span><strong>{program.source.split("\n").length} 行</strong></div><pre><code>{program.source}</code></pre></div>
          ) : hasContent(step.transform.structured_output) ? <JsonInspector value={step.transform.structured_output} /> : (
            <dl className="live-transform-ledger">
              <div><dt>模型</dt><dd>{step.transform.model || "Runtime"}</dd></div>
              <div><dt>Token</dt><dd>{formatNumber(step.transform.usage.total_tokens ?? 0)}</dd></div>
              <div><dt>路径依据</dt><dd>{step.transform.decision_note || "由 ApprovedPlan 与 Capability 合同确定"}</dd></div>
            </dl>
          )}
        </article>
        <article className="live-io-column live-io-column--output">
          <div className="live-io-column__heading"><span>03</span><div><strong>输出与验证</strong><small>{step.output.object_type}</small></div></div>
          <p>{step.output.summary || "等待类型化输出对象。"}</p>
          <RefList refs={step.output.refs} />
          {step.output.hash && <div className="live-hash"><Fingerprint size={12} /><code>{shortHash(step.output.hash, 28)}</code></div>}
          <JsonInspector value={step.output.data} />
          <div className="live-validation-list">
            {step.validation.checks.map((check) => <span className={check.passed ? "is-passed" : "is-failed"} key={check.id}>{check.passed ? <Check size={10} /> : <XCircle size={10} />}{check.label}</span>)}
          </div>
        </article>
      </div>
    </section>
  );
}

function OutcomeDock({
  run,
  flow,
  tokenCount,
  wireBytes,
  stateCount,
  memoryUse,
  taskMs,
  onOpenRecords,
}: {
  run: RunView | null;
  flow: TaskFlow | null;
  tokenCount: number | null;
  wireBytes: number | null;
  stateCount: number | null;
  memoryUse: number | null;
  taskMs: number | null;
  onOpenRecords: () => void;
}) {
  const summary = (run?.result.summary ?? run?.result.stdout ?? {}) as Record<string, unknown>;
  const answer = flow?.final_answer || pickText(summary, ["final_answer", "answer", "summary_text", "conclusion", "output"]);
  const qualityPassed = flow?.quality_passed || run?.status === "completed";
  return (
    <aside className="live-outcome-dock">
      <header><div><span>实时结果</span><strong>{run ? statusLabel(run.status) : "等待运行"}</strong></div><span className={`outcome-state outcome-state--${run?.status ?? "queued"}`}>{qualityPassed ? <CheckCircle2 size={13} /> : run?.status === "failed" ? <XCircle size={13} /> : <Clock3 size={13} />}{qualityPassed ? "质量通过" : run?.current_stage || "尚未开始"}</span></header>
      <div className="outcome-progress"><div><span>{run ? shortHash(run.run_id, 18) : "Run ID"}</span><strong>{run ? `${Math.round(run.progress * 100)}%` : "--"}</strong></div><i><span style={{ width: `${Math.max(0, Math.min(100, (run?.progress ?? 0) * 100))}%` }} /></i></div>
      <div className={run?.error ? "outcome-answer is-error" : "outcome-answer"}>
        <span>{run?.error ? "故障诊断" : answer ? "验证后的结论" : "当前阶段"}</span>
        <p>{run?.error || answer || run?.current_stage || "选择配方并开始运行。"}</p>
      </div>
      <dl className="outcome-metrics">
        <div><dt><Layers3 size={13} />Token</dt><dd>{tokenCount == null ? "--" : formatNumber(tokenCount)}</dd></div>
        <div><dt><Radio size={13} />链路字节</dt><dd>{wireBytes == null ? "--" : formatBytes(wireBytes)}</dd></div>
        <div><dt><Clock3 size={13} />任务耗时</dt><dd>{taskMs == null ? "--" : `${formatNumber(taskMs / 1000, 2)} s`}</dd></div>
        <div><dt><Boxes size={13} />状态消费</dt><dd>{stateCount == null ? "--" : formatNumber(stateCount)}</dd></div>
        <div><dt><Database size={13} />记忆使用</dt><dd>{memoryUse == null ? "--" : formatNumber(memoryUse)}</dd></div>
      </dl>
      <div className="outcome-protocol"><span><Radio size={12} />UDS + Protobuf</span><span><Boxes size={12} />shared_memory / CAS</span></div>
      <button className="outcome-record-button" onClick={onOpenRecords}><History size={15} />查看完整记录</button>
    </aside>
  );
}

function EventList({ events }: { events: RunEvent[] }) {
  if (!events.length) return <EmptyState title="等待结构化事件" detail="Runtime 事件会按真实顺序进入这里。" />;
  return <div className="live-event-list">{[...events].reverse().map((event) => <article key={event.sequence}><span className={event.event_type.includes("FAILED") ? "is-error" : event.event_type.includes("COMPLETED") || event.event_type.includes("VALIDATED") ? "is-done" : ""} /><div><strong>{eventLabel(event.event_type)}</strong><small>{event.role ? `${roleLabel(event.role)} · ` : ""}{event.step_id || event.task_id}</small></div><time>{formatTimestamp(event.timestamp)}</time></article>)}</div>;
}

function ProgramRecord({ program }: { program: GeneratedProgram | null }) {
  if (!program || program.kind === "none") return <EmptyState title="尚未生成执行程序" detail="Executor 选择执行路径后，这里会显示 Python 或 Transform DSL。" />;
  return <div className="record-program"><header><div><span>{program.kind === "python" ? "Python / CodeAct" : "Transform DSL"}</span><h3>{program.capability_id}</h3></div><dl><div><dt>模型</dt><dd>{program.model || "--"}</dd></div><div><dt>输出合同</dt><dd>{program.output_contract || "--"}</dd></div></dl></header><ProgramStages program={program} /><pre><code>{program.source}</code></pre><div className="record-program__audit"><JsonInspector value={program.policy} /><JsonInspector value={program.sandbox} /><JsonInspector value={program.result} /></div></div>;
}

function RecordDrawer({
  open,
  tab,
  run,
  runs,
  flow,
  step,
  artifacts,
  onTab,
  onClose,
  onSelectRun,
}: {
  open: boolean;
  tab: RecordTab;
  run: RunView | null;
  runs: RunView[];
  flow: TaskFlow | null;
  step: TaskFlowStep | null;
  artifacts: ArtifactItem[];
  onTab: (tab: RecordTab) => void;
  onClose: () => void;
  onSelectRun: (run: RunView) => void;
}) {
  return (
    <div className={open ? "record-drawer-shell is-open" : "record-drawer-shell"} aria-hidden={!open}>
      <button className="record-drawer-backdrop" onClick={onClose} aria-label="关闭完整记录" />
      <aside className="record-drawer" aria-label="完整运行记录">
        <header className="record-drawer__header"><div><span>完整运行记录</span><strong>{flow?.task_id || run?.recipe_name || "尚未运行"}</strong></div><div>{runs.length > 0 && <select value={run?.run_id ?? ""} onChange={(event) => { const selected = runs.find((item) => item.run_id === event.target.value); if (selected) onSelectRun(selected); }} aria-label="选择历史运行">{runs.map((item) => <option value={item.run_id} key={item.run_id}>{formatTimestamp(item.created_at)} · {item.recipe_name} · {statusLabel(item.status)}</option>)}</select>}<button className="icon-button" onClick={onClose} title="关闭"><X size={18} /></button></div></header>
        <nav className="record-drawer__tabs" role="tablist">{recordTabs.map((item) => { const Icon = item.icon; return <button className={tab === item.id ? "is-active" : ""} onClick={() => onTab(item.id)} role="tab" aria-selected={tab === item.id} key={item.id}><Icon size={15} />{item.label}</button>; })}</nav>
        <div className="record-drawer__body">
          {tab === "agents" && <AgentInspector step={step} program={flow?.generated_program ?? null} follow={false} onFollow={() => undefined} showFollow={false} />}
          {tab === "program" && <ProgramRecord program={flow?.generated_program ?? null} />}
          {tab === "receipts" && <JsonInspector value={flow?.receipts ?? {}} />}
          {tab === "artifacts" && (artifacts.length ? <div className="record-artifacts">{artifacts.map((artifact) => <div key={artifact.path}><Archive size={15} /><span>{artifact.path}</span><strong>{formatBytes(artifact.size_bytes)}</strong></div>)}</div> : <EmptyState title="暂无执行产物" detail="运行完成后会列出工作区中的允许产物。" />)}
          {tab === "quality" && <JsonInspector value={flow?.quality ?? {}} />}
          {tab === "events" && <EventList events={run?.latest_events ?? []} />}
        </div>
      </aside>
    </div>
  );
}

export function LiveStudioPage() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [runs, setRuns] = useState<RunView[]>([]);
  const [mode, setMode] = useState<RunMode>("quick");
  const [selectedRecipeId, setSelectedRecipeId] = useState("");
  const [selectedRun, setSelectedRun] = useState<RunView | null>(null);
  const [artifacts, setArtifacts] = useState<ArtifactItem[]>([]);
  const [flowIndex, setFlowIndex] = useState<TaskFlowIndex | null>(null);
  const [selectedTaskId, setSelectedTaskId] = useState("");
  const [selectedRole, setSelectedRole] = useState("planner");
  const [autoFollow, setAutoFollow] = useState(true);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [recordOpen, setRecordOpen] = useState(false);
  const [recordTab, setRecordTab] = useState<RecordTab>("agents");
  const [launching, setLaunching] = useState(false);
  const [error, setError] = useState("");
  const [datasetOpen, setDatasetOpen] = useState(false);
  const [selectedDataset, setSelectedDataset] = useState("");
  const keepWorkspaceClearRef = useRef(false);

  const loadRuns = useCallback(async () => {
    const nextRuns = await studioApi.runs();
    setRuns(nextRuns);
    setSelectedRun((current) => {
      if (!current && keepWorkspaceClearRef.current) return null;
      return current ? nextRuns.find((run) => run.run_id === current.run_id) ?? current : nextRuns[0] ?? null;
    });
  }, []);

  useEffect(() => {
    let active = true;
    Promise.all([studioApi.catalog(), studioApi.health(), studioApi.runs()])
      .then(([nextCatalog, nextHealth, nextRuns]) => {
        if (!active) return;
        setCatalog(nextCatalog);
        setHealth(nextHealth);
        setRuns(nextRuns);
        const initial = nextCatalog.recipes.find((recipe) => recipe.mode === "quick") ?? nextCatalog.recipes[0];
        setSelectedRecipeId(initial?.recipe_id ?? "");
        setSelectedDataset(initial?.dataset_ids[0] ?? nextCatalog.datasets[0]?.dataset_id ?? "");
        if (nextRuns[0]) setSelectedRun(nextRuns[0]);
      })
      .catch((reason: Error) => active && setError(reason.message));
    return () => { active = false; };
  }, []);

  useEffect(() => {
    const timer = window.setInterval(() => {
      loadRuns().catch(() => undefined);
      studioApi.health().then(setHealth).catch(() => undefined);
    }, 2500);
    return () => window.clearInterval(timer);
  }, [loadRuns]);

  useEffect(() => {
    if (!selectedRun || terminalStatuses.includes(selectedRun.status)) return;
    const lastSequence = selectedRun.latest_events.at(-1)?.sequence ?? 0;
    const source = new EventSource(`/api/v1/runs/${selectedRun.run_id}/events?after=${lastSequence}`);
    source.addEventListener("run-event", (raw) => {
      const event = JSON.parse((raw as MessageEvent).data) as RunEvent;
      setSelectedRun((current) => current && current.run_id === selectedRun.run_id
        ? { ...current, latest_events: mergeEvents(current.latest_events, event), current_stage: event.message || current.current_stage }
        : current);
    });
    source.addEventListener("stream-end", () => { source.close(); loadRuns().catch(() => undefined); });
    source.onerror = () => source.close();
    return () => source.close();
  }, [selectedRun?.run_id, selectedRun?.status, loadRuns]);

  useEffect(() => {
    setFlowIndex(null);
    setSelectedTaskId("");
    setSelectedRole("planner");
    setAutoFollow(true);
  }, [selectedRun?.run_id]);

  useEffect(() => {
    let active = true;
    if (!selectedRun) {
      setArtifacts([]);
      return () => { active = false; };
    }
    studioApi.artifacts(selectedRun.run_id)
      .then((payload) => active && setArtifacts(payload.artifacts))
      .catch(() => active && setArtifacts([]));
    return () => { active = false; };
  }, [selectedRun?.run_id, selectedRun?.status]);

  useEffect(() => {
    if (!selectedRun) return;
    let active = true;
    const refresh = () => studioApi.taskFlow(selectedRun.run_id, selectedTaskId).then((payload) => {
      if (!active) return;
      setFlowIndex(payload);
      if (!selectedTaskId && payload.selected_task_id) setSelectedTaskId(payload.selected_task_id);
    }).catch(() => active && setFlowIndex(null));
    refresh();
    if (terminalStatuses.includes(selectedRun.status)) return () => { active = false; };
    const timer = window.setInterval(refresh, 1500);
    return () => { active = false; window.clearInterval(timer); };
  }, [selectedRun?.run_id, selectedRun?.status, selectedTaskId]);

  const recipes = useMemo(() => catalog?.recipes.filter((recipe) => recipe.mode === mode) ?? [], [catalog, mode]);
  const selectedRecipe = catalog?.recipes.find((recipe) => recipe.recipe_id === selectedRecipeId) ?? recipes[0];
  const flow = flowIndex?.selected ?? null;
  const events = selectedRun?.latest_events ?? [];
  const activeRole = useMemo(() => inferActiveRole(selectedRun, flow), [selectedRun, flow]);
  const roleStates = useMemo(() => buildRoleStates(selectedRun, flow, activeRole), [selectedRun, flow, activeRole]);
  const selectedStep = (Array.isArray(flow?.steps) ? flow.steps : []).find((step) => step.role === selectedRole) ?? null;
  const tokenCount = flow?.usage.total_tokens ?? latestMetric(events, "llm_total_tokens") ?? latestMetric(events, "llm_prompt_tokens");
  const wireBytes = latestMetric(events, "total_wire_bytes") ?? latestMetric(events, "control_bytes");
  const stateCount = latestMetric(events, "semantic_state_consume_count") ?? latestMetric(events, "semantic_state_transfer_count");
  const memoryUse = latestMetric(events, "memory_consumed_count") ?? latestMetric(events, "memory_behavioral_effect_count");
  const taskMs = flow?.elapsed_ms ?? latestMetric(events, "task_ms");
  const canRun = Boolean(!selectedRun && health?.ok && health?.role_worker?.ok && selectedRecipe && !launching);

  useEffect(() => {
    if (autoFollow && activeRole) setSelectedRole(activeRole);
  }, [activeRole, autoFollow]);

  const changeMode = (nextMode: RunMode) => {
    setMode(nextMode);
    const nextRecipe = catalog?.recipes.find((recipe) => recipe.mode === nextMode);
    setSelectedRecipeId(nextRecipe?.recipe_id ?? "");
    setSelectedDataset(nextRecipe?.dataset_ids[0] ?? selectedDataset);
  };

  const selectRecipe = (recipe: Recipe) => {
    setSelectedRecipeId(recipe.recipe_id);
    setSelectedDataset(recipe.dataset_ids[0] ?? selectedDataset);
  };

  const createRun = async () => {
    if (!selectedRecipe) return;
    setLaunching(true);
    setError("");
    setFlowIndex(null);
    setSelectedTaskId("");
    setArtifacts([]);
    setSelectedRole("planner");
    setAutoFollow(true);
    try {
      const run = await studioApi.createRun(selectedRecipe.recipe_id);
      keepWorkspaceClearRef.current = false;
      setSelectedRun(run);
      setRuns((current) => [run, ...current.filter((row) => row.run_id !== run.run_id)]);
      setSidebarOpen(false);
      setAutoFollow(true);
      setSelectedRole("planner");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法创建运行");
    } finally {
      setLaunching(false);
    }
  };

  const resetWorkspace = () => {
    keepWorkspaceClearRef.current = true;
    setSelectedRun(null);
    setFlowIndex(null);
    setSelectedTaskId("");
    setArtifacts([]);
    setSelectedRole("planner");
    setAutoFollow(true);
    setSidebarOpen(true);
    setRecordOpen(false);
    setRecordTab("agents");
    setError("");
  };

  const cancelRun = async () => {
    if (!selectedRun) return;
    try { setSelectedRun(await studioApi.cancelRun(selectedRun.run_id)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "无法取消运行"); }
  };

  const selectRole = (role: string) => {
    setSelectedRole(role);
    setAutoFollow(false);
  };

  const selectHistoricalRun = (run: RunView) => {
    keepWorkspaceClearRef.current = false;
    setSelectedRun(run);
    setMode(run.mode);
    setSelectedRecipeId(run.recipe_id);
  };

  if (!catalog && !error) return <div className="page-state"><span className="loading-ring" /><p>正在载入运行目录</p></div>;

  return (
    <div className="live-page">
      <section className="live-control-bar">
        <button className="icon-button live-sidebar-toggle" onClick={() => setSidebarOpen((value) => !value)} title={sidebarOpen ? "收起配方栏" : "展开配方栏"}>{sidebarOpen ? <PanelLeftClose size={18} /> : <PanelLeftOpen size={18} />}</button>
        <div className="live-mode-segments" aria-label="任务模式">{modeLabels.map((item) => { const Icon = item.icon; return <button className={mode === item.id ? "is-active" : ""} onClick={() => changeMode(item.id)} key={item.id}><Icon size={15} />{item.label}</button>; })}</div>
        <div className="live-selected-recipe"><span>当前配方</span><strong>{selectedRecipe?.name ?? "--"}</strong><small><Clock3 size={12} />{selectedRecipe?.duration ?? "--"}</small></div>
        <div className="live-control-actions">
          <button className="secondary-button" onClick={() => setDatasetOpen(true)}><TableProperties size={16} />任务与数据</button>
          <button className="secondary-button" onClick={() => setRecordOpen(true)}><History size={16} />完整记录</button>
          {selectedRun && !terminalStatuses.includes(selectedRun.status) ? (
            <button className="danger-button" onClick={cancelRun}><CircleStop size={16} />停止</button>
          ) : selectedRun ? (
            <button className="primary-button" onClick={resetWorkspace} title="清空当前工作台，历史运行记录会继续保留"><RotateCcw size={16} />新建运行</button>
          ) : (
            <button className="primary-button" disabled={!canRun} onClick={createRun} title={!health?.role_worker?.ok ? "隔离 Agent Worker 环境未就绪" : "开始受控运行"}>{launching ? <RefreshCw className="is-spinning" size={16} /> : <Play size={16} fill="currentColor" />}{launching ? "正在创建" : "开始运行"}</button>
          )}
        </div>
      </section>

      {error && <div className="live-inline-error"><XCircle size={16} /><span>{error}</span><button onClick={() => setError("")}>关闭</button></div>}

      <section className={sidebarOpen ? "live-console" : "live-console is-sidebar-collapsed"}>
        {sidebarOpen && <aside className="live-recipe-sidebar">
          <header><div><span>白名单配方</span><strong>运行目录</strong></div><small>{recipes.length}</small></header>
          <div className="live-recipe-list">{recipes.map((recipe) => <button className={selectedRecipe?.recipe_id === recipe.recipe_id ? "is-active" : ""} onClick={() => selectRecipe(recipe)} key={recipe.recipe_id}><span><FlaskConical size={16} /></span><div><strong>{recipe.name}</strong><p>{recipe.description}</p><small>{recipe.dataset_ids.join(" · ")}</small></div></button>)}</div>
          <footer><ShieldCheck size={14} /><span><strong>受控执行</strong>只运行服务端白名单配方</span></footer>
        </aside>}

        <div className="live-stage-grid">
          <section className="live-flow-surface">
            <header className="live-flow-surface__header">
              <div><span>单任务数据流</span><strong>{flow?.task_id ?? selectedRecipe?.task_ids[0] ?? "等待任务"}</strong><p>{flow?.request_text ?? selectedRecipe?.description ?? "选择配方并开始运行。"}</p></div>
              <div>{flowIndex && flowIndex.tasks.length > 1 && <select value={flowIndex.selected_task_id} onChange={(event) => setSelectedTaskId(event.target.value)} aria-label="选择任务">{flowIndex.tasks.map((task) => <option value={task.task_id} key={task.task_id}>{task.task_id}</option>)}</select>}<span className={`run-status run-status--${selectedRun?.status ?? "queued"}`}>{selectedRun ? statusLabel(selectedRun.status) : "尚未运行"}</span></div>
            </header>
            <AgentFlowCanvas key={selectedRun?.run_id ?? "fresh-workspace"} flow={flow} states={roleStates} selectedRole={selectedRole} hasRun={Boolean(selectedRun)} onSelectRole={selectRole} />
          </section>

          <AgentInspector step={selectedStep} program={flow?.generated_program ?? null} follow={autoFollow} onFollow={() => setAutoFollow((value) => !value)} />

          <OutcomeDock run={selectedRun} flow={flow} tokenCount={tokenCount} wireBytes={wireBytes} stateCount={stateCount} memoryUse={memoryUse} taskMs={taskMs} onOpenRecords={() => setRecordOpen(true)} />
        </div>
      </section>

      <RecordDrawer open={recordOpen} tab={recordTab} run={selectedRun} runs={runs} flow={flow} step={selectedStep} artifacts={artifacts} onTab={setRecordTab} onClose={() => setRecordOpen(false)} onSelectRun={selectHistoricalRun} />
      <DatasetDrawer datasets={catalog?.datasets ?? []} selectedId={selectedDataset} open={datasetOpen} onSelect={setSelectedDataset} onClose={() => setDatasetOpen(false)} />
    </div>
  );
}

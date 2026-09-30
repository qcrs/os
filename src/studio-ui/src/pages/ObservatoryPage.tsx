import { Activity, ArrowRight, BarChart3, Check, ChevronDown, Clipboard, Database, FileCheck2, GitBranch, History, Layers3, ListOrdered, Maximize2, Minimize2, Pause, Play, RotateCcw, Search, ShieldCheck, SkipBack, SkipForward, Terminal, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { studioApi } from "../api";
import { buildFlow, valueText } from "../observatory/flow";
import type { FlowBeat, FlowModel, FlowRoute, FlowTone } from "../observatory/flow";
import type { ObservatoryCampaign, ObservatoryEvent, ObservatoryObject, ObservatoryTask } from "../types";
import "../observatory/observatory.css";

const ROLE_NAMES: Record<string, string> = { planner: "Planner", retriever: "Retriever", executor: "Executor", summarizer: "Summarizer", runtime_driver: "Runtime", runtime_supervisor: "Runtime", runtime: "Runtime", semantic_state_worker: "State worker" };
const CHAPTERS = [{ id: "F01", name: "首次协作" }, { id: "F02", name: "记忆复用" }, { id: "F12", name: "跨角色消费" }];
const TONES: Record<FlowTone, string> = { protocol: "#4263d4", state: "#0a948d", memory: "#a35d28" };
const ROUTES: Record<FlowRoute, string> = {
  plan: "M 270 118 L 270 69",
  dispatch: "M 381 151 H 408 Q 424 151 424 167 V 244 H 466",
  publish: "M 520 288 V 545 Q 520 563 502 563 H 455 V 579",
  resolve: "M 666 253 H 1000",
  "state-read": "M 588 579 V 318 Q 588 302 604 302 H 1180 Q 1196 302 1196 288",
  query: "M 623 288 V 312 Q 623 328 639 328 H 695 Q 711 328 711 344 V 532 Q 711 548 727 548 H 903 Q 919 548 919 564 V 579",
  verdict: "M 1000 579 V 556",
  "retrieve-result": "M 666 276 H 679 Q 695 276 695 292 V 347 Q 695 363 711 363 H 751",
  "memory-executor": "M 970 579 V 430 Q 970 411 951 411 H 855 V 398",
  execute: "M 951 363 H 1019",
  summarize: "M 951 364 H 1001 Q 1016 364 1016 380 V 471 H 1082",
  "memory-summarizer": "M 1180 579 V 550 Q 1180 534 1196 534 H 1215 V 515",
  result: "M 1282 481 H 1305 Q 1315 481 1315 465 V 410 Q 1315 395 1300 395 H 1285",
  commit: "M 1285 431 V 547 Q 1285 563 1269 563 H 1237 V 579",
  release: "M 375 579 V 553",
};

function shortId(id: string, max = 26) { return id.length > max ? `${id.slice(0, max - 10)}…${id.slice(-9)}` : id; }
function reached(model: FlowModel, index: number, route: FlowRoute) { return model.beats.slice(0, index + 1).some((beat) => beat.route === route); }
function stateEvidence(event: ObservatoryEvent) { return event.source_ref.path.split("/").at(-1); }
function effectLabel(value: unknown) { return value === "no_effect" ? "本轮选择未改变" : valueText(value); }
function verdictLabel(value: unknown) { return value === "degraded" ? "降级兼容" : value === "compatible" ? "兼容" : valueText(value); }
const OUTPUT_LABELS: Record<string, string> = { period: "月份", unit_id: "业务单元", period_count: "月数", revenue_cny: "收入", cost_cny: "成本", profit_cny: "利润" };
function taskSummary(task: ObservatoryTask) {
  const method = task.task_contract?.method ?? "";
  if (method.includes("verified_totals")) return "汇总已验证历史产物，并核对各业务单元结果";
  if (method.includes("plan_join")) return "关联计划与实际数据，核对各业务单元结果";
  if (method.includes("sequence")) return "按月份核对各业务单元的连续变化";
  if (method.includes("delta")) return "比较相邻月份各业务单元的变化";
  if (method.includes("summary")) return "按月份和业务单元汇总收入、成本、利润";
  return "当前归档未提供可展示的任务合同";
}
function commandTaskId(command: string, task: ObservatoryTask, available: string[]) {
  const normalized = command.trim();
  if (normalized === task.task_contract?.instructions.trim()) return task.task_id;
  const match = /^(?:执行\s*)?F\s*0?([1-9]|1[0-2])$/i.exec(normalized);
  if (!match) return null;
  const id = `F${match[1].padStart(2, "0")}`;
  return available.includes(id) ? id : null;
}
function sourcePath(ref: { path: string; json_pointer?: string }) { return `${ref.path}${ref.json_pointer ?? ""}`; }
function objectProtocol(object: ObservatoryObject | null, beat: FlowBeat) {
  if (!object) return { protocol: beat.content, payload: `${beat.from} → ${beat.to}`, purpose: beat.description };
  switch (object.object_type) {
    case "ApprovedPlan": return { protocol: "Typed plan", payload: "结构化协作计划", purpose: "Runtime 验证提案并批准执行计划" };
    case "TypedHandoff": return { protocol: "TypedHandoff", payload: `${valueText(object.fields.sender)} → ${valueText(object.fields.receiver)}`, purpose: "把当前动作、参数与授权上下文交给下一个角色" };
    case "SemanticStateRef": return { protocol: "Ref + mmap_file", payload: "数值语义矩阵的引用", purpose: "跨进程传递位置和身份，消费者按引用读取载荷" };
    case "StateReceipt": return { protocol: "StateReceipt", payload: "读取结果与证据选择", purpose: "确认 State worker 已解析、读取并留下可核查回执" };
    case "MemoryQuery/Verdict": return { protocol: "MemoryQuery + Verdict", payload: "候选记忆与兼容判断", purpose: "只有通过兼容和策略检查的候选才允许消费" };
    case "MemoryRef": return { protocol: "MemoryRef", payload: "历史验证产物的引用", purpose: "让后续任务复用已验证产物，并记录实际消费者" };
    case "Receipt": return { protocol: "ConsumeReceipt", payload: `${valueText(object.fields.source_task_id)} → ${valueText(object.fields.consumer_agent)}`, purpose: "证明记忆真的被读取，以及 replay 或 assist 的结果" };
    case "ExecutionArtifactRef": return { protocol: "ExecutionArtifactRef", payload: "当前执行与验证产物", purpose: "经 Runtime 验证后成为可提交、可复用的事实" };
    default: return { protocol: object.object_type, payload: object.label, purpose: object.summary };
  }
}

function FlowLine({ route, active, complete, tone, playing, progress }: { route: FlowRoute; active: boolean; complete: boolean; tone: FlowTone; playing: boolean; progress: number }) {
  const pathRef = useRef<SVGPathElement>(null);
  const [point, setPoint] = useState({ x: 0, y: 0 });
  useEffect(() => {
    if (active && pathRef.current) {
      const path = pathRef.current;
      const at = path.getPointAtLength(path.getTotalLength() * progress);
      setPoint({ x: at.x, y: at.y });
    }
  }, [active, progress]);
  const color = TONES[tone];
  const packet = tone === "protocol" ? route === "plan" ? "Plan" : route === "execute" ? "ArtifactRef" : route === "result" ? "Result" : "Typed" : tone === "memory" ? route === "query" ? "Query" : route === "verdict" ? "Verdict" : "MemoryRef" : route === "publish" ? "State" : route === "resolve" ? "Ref" : route === "release" ? "Release" : "Read";
  return <g className={`flow-line ${active ? "is-active" : ""} ${complete ? "is-complete" : ""}`} data-route={route}>
    {active && <path d={ROUTES[route]} stroke={color} strokeWidth="10" opacity=".09" fill="none" />}
    <path ref={pathRef} d={ROUTES[route]} fill="none" stroke={active || complete ? color : "#dfe4ec"} strokeWidth={active ? 2.8 : 1.7} strokeDasharray={tone === "memory" && route !== "commit" ? "5 5" : undefined} markerEnd={`url(#arrow-${active || complete ? tone : "muted"})`} />
    {active && <g transform={`translate(${point.x} ${point.y})`} className={playing ? "flow-packet is-playing" : "flow-packet"}>
      <circle r="11" fill={color} opacity=".12" /><circle r="5" fill={color} stroke="white" strokeWidth="2" />
      <rect x="-37" y="-32" width="74" height="18" rx="3" fill="white" stroke={color} strokeOpacity=".25" /><text y="-19" textAnchor="middle" fill={color} className="flow-packet-text">{packet}</text>
    </g>}
  </g>;
}

function ObjectLabel({ x, y, title, detail, tone = "protocol", active = false, shown = true, onClick }: { x: number; y: number; title: string; detail?: string; tone?: FlowTone; active?: boolean; shown?: boolean; onClick?: () => void }) {
  return <g transform={`translate(${x} ${y})`} className={`flow-object-label ${active ? "is-active" : ""} ${shown ? "" : "is-pending"}`} role={onClick ? "button" : undefined} tabIndex={onClick ? 0 : undefined} onClick={onClick} onKeyDown={(event) => { if ((event.key === "Enter" || event.key === " ") && onClick) { event.preventDefault(); onClick(); } }}>
    <title>{title}{detail ? ` · ${detail}` : ""}</title>
    <rect x="-8" y="-16" width={Math.max(title.length * 7.8 + 18, 86)} height="25" rx="4" fill="white" />
    <text fill={shown ? TONES[tone] : "#8e98aa"} className="flow-object-title">{title}</text>
    {detail && <text y="24" className="flow-object-detail">{detail}</text>}
  </g>;
}

function RuntimeDecision({ x, y, label, active, complete }: { x: number; y: number; label: string; active: boolean; complete: boolean }) {
  return <g transform={`translate(${x} ${y})`} className={`flow-runtime-decision ${active ? "is-active" : ""} ${complete ? "is-complete" : ""}`}><circle r="4" /><text x="9" y="4">{label}</text></g>;
}

function PlaybackControls({ model, index, speed, nodesOpen, seek, setSpeed, setNodesOpen }: { model: FlowModel; index: number; speed: number; nodesOpen: boolean; seek: (next: number) => void; setSpeed: (speed: number) => void; setNodesOpen: (open: boolean) => void }) {
  return <div className="flow-controls"><div className="flow-transport"><button className="flow-icon-button" title="回到首节点" aria-label="回到首节点" onClick={() => seek(0)}><RotateCcw size={16} /></button><button className="flow-icon-button" title="上一个节点" aria-label="上一个节点" disabled={index === 0} onClick={() => seek(index - 1)}><SkipBack size={17} /></button><button className="flow-icon-button" title="下一个节点" aria-label="下一个节点" disabled={index === model.beats.length - 1} onClick={() => seek(index + 1)}><SkipForward size={17} /></button></div><div className="flow-scrubber"><input aria-label="回放节点进度" type="range" min={0} max={model.beats.length - 1} value={index} onChange={(event) => seek(Number(event.target.value))} /><div className="flow-scrubber-ticks">{model.beats.map((item, i) => <button key={item.id} className={i <= index ? "is-seen" : ""} style={{ left: `${i / (model.beats.length - 1) * 100}%` }} title={item.title} aria-label={`跳到${item.title}`} onClick={() => seek(i)} />)}</div></div><label className="flow-speed"><select aria-label="播放速度" value={speed} onChange={(event) => setSpeed(Number(event.target.value))}><option value={.5}>0.5×</option><option value={1}>1×</option><option value={1.5}>1.5×</option><option value={2}>2×</option></select></label><button className={`flow-icon-button ${nodesOpen ? "is-selected" : ""}`} title="节点目录" aria-label="节点目录" onClick={() => setNodesOpen(!nodesOpen)}><ListOrdered size={17} /></button></div>;
}

function AgentBlock({ x, y, name, title, detail, active, done, skipped, onClick, icon: Icon }: { x: number; y: number; name: string; title: string; detail: string; active: boolean; done: boolean; skipped?: boolean; onClick?: () => void; icon: typeof Activity }) {
  return <g transform={`translate(${x} ${y})`} className={`flow-agent-block ${active ? "is-active" : ""} ${done ? "is-done" : ""}`} onClick={onClick} role={onClick ? "button" : undefined} tabIndex={onClick ? 0 : undefined} onKeyDown={(event) => { if (event.key === "Enter" && onClick) onClick(); }}>
    <title>{name} · {title} · {detail}</title>
    <rect width="200" height="68" rx="6" className="flow-agent-bg" />
    <rect x="0" y="0" width="3" height="68" rx="1.5" className="flow-agent-accent" />
    <foreignObject x="14" y="15" width="23" height="24"><Icon size={21} /></foreignObject>
    <text x="48" y="28" className="flow-agent-title">{title}</text>
    <text x="48" y="49" className="flow-agent-detail">{detail}</text>
    {done && <foreignObject x="174" y="13" width="16" height="18"><Check size={15} /></foreignObject>}
    {active && !done && <circle cx="182" cy="22" r="4" className="flow-agent-active-dot" />}
    {skipped && <g transform="translate(13 82)"><rect width="173" height="24" rx="3" fill="#fbf2e8" /><text x="8" y="16" className="flow-skip-label">generation 已跳过 · 执行保留</text></g>}
  </g>;
}

function FlowCanvas({ task, model, index, playing, progress, inspect }: { task: ObservatoryTask; model: FlowModel; index: number; playing: boolean; progress: number; inspect: (id: string) => void }) {
  const beat = model.beats[index];
  const published = reached(model, index, "publish");
  const resolved = reached(model, index, "resolve");
  const read = reached(model, index, "state-read");
  const queried = reached(model, index, "query");
  const verdict = reached(model, index, "verdict");
  const consumed = reached(model, index, "memory-executor");
  const summaryConsumed = reached(model, index, "memory-summarizer");
  const committed = reached(model, index, "commit");
  const released = reached(model, index, "release");
  const active = (...routes: FlowRoute[]) => routes.includes(beat.route);
  const selectedRows = model.stateReceipt?.fields.selected_candidate_ids;
  const shape = Array.isArray(model.state?.fields.shape) ? model.state.fields.shape.join(" × ") : valueText(model.state?.fields.shape);
  const candidateCount = Number(model.query?.fields.candidate_count ?? 0);
  const decisions = (model.query?.fields.decisions ?? []) as Array<Record<string, unknown>>;
  const selectedDecision = decisions.find((decision) => decision.memory_id === model.sourceMemory?.id);
  const allowed = decisions.filter((decision) => decision.policy_approved).length;
  const executorReceipt = model.memoryReceipts.find((receipt) => receipt.fields.consumer_agent === "executor");
  const skipped = consumed && Number(executorReceipt?.fields.skipped_executor_generation) > 0;
  const line = (route: FlowRoute, tone: FlowTone) => <FlowLine key={route} route={route} tone={tone} active={active(route)} complete={reached(model, index, route)} playing={playing} progress={progress} />;
  return <svg className="flow-diagram" viewBox="0 0 1400 710" preserveAspectRatio="xMinYMin meet" aria-label={`${task.task_id} 四角色协作与状态、记忆流动图`}>
    <defs>{([...Object.entries(TONES), ["muted", "#dfe4ec"]] as Array<[string, string]>).map(([name, color]) => <marker key={name} id={`arrow-${name}`} viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7.5" markerHeight="7.5" orient="auto-start-reverse"><path d="M 1 1 L 8 5 L 1 9" fill="none" stroke={color} strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" /></marker>)}</defs>
    <g className="flow-lanes">{[151, 253, 364, 481].map((y, i) => <g key={y}><rect x="17" y={y - 47} width="1366" height="94" fill={i % 2 === 0 ? "#f8f9fc" : "#ffffff"} /><path d={`M 163 ${y} H 1360`} stroke="#e5e9f0" strokeDasharray="3 7" /></g>)}</g>
    <g className="flow-lane-labels">{[{ y: 151, name: "Planner", cn: "任务规划", icon: GitBranch }, { y: 253, name: "Retriever", cn: "信息检索", icon: Search }, { y: 364, name: "Executor", cn: "执行与验证", icon: Terminal }, { y: 481, name: "Summarizer", cn: "总结与交叉核查", icon: FileCheck2 }].map(({ y, name, cn, icon: Icon }, i) => <g transform={`translate(30 ${y - 17})`} key={name}><text className="flow-lane-number">0{i + 1}</text><foreignObject x="25" y="-2" width="20" height="20"><Icon size={18} /></foreignObject><text x="51" y="13" className="flow-lane-name">{name}</text><text x="51" y="34" className="flow-lane-cn">{cn}</text></g>)}</g>
    <g className="flow-runtime-band"><rect x="181" y="20" width="1178" height="50" rx="5" fill="#f3f5fb" /><foreignObject x="199" y="36" width="20" height="20"><ShieldCheck size={19} /></foreignObject><text x="228" y="51" className="flow-runtime-title">StateBus Runtime</text><text x="396" y="51" className="flow-runtime-detail">批准计划</text><path d="M 466 44 H 497" stroke="#bac4d8" markerEnd="url(#arrow-muted)" /><text x="516" y="51" className="flow-runtime-detail">能力授权</text><path d="M 585 44 H 616" stroke="#bac4d8" markerEnd="url(#arrow-muted)" /><text x="635" y="51" className="flow-runtime-detail">调度与 Ref 检查</text><path d="M 759 44 H 790" stroke="#bac4d8" markerEnd="url(#arrow-muted)" /><text x="809" y="51" className="flow-runtime-detail">产物验证</text><path d="M 879 44 H 910" stroke="#bac4d8" markerEnd="url(#arrow-muted)" /><text x="929" y="51" className="flow-runtime-detail">记忆准入 · 生命周期</text><text x="1338" y="51" textAnchor="end" className="flow-runtime-status">{released ? "本轮状态已释放" : committed ? "验证提交完成" : consumed ? "记忆消费已授权" : read ? "状态读取已记录" : published ? "状态已发布" : "计划已批准"}</text></g>
    <RuntimeDecision x={304} y={74} label="Plan approved" active={active("plan")} complete={reached(model, index, "plan")} />
    <RuntimeDecision x={520} y={177} label="Capability grant" active={active("dispatch")} complete={reached(model, index, "dispatch")} />
    <RuntimeDecision x={815} y={268} label="Ref resolve admitted" active={active("resolve")} complete={reached(model, index, "resolve")} />
    <RuntimeDecision x={1114} y={365} label="Artifact validated" active={active("execute")} complete={reached(model, index, "execute")} />
    <RuntimeDecision x={1010} y={566} label="Compatibility approved" active={active("verdict")} complete={reached(model, index, "verdict")} />
    <RuntimeDecision x={330} y={552} label="Release" active={active("release")} complete={reached(model, index, "release")} />
    {line("plan", "protocol")}{line("dispatch", "protocol")}{line("publish", "state")}{line("resolve", "state")}{line("state-read", "state")}{line("query", "memory")}{line("verdict", "memory")}{model.beats.some((item) => item.route === "retrieve-result") && line("retrieve-result", "protocol")}
    {model.memoryReceipts.some((receipt) => receipt.fields.consumer_agent === "executor") && line("memory-executor", "memory")}
    {line("execute", "protocol")}{line("summarize", "protocol")}
    {model.memoryReceipts.some((receipt) => receipt.fields.consumer_agent === "summarizer") && line("memory-summarizer", "memory")}
    {line("result", "protocol")}{line("commit", "memory")}{line("release", "state")}
    <AgentBlock x={181} y={118} name="Planner" title="生成协作计划" detail="ApprovedPlan" active={active("plan", "dispatch")} done={reached(model, index, "dispatch")} icon={GitBranch} onClick={() => inspect(model.beats[0].objectId)} />
    <AgentBlock x={466} y={220} name="Retriever" title="检索与生成状态" detail={published ? "SemanticState 已发布" : "证据检索 · embedding"} active={active("dispatch", "publish", "query", "verdict", "retrieve-result")} done={queried} icon={Search} onClick={() => model.state && inspect(model.state.id)} />
    <AgentBlock x={751} y={330} name="Executor" title={consumed ? "复用产物，执行验证" : "执行与产物验证"} detail={consumed ? valueText(executorReceipt?.fields.replay_class) : reached(model, index, "retrieve-result") ? "检索输入与授权已到达" : "等待输入与授权"} active={active("retrieve-result", "memory-executor", "execute")} done={reached(model, index, "execute")} skipped={skipped} icon={Terminal} onClick={() => inspect(consumed ? executorReceipt!.id : model.artifact?.id ?? "")} />
    <AgentBlock x={1082} y={447} name="Summarizer" title="总结与交叉核查" detail={summaryConsumed ? "Memory 消费 · assist" : reached(model, index, "summarize") ? "已接收 typed 交接" : "等待执行产物"} active={active("summarize", "memory-summarizer", "result")} done={reached(model, index, "result")} icon={FileCheck2} onClick={() => inspect(summaryConsumed ? model.memoryReceipts.find((receipt) => receipt.fields.consumer_agent === "summarizer")!.id : model.beats.find((item) => item.route === "summarize")?.objectId ?? "")} />
    <g transform="translate(1024 345)" className={`flow-runtime-check ${active("execute") ? "is-active" : ""}`} role="button" tabIndex={0} onClick={() => model.artifact && inspect(model.artifact.id)} onKeyDown={(event) => { if (event.key === "Enter" && model.artifact) inspect(model.artifact.id); }}><rect width="78" height="36" rx="4" /><foreignObject x="8" y="10" width="16" height="16"><ShieldCheck size={15} /></foreignObject><text x="28" y="23">验证产物</text></g>
    <g transform="translate(1260 395)" className={`flow-runtime-check ${active("result", "commit") ? "is-active" : ""}`}><rect width="51" height="36" rx="4" /><text x="8" y="23">Runtime</text></g>
    <g transform="translate(1000 220)" className={`flow-state-worker ${active("resolve", "state-read") ? "is-active" : ""}`} role="button" tabIndex={0} onClick={() => model.stateReceipt && inspect(model.stateReceipt.id)} onKeyDown={(event) => { if (event.key === "Enter" && model.stateReceipt) inspect(model.stateReceipt.id); }}><rect width="220" height="68" rx="5" /><foreignObject x="14" y="16" width="22" height="22"><Layers3 size={20} /></foreignObject><text x="46" y="28" className="flow-worker-title">State worker</text><text x="46" y="49" className="flow-worker-detail">{read ? "读取完成 · 回执已记录" : resolved ? `独立进程 · PID ${valueText(model.state?.fields.consumer_pid)}` : "独立进程 · 按 Ref 读取"}</text></g>
    <ObjectLabel x={335} y={105} title="ApprovedPlan" active={active("plan")} onClick={() => inspect(model.beats[0].objectId)} />
    <ObjectLabel x={385} y={195} title="TypedHandoff" detail="Planner → Retriever" shown={reached(model, index, "dispatch")} active={active("dispatch")} onClick={() => inspect(model.beats.find((item) => item.route === "dispatch")?.objectId ?? "")} />
    <ObjectLabel x={741} y={238} title="SemanticStateRef" tone="state" shown={resolved} active={active("resolve")} onClick={() => model.state && inspect(model.state.id)} />
    {model.beats.some((item) => item.route === "retrieve-result") && <ObjectLabel x={606} y={370} title="TypedHandoff" shown={reached(model, index, "retrieve-result")} active={active("retrieve-result")} onClick={() => inspect(model.beats.find((item) => item.route === "retrieve-result")!.objectId)} />}
    <ObjectLabel x={1230} y={300} title="StateReceipt" detail={read ? `${Array.isArray(selectedRows) ? selectedRows.length : "已读取"} 条证据 · ${effectLabel(model.stateReceipt?.fields.behavioral_effect)}` : "数值矩阵 → 证据选择"} tone="state" shown={read} active={active("state-read")} onClick={() => model.stateReceipt && inspect(model.stateReceipt.id)} />
    <ObjectLabel x={982} y={420} title="TypedHandoff" detail="Executor → Summarizer" shown={reached(model, index, "summarize")} active={active("summarize")} onClick={() => inspect(model.beats.find((item) => item.route === "summarize")?.objectId ?? "")} />
    <g transform="translate(35 590)"><foreignObject width="20" height="20"><Layers3 size={18} /></foreignObject><text x="26" y="15" className="flow-storage-heading">存储与复用</text><text x="26" y="36" className="flow-faint-caption">载荷与来源保持可见</text></g>
    <g transform="translate(310 579)" className={`flow-store flow-store--state ${active("publish", "resolve", "state-read", "release") ? "is-active" : ""}`} role="button" tabIndex={0} onClick={() => model.state && inspect(model.state.id)} onKeyDown={(event) => { if (event.key === "Enter" && model.state) inspect(model.state.id); }}>
      <rect width="360" height="111" rx="6" className="flow-store-bg" /><foreignObject x="17" y="17" width="23" height="23"><Database size={21} /></foreignObject><text x="50" y="32" className="flow-store-title">State store</text><text x="340" y="31" textAnchor="end" className="flow-store-status">{released ? "已释放" : published ? "载荷保存在此" : "等待写入"}</text>
      <text x="19" y="63" className="flow-store-value">{published ? `${shape} · ${valueText(model.state?.fields.dtype)}` : "SemanticState"}</text><text x="19" y="86" className="flow-store-meta">{published ? `${Number(model.state?.fields.size_bytes).toLocaleString()} B · ${valueText(model.state?.fields.storage_kind)}` : "数值载荷与 Ref 分离"}</text>
      <g transform="translate(278 48)" opacity={published && !released ? 1 : .3}>{Array.from({ length: 5 }, (_, row) => Array.from({ length: 6 }, (_, col) => <rect key={`${row}:${col}`} x={col * 9} y={row * 8} width="6" height="5" rx="1" fill="#0a948d" opacity={row === 0 ? .9 : .25} />))}</g>
    </g>
    <g transform="translate(823 579)" className={`flow-store flow-store--memory ${active("query", "verdict", "memory-executor", "memory-summarizer", "commit") ? "is-active" : ""}`}>
      <rect width="536" height="111" rx="6" className="flow-store-bg" /><foreignObject x="17" y="17" width="23" height="23"><Database size={21} /></foreignObject><text x="50" y="32" className="flow-store-title">Persistent Memory</text><text x="517" y="31" textAnchor="end" className="flow-store-status">{committed ? "本轮新记忆已写入" : consumed ? "实际消费已记录" : verdict ? "候选已判断" : queried ? "查询有记录" : "跨任务保存"}</text>
      {model.sourceMemory ? <g className="flow-memory-entry" role="button" tabIndex={0} onClick={() => inspect(model.sourceMemory!.id)} onKeyDown={(event) => { if (event.key === "Enter") inspect(model.sourceMemory!.id); }}><text x="19" y="64" className="flow-store-value">来源 {valueText(model.sourceMemory.fields.source_task_id)} → {task.task_id}{summaryConsumed ? " · 2 个消费者" : ""}</text><text x="19" y="87" className="flow-store-meta">{consumed ? `${verdictLabel(selectedDecision?.verdict)} · Executor replay${summaryConsumed ? " / Summarizer assist" : ""}` : verdict ? `${verdictLabel(selectedDecision?.verdict)} · ${allowed} 个获准候选` : queried ? `${candidateCount} 个候选 · 等待判断` : "历史验证产物"}</text></g> : <g><text x="19" y="64" className="flow-store-value">{queried ? "本轮无历史候选" : "等待查询"}</text><text x="19" y="87" className="flow-store-meta">{committed ? "验证产物已成为首条记忆" : "先计算、验证，再形成可复用记忆"}</text></g>}
      {committed && model.committedMemory && <g transform="translate(357 49)" className="flow-new-memory" role="button" tabIndex={0} onClick={() => inspect(model.committedMemory!.id)} onKeyDown={(event) => { if (event.key === "Enter") inspect(model.committedMemory!.id); }}><rect width="160" height="43" rx="4" fill="#fbf2e8" /><text x="12" y="18" className="flow-new-memory-title">{task.task_id} · 新 MemoryRef</text><text x="12" y="34" className="flow-new-memory-sub">验证提交 · 供后续任务使用</text></g>}
    </g>
    <ObjectLabel x={414} y={525} title={released ? "ReleaseReceipt" : "写入数值载荷"} tone="state" shown={published} active={active("publish", "release")} onClick={() => model.state && inspect(model.state.id)} />
    <ObjectLabel x={850} y={535} title={verdict ? candidateCount ? "CompatibilityVerdict" : "0 个候选" : "MemoryQuery"} tone="memory" shown={queried} active={active("query", "verdict")} onClick={() => model.query && inspect(model.query.id)} />
    {model.sourceMemory && <ObjectLabel x={843} y={453} title="MemoryRef → Receipt" detail={consumed ? `来源 ${valueText(model.sourceMemory.fields.source_task_id)} · 实际读取 ${valueText(executorReceipt?.fields.artifact_read_bytes)} B` : "获准后才允许消费"} tone="memory" shown={consumed} active={active("memory-executor")} onClick={() => executorReceipt && inspect(executorReceipt.id)} />}
    {model.memoryReceipts.some((receipt) => receipt.fields.consumer_agent === "summarizer") && <ObjectLabel x={1210} y={547} title="MemoryRef" tone="memory" shown={summaryConsumed} active={active("memory-summarizer")} onClick={() => inspect(model.memoryReceipts.find((receipt) => receipt.fields.consumer_agent === "summarizer")!.id)} />}
  </svg>;
}

function Inspector({ model, task, selected, beat, close, inspect }: { model: FlowModel; task: ObservatoryTask; selected: ObservatoryObject | null; beat: FlowBeat; close: () => void; inspect: (id: string) => void }) {
  const [tab, setTab] = useState("overview");
  const [copied, setCopied] = useState(false);
  useEffect(() => { setTab("overview"); setCopied(false); }, [selected?.id]);
  const fields = selected?.fields ?? {};
  const protocol = objectProtocol(selected, beat);
  const evidence = selected ? model.evidenceByObject[selected.id] ?? [] : beat.evidence;
  const associated = selected?.object_type === "MemoryRef" ? model.memoryReceipts.filter((object) => object.fields.memory_ref === selected.id) : selected?.object_type === "SemanticStateRef" && model.stateReceipt ? [model.stateReceipt] : [];
  const copy = async () => { await navigator.clipboard.writeText(JSON.stringify(selected ?? beat.evidence, null, 2)); setCopied(true); };
  return <aside className="flow-inspector" aria-label="对象检查"><header><div><span>对象与来源 · 当前流动对象</span><h2>{selected?.object_type ?? "NodeEvidence"}</h2></div><button className="flow-icon-button flow-inspector-close" onClick={close} title="关闭检查层" aria-label="关闭检查层"><X size={20} /></button></header><p className="flow-inspector-summary">{selected?.summary ?? beat.description}</p>{selected && <code className="flow-inspector-id">{selected.id}</code>}<div className="flow-inspector-tabs" role="tablist">{[{ id: "overview", name: "概览" }, { id: "source", name: "来源证据" }, { id: "raw", name: "原始字段" }].map((item) => <button role="tab" aria-selected={tab === item.id} key={item.id} onClick={() => setTab(item.id)}>{item.name}</button>)}</div>
    <div className="flow-inspector-content">{tab === "overview" && <><section className="flow-object-brief"><div><span>协议</span><b>{protocol.protocol}</b></div><div><span>传递内容</span><b>{protocol.payload}</b></div><div><span>作用</span><p>{protocol.purpose}</p></div></section><dl className="flow-facts"><div><dt>当前动作</dt><dd>{beat.title} · {beat.from} → {beat.to}</dd></div><div><dt>当前任务</dt><dd>{task.task_id} · {task.run_id}</dd></div>{selected?.object_type === "SemanticStateRef" ? <><div><dt>载荷位置</dt><dd>{valueText(fields.storage_kind)} · {valueText(fields.size_bytes)} B</dd></div><div><dt>表示方式</dt><dd>{valueText(fields.dtype)} [{valueText(fields.shape)}]</dd></div><div><dt>进程身份</dt><dd>{valueText(fields.producer_pid)} → {valueText(fields.consumer_pid)}</dd></div><div><dt>传递方式</dt><dd>交付 Ref，消费者按引用读取</dd></div><div><dt>传输字节</dt><dd>未测量；载荷大小不是 wire bytes</dd></div></> : selected?.object_type === "TypedHandoff" ? <><div><dt>发送方 → 接收方</dt><dd>{valueText(fields.sender)} → {valueText(fields.receiver)}</dd></div><div><dt>动作</dt><dd>{valueText(fields.step)}</dd></div><div><dt>载体</dt><dd>{valueText(fields.carrier)}</dd></div><div><dt>传递范围</dt><dd>{valueText(fields.transport_scope)}</dd></div><div><dt>参数与结果正文</dt><dd>当前归档 handoff 未收录正文；不补造字段</dd></div></> : selected?.object_type === "Receipt" ? <><div><dt>来源 → 消费者</dt><dd>{valueText(fields.source_task_id)} / {valueText(fields.source_agent)} → {valueText(fields.consumer_agent)}</dd></div><div><dt>复用方式</dt><dd>{valueText(fields.replay_class)}</dd></div><div><dt>实际读取</dt><dd>{valueText(fields.artifact_read)} · {valueText(fields.artifact_read_bytes)} B</dd></div><div><dt>generation 跳过</dt><dd>{Number(fields.skipped_executor_generation) ? "是；执行仍发生" : "否"}</dd></div><div><dt>当前输入重新计算</dt><dd>{valueText(fields.input_recomputed)}</dd></div></> : <>{Object.entries(fields).filter(([key, value]) => ["source_task_id", "source_agent", "committed", "replay_class", "verdict", "candidate_count", "capability_id", "proposal_valid", "policy_rejected", "storage_kind", "receipt_status", "behavioral_effect", "selected_candidate_ids", "artifact_read_bytes"].includes(key) && value !== null).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{valueText(value)}</dd></div>)}</>}</dl>
      {selected?.object_type === "MemoryQuery/Verdict" && <div className="flow-verdict-list">{((fields.decisions ?? []) as Array<Record<string, unknown>>).map((decision) => <article key={String(decision.memory_id)}><b>{shortId(String(decision.memory_id), 35)}</b><span>{valueText(decision.verdict)} · {decision.policy_approved ? "策略允许" : "拒绝复用"}</span><small>{valueText(decision.reasons)}</small></article>)}</div>}
      {associated.map((object) => <button className="flow-receipt-link" key={object.id} onClick={() => inspect(object.id)}><FileCheck2 size={17} /><span>{object.label}<small>{object.summary}</small></span><ArrowRight size={16} /></button>)}
      {evidence.length > 0 && <div className="flow-evidence-note"><ShieldCheck size={16} /><span>{evidence.length} 条关联来源记录。{selected?.object_type === "SemanticStateRef" ? "Runtime 记录的 actor 为 Executor；原始消费回执的执行进程为 State worker。" : "讲解节点合并关联证据，节点间播放速度不代表真实耗时。"}</span></div>}</>}
      {tab === "source" && <>{evidence.map((event) => <details key={event.id} className="flow-source-row"><summary><span>{event.kind}</span><small>{stateEvidence(event)}:{event.source_ref.line}</small></summary><p>{event.source_ref.path}</p><p>actor: {ROLE_NAMES[event.actor] ?? event.actor} · {event.time_basis}</p><pre>{JSON.stringify(event.payload, null, 2)}</pre></details>)}{!evidence.length && <p>当前归档未提供此对象的关联来源。</p>}</>}
      {tab === "raw" && <><button className="flow-copy" onClick={() => void copy()}><Clipboard size={16} />{copied ? "已复制" : "复制 JSON"}</button><pre>{JSON.stringify(selected ?? beat.evidence, null, 2)}</pre></>}
    </div></aside>;
}

function TaskPrompt({ task, available, playing, completed, togglePlay, startTask }: { task: ObservatoryTask; available: string[]; playing: boolean; completed: boolean; togglePlay: () => void; startTask: (id: string) => void }) {
  const contract = task.task_contract;
  const [command, setCommand] = useState(`执行 ${task.task_id}`);
  const [invalid, setInvalid] = useState(false);
  const commandId = commandTaskId(command, task, available);
  const currentCommand = commandId === task.task_id;
  useEffect(() => { setCommand(`执行 ${task.task_id}`); setInvalid(false); }, [task.task_id]);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!commandId) { setInvalid(true); return; }
    setInvalid(false);
    if (currentCommand) togglePlay(); else startTask(commandId);
  };
  return <section className="flow-task-prompt" aria-label="本轮任务">
    <div className="flow-task-prompt-heading"><span><Terminal size={16} />任务输入</span><small>已归档 · {task.task_id}</small></div>
    <div className="flow-task-message"><b>{task.task_id}</b><span>{taskSummary(task)}</span><small>{contract?.periods.length ? `${contract.periods[0]}${contract.periods.length > 1 ? ` 至 ${contract.periods.at(-1)}` : ""}` : "任务期间未归档"}{contract?.required_history.length ? ` · 依赖 ${contract.required_history.length} 轮` : ""}</small></div>
    <form className="flow-task-command" onSubmit={submit}><label htmlFor="flow-task-command">执行命令</label><div className="flow-task-command-row"><Terminal size={16} /><input id="flow-task-command" aria-label="执行命令" aria-invalid={invalid} value={command} onChange={(event) => { setCommand(event.target.value); setInvalid(false); }} placeholder="执行 F01" /><button className="flow-task-play" type="submit">{playing && currentCommand ? <Pause size={16} /> : completed && currentCommand ? <RotateCcw size={16} /> : <Play size={16} fill="currentColor" />}{playing && currentCommand ? "暂停" : completed && currentCommand ? "重新开始" : "开始"}</button></div>{invalid && <small className="flow-task-error" role="alert">仅支持 F01–F12 或当前任务的归档指令。</small>}</form>
    <div className="flow-task-options"><span>选择</span>{["F01", "F02", "F12"].filter((id) => available.includes(id)).map((id) => <button key={id} type="button" className={commandId === id ? "is-selected" : ""} onClick={() => { setCommand(`执行 ${id}`); setInvalid(false); }}>{id}</button>)}<select aria-label="选择命令轮次" value={commandId ?? ""} onChange={(event) => { setCommand(`执行 ${event.target.value}`); setInvalid(false); }}><option value="" disabled>其他轮次</option>{available.map((id) => <option value={id} key={id}>{id}</option>)}</select></div>
    {contract && <details className="flow-task-contract"><summary>任务合同 <ChevronDown size={14} /></summary><div><button type="button" className="flow-use-instruction" onClick={() => { setCommand(contract.instructions); setInvalid(false); }}>填入归档指令 <ArrowRight size={13} /></button><p lang="en">{contract.instructions}</p><strong>输入 schema</strong><pre>{JSON.stringify(contract.input_schemas, null, 2)}</pre><strong>输出 schema</strong><pre>{JSON.stringify(contract.output_schema, null, 2)}</pre><small>来源：{sourcePath(contract.source_ref)}</small></div></details>}
  </section>;
}

function Delivery({ task, model, inspect }: { task: ObservatoryTask; model: FlowModel; inspect: (id: string) => void }) {
  const delivery = task.delivery;
  const keys = Object.keys(task.task_contract?.output_schema ?? delivery?.rows[0] ?? {}).sort((a, b) => {
    const order = ["period", "unit_id", "period_count", "revenue_cny", "cost_cny", "profit_cny"];
    return (order.indexOf(a) < 0 ? order.length : order.indexOf(a)) - (order.indexOf(b) < 0 ? order.length : order.indexOf(b));
  });
  const consumed = model.memoryReceipts.map((receipt) => ({ source: valueText(receipt.fields.source_task_id), consumer: valueText(receipt.fields.consumer_agent), id: receipt.id }));
  return <aside className="flow-delivery" aria-label="本轮输出"><header><span><FileCheck2 size={17} />本轮输出</span><strong>{task.task_id} · 结构化交付</strong></header><div className="flow-delivery-body">
    {!delivery ? <p className="flow-delivery-missing">此来源只归档了事件、对象和回执，未归档可核验的结果正文。</p> : <>
      <div className="flow-delivery-section"><div className="flow-delivery-title"><b>计算结果</b><small>{delivery.rows.length} 行</small></div><div className="flow-result-scroll"><table><thead><tr>{keys.map((key) => <th key={key} title={key}>{OUTPUT_LABELS[key] ?? key}</th>)}</tr></thead><tbody>{delivery.rows.map((row, i) => <tr key={i}>{keys.map((key) => <td key={key}>{typeof row[key] === "number" ? row[key].toLocaleString("zh-CN") : valueText(row[key])}</td>)}</tr>)}</tbody></table></div></div>
      <section className="flow-delivery-section flow-report"><div className="flow-delivery-title"><b><FileCheck2 size={16} />引用报告</b><small>{delivery.claim_set.claims.length} 条事实</small></div><div className="flow-report-body">{delivery.claim_set.claims.map((claim) => <article key={claim.claim_id}><p lang="en">{claim.claim_text}</p><small>引用 {claim.supporting_evidence_item_ids.join(" · ") || "未列出"}</small></article>)}</div></section>
      <div className="flow-delivery-section"><div className="flow-delivery-title"><b>质量与记忆</b></div><div className="flow-quality-row"><span><Check size={14} />任务质量 {delivery.quality_passed === true ? "通过" : delivery.quality_passed === false ? "未通过" : "未记录"}</span><span><ShieldCheck size={14} />业务质量 {delivery.business_quality_passed === true ? "通过" : delivery.business_quality_passed === false ? "未通过" : "未记录"}</span></div>{consumed.map((item) => <button className="flow-delivery-memory" key={item.id} onClick={() => inspect(item.id)}><Database size={16} /><span>消费 {item.source} 的记忆 <small>{item.consumer} · 查看读取回执</small></span><ArrowRight size={15} /></button>)}{model.committedMemory && <button className="flow-delivery-memory" onClick={() => inspect(model.committedMemory!.id)}><Database size={16} /><span>写入 {task.task_id} 的新记忆 <small>已验证产物 · 供后续任务检索</small></span><ArrowRight size={15} /></button>}</div>
      <details className="flow-delivery-provenance"><summary>查看来源记录 <ChevronDown size={13} /></summary><small>结果：{sourcePath(delivery.rows_source_ref)}</small><small>报告：{sourcePath(delivery.report_source_ref)}</small><small>质量：{sourcePath(delivery.quality_source_ref)}</small></details>
    </>}
    {model.artifact && <button className="flow-delivery-object" onClick={() => inspect(model.artifact!.id)}><Layers3 size={16} />查看最后验证产物<ArrowRight size={15} /></button>}
  </div></aside>;
}

export function ObservatoryPage() {
  const [params, setParams] = useSearchParams();
  const taskId = params.get("task") ?? "F01";
  const sourceId = params.get("source");
  const [campaign, setCampaign] = useState<ObservatoryCampaign | null>(null);
  const [task, setTask] = useState<ObservatoryTask | null>(null);
  const [error, setError] = useState("");
  const [playing, setPlaying] = useState(false);
  const [index, setIndex] = useState(0);
  const [progress, setProgress] = useState(0);
  const progressRef = useRef(0);
  const [speed, setSpeed] = useState(1);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [nodesOpen, setNodesOpen] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);
  const pendingStart = useRef<string | null>(null);
  const pageRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLDivElement>(null);
  const model = useMemo(() => task ? buildFlow(task) : null, [task]);
  const beat = model?.beats[index];
  useEffect(() => { studioApi.observatoryCampaign().then(setCampaign).catch((reason: Error) => setError(reason.message)); }, []);
  useEffect(() => {
    let active = true;
    setTask(null); setError(""); setPlaying(false); setIndex(0); setProgress(0); progressRef.current = 0; setSelectedId(null);
    const request = sourceId ? studioApi.observatoryTaskFromSource(sourceId, taskId) : studioApi.observatoryTask(taskId);
    request.then((next) => { if (active) { const count = buildFlow(next).beats.length; setTask(next); const requested = Number(params.get("node") ?? 0); setIndex(Number.isFinite(requested) ? Math.min(count - 1, Math.max(0, Math.floor(requested))) : 0); } }).catch((reason: Error) => { if (active) setError(reason.message); });
    return () => { active = false; };
  }, [taskId, sourceId]);
  useEffect(() => {
    if (task?.task_id === taskId && model && pendingStart.current === taskId) {
      pendingStart.current = null;
      setPlaying(true);
    }
  }, [task, taskId, model]);
  useEffect(() => {
    if (!playing || !model) return;
    let frame: number;
    let last = performance.now();
    const tick = (now: number) => {
      progressRef.current = Math.min(1, progressRef.current + (now - last) * speed / 4400);
      last = now; setProgress(progressRef.current);
      if (progressRef.current >= 1) {
        if (index >= model.beats.length - 1) setPlaying(false);
        else { progressRef.current = 0; setProgress(0); setIndex(index + 1); }
        return;
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing, model, index, speed]);
  useEffect(() => { const update = () => setFullscreen(Boolean(document.fullscreenElement)); document.addEventListener("fullscreenchange", update); return () => document.removeEventListener("fullscreenchange", update); }, []);
  useEffect(() => { setSelectedId(null); }, [index]);
  useEffect(() => {
    if (!model || window.innerWidth > 760) return;
    const frame = requestAnimationFrame(() => {
      const canvas = canvasRef.current;
      const packet = canvas?.querySelector<SVGGElement>(".flow-line.is-active .flow-packet");
      if (!canvas || !packet) return;
      const canvasBox = canvas.getBoundingClientRect();
      const packetBox = packet.getBoundingClientRect();
      canvas.scrollLeft += packetBox.left + packetBox.width / 2 - canvasBox.left - canvasBox.width / 2;
    });
    return () => cancelAnimationFrame(frame);
  }, [model, index, playing, progress]);
  const seek = useCallback((next: number) => { if (!model) return; setPlaying(false); setIndex(Math.max(0, Math.min(model.beats.length - 1, next))); progressRef.current = 0; setProgress(0); }, [model]);
  const inspect = (id: string) => { if (!id) return; setPlaying(false); setSelectedId(id); };
  const selectTask = (next: string) => { pendingStart.current = null; const search = new URLSearchParams(); search.set("task", next); if (sourceId) search.set("source", sourceId); setParams(search, { replace: true }); };
  const startTask = (next: string) => { pendingStart.current = next; const search = new URLSearchParams(); search.set("task", next); if (sourceId) search.set("source", sourceId); setParams(search, { replace: true }); };
  const togglePlay = () => { setSelectedId(null); if (!playing && model && index === model.beats.length - 1 && progressRef.current >= 1) { setIndex(0); progressRef.current = 0; setProgress(0); } setPlaying(!playing); };
  const toggleFullscreen = async () => { if (document.fullscreenElement) await document.exitFullscreen(); else await pageRef.current?.requestFullscreen(); };
  const selected = model?.objects.find((object) => object.id === selectedId) ?? null;
  const currentObject = model && beat ? model.objects.find((object) => object.id === beat.objectId) ?? null : null;
  const visibleObject = selected ?? currentObject;
  const completed = Boolean(model && index === model.beats.length - 1 && progress >= 1);
  if (error) return <div className="page-state"><strong>链路载入失败</strong><p>{error}</p><Link to="/observatory">返回观察台</Link></div>;
  if (!campaign || !task || !model || !beat) return <div className="page-state"><span className="loading-ring" /><p>正在载入运行链路</p></div>;
  return <div className="flow-observatory" ref={pageRef}>
    <header className="flow-header"><Link className="flow-brand" to="/observatory"><Activity size={25} /><strong>StateBus</strong><span>协作运行观察台</span></Link><div className="flow-run"><History size={14} /><span>{sourceId ? "实验来源" : campaign.collection_date} · {task.variant} / {task.family}</span></div><nav><Link to="/evidence"><BarChart3 size={16} /><span>实验与证据</span></Link><Link to="/live" title="真实任务入口"><Terminal size={17} /><span>实时任务</span></Link><button className="flow-icon-button" onClick={() => void toggleFullscreen()} title={fullscreen ? "退出全屏" : "全屏录制"} aria-label={fullscreen ? "退出全屏" : "全屏录制"}>{fullscreen ? <Minimize2 size={18} /> : <Maximize2 size={18} />}</button></nav></header>
    <div className="flow-taskbar"><div className="flow-chapters">{CHAPTERS.map((chapter) => <button key={chapter.id} className={taskId === chapter.id ? "is-selected" : ""} onClick={() => selectTask(chapter.id)}><span>{chapter.id}</span>{chapter.name}{taskId === chapter.id && <i />}</button>)}</div><label className="flow-round-select"><span>全部轮次</span><select aria-label="选择运行轮次" value={taskId} onChange={(event) => selectTask(event.target.value)}>{campaign.tasks.map((item) => <option key={item.task_id} value={item.task_id}>{item.task_id} · 第 {item.round} 轮</option>)}</select><ChevronDown size={14} /></label><span className="flow-campaign-status"><Check size={15} />{campaign.tasks.filter((item) => item.status === "success").length}/{campaign.tasks.length} 轮完成</span><code>{task.run_id}</code></div>
    <div className="flow-main-row"><main className="flow-workspace"><div className="flow-canvas-top"><div className="flow-context"><b>{task.task_id}</b><span>{taskId === "F01" ? "首次协作：建立状态与记忆" : taskId === "F02" ? "连续任务：历史产物改变执行路径" : taskId === "F12" ? "跨角色协作：同一记忆，两次消费" : `连续任务 · 第 ${task.round} 轮`}</span></div><PlaybackControls model={model} index={index} speed={speed} nodesOpen={nodesOpen} seek={seek} setSpeed={setSpeed} setNodesOpen={setNodesOpen} /><div className="flow-key"><span><i style={{ background: TONES.protocol }} />结构化交接</span><span><i style={{ background: TONES.state }} />状态与 Ref</span><span><i style={{ background: TONES.memory }} />记忆与复用</span></div></div><div className="flow-canvas-scroll" ref={canvasRef}><FlowCanvas task={task} model={model} index={index} playing={playing} progress={Math.min(1, progress * 1.45)} inspect={inspect} /></div></main><div className="flow-right-column"><TaskPrompt task={task} available={campaign.task_ids} playing={playing} completed={completed} togglePlay={togglePlay} startTask={startTask} />{completed && !selectedId ? <Delivery task={task} model={model} inspect={inspect} /> : <Inspector task={task} model={model} selected={visibleObject} beat={beat} inspect={inspect} close={() => setSelectedId(null)} />}{completed && selectedId && <button className="flow-back-delivery" onClick={() => setSelectedId(null)}><ArrowRight size={15} />返回本轮输出</button>}<footer className="flow-player"><div className="flow-current" data-tone={beat.tone}><span className="flow-current-number">{String(index + 1).padStart(2, "0")}<small>/{String(model.beats.length).padStart(2, "0")}</small></span><div className="flow-current-heading"><b>{beat.title}</b><span>{beat.from}<ArrowRight size={14} />{beat.to}<code>{beat.content}</code></span></div><button className="flow-node-evidence" onClick={() => inspect(beat.objectId)}><ShieldCheck size={15} />{beat.evidence.length} 条证据<ArrowRight size={14} /></button></div><div className="flow-description">{beat.description}</div></footer></div></div>
    {nodesOpen && <div className="flow-node-menu"><header><b>链路节点</b><button className="flow-icon-button" title="关闭节点目录" onClick={() => setNodesOpen(false)}><X size={18} /></button></header>{model.beats.map((item, i) => <button key={item.id} className={i === index ? "is-selected" : ""} onClick={() => { seek(i); setNodesOpen(false); }}><small>{String(i + 1).padStart(2, "0")}</small><span>{item.title}</span><code>{item.content}</code></button>)}</div>}
  </div>;
}

import { ArrowRight, CheckCircle2, ExternalLink, FileCheck2, History, Layers3, Link2, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { studioApi } from "../api";
import type { ObservatoryEvidence } from "../types";

function number(value: string | number | undefined) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function delta(baseline: number, statebus: number) {
  if (!baseline) return "未测量";
  return `${((statebus - baseline) / baseline * 100).toFixed(2)}%`;
}

export function MainlineEvidencePage() {
  const [payload, setPayload] = useState<ObservatoryEvidence | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { studioApi.evidenceMainline().then(setPayload).catch((reason: Error) => setError(reason.message)); }, []);
  const rows = payload?.tasks ?? [];
  const sb = useMemo(() => rows.filter((row) => row.variant === "SB-FULL"), [rows]);
  const text = useMemo(() => rows.filter((row) => row.variant === "P-TEXT"), [rows]);
  const paired = (key: string) => ({ baseline: text.reduce((sum, row) => sum + number(row[key]), 0), statebus: sb.reduce((sum, row) => sum + number(row[key]), 0) });
  if (error) return <div className="page-state"><strong>证据批次载入失败</strong><p>{error}</p></div>;
  if (!payload) return <div className="page-state"><span className="loading-ring" /><p>正在载入 2026-09-27 主链证据</p></div>;
  const quality = sb.filter((row) => row.business_quality === "True").length;
  const tokens = paired("provider_total_tokens");
  const requests = paired("provider_requests");
  const elapsed = paired("e2e_ms");
  return <div className="mainline-evidence page">
    <header className="mainline-evidence__heading"><div><span className="eyebrow"><History size={14} /> EVIDENCE COLLECTION</span><h1>2026-09-27 主链 · 24 对任务</h1><p>SB-FULL / P-TEXT 的同批次配对结果，来源固定为 Contest39 归档清单。</p></div><div className="mainline-evidence__actions"><Link className="secondary-button" to="/observatory?task=F01&view=runtime"><Layers3 size={16} />打开观察台</Link><Link className="secondary-button" to="/evidence/archive/2026-07-26"><History size={16} />旧快照归档</Link></div></header>
    <div className="mainline-evidence__meta"><span><CheckCircle2 size={15} />质量 {quality}/{sb.length}</span><span><FileCheck2 size={15} />collection {payload.collection}</span><span><ShieldCheck size={15} />原始 runs 不作为页面运行前提</span></div>
    <section className="mainline-evidence__hero"><div><span className="eyebrow">PRODUCT-LEVEL OBSERVATION</span><h2>同批次产品级观测差异</h2><p>provider tokens 是模型服务用量，不是 Agent 间通信 tokens。没有采集的 `wire_bytes`、`typed_bytes` 和反事实 avoided tokens 保持“未测量”。</p></div><div className="mainline-evidence__metric-grid"><article><span>Provider tokens</span><strong>{delta(tokens.baseline, tokens.statebus)}</strong><small>{tokens.statebus.toLocaleString()} SB-FULL · {tokens.baseline.toLocaleString()} P-TEXT</small></article><article><span>Provider requests</span><strong>{delta(requests.baseline, requests.statebus)}</strong><small>{requests.statebus} SB-FULL · {requests.baseline} P-TEXT</small></article><article><span>任务总耗时</span><strong>{delta(elapsed.baseline, elapsed.statebus)}</strong><small>{(elapsed.statebus / 1000).toFixed(1)} s SB-FULL · {(elapsed.baseline / 1000).toFixed(1)} s P-TEXT</small></article></div></section>
    <section className="mainline-evidence__section"><header><div><span className="eyebrow">MATCHED TASKS</span><h2>按任务族查看来源</h2></div><span className="mainline-evidence__note">{sb.length} SB-FULL + {text.length} P-TEXT</span></header><div className="mainline-evidence__table-wrap"><table><thead><tr><th>Task</th><th>Family</th><th>SB-FULL</th><th>P-TEXT</th><th>SB-FULL tokens</th><th>来源</th></tr></thead><tbody>{sb.map((row) => { const baseline = text.find((item) => item.task_id === row.task_id && item.family === row.family); return <tr key={`${row.variant}-${row.task_id}`}><td><strong>{row.task_id}</strong></td><td>{row.family}</td><td><span className="mainline-status"><CheckCircle2 size={13} />{row.business_quality === "True" ? "passed" : "failed"}</span></td><td><span className="mainline-status mainline-status--muted"><CheckCircle2 size={13} />{baseline?.business_quality === "True" ? "passed" : "failed"}</span></td><td>{number(row.provider_total_tokens).toLocaleString()}</td><td><Link to={`/observatory?task=${row.task_id}&view=runtime`} title={`打开 ${row.task_id}`}><Link2 size={14} />finance/slots/{row.task_id}</Link></td></tr>; })}</tbody></table></div></section>
    <section className="mainline-evidence__mechanisms"><article><span className="eyebrow">MECHANISM OBSERVATION</span><h3>State / Memory 证据</h3><p>主链观察到 State publish / transfer / consume / release，以及 Memory query、validated replay 和跨 Agent consume receipt。</p><Link to="/observatory?task=F12&view=memory">查看 F12 Memory lineage <ArrowRight size={14} /></Link></article><article><span className="eyebrow">SPECIALIZED REPORTS</span><h3>专项入口</h3><p>APC、KV、Logit、CodeAct 与模型辅助报告保持独立，不与本批次主链数字混图。</p><a href="/tests/evidence/mechanisms/" target="_blank" rel="noreferrer">打开专项证据 <ExternalLink size={14} /></a></article></section>
  </div>;
}


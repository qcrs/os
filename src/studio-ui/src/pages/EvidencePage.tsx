import type { EChartsOption } from "echarts";
import {
  ArrowRight,
  Boxes,
  CheckCircle2,
  Clock3,
  Database,
  FileCheck2,
  Fingerprint,
  Layers3,
  Radio,
  ShieldCheck,
  Sparkles,
  TableProperties,
  TerminalSquare,
  Waypoints,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { studioApi } from "../api";
import { DatasetDrawer } from "../components/DatasetDrawer";
import { EChart } from "../components/EChart";
import { MetricCard } from "../components/MetricCard";
import { formatBytes, formatNumber, shortHash } from "../format";
import type { Catalog, EvidenceSection, EvidenceSnapshot, HeadlineMetric } from "../types";

const COLORS = {
  baseline: "#929aa3",
  statebus: "#087f75",
  statebusLight: "#52b6ab",
  ink: "#17212b",
  muted: "#66727e",
  grid: "#e6eaed",
  green: "#25865f",
  amber: "#ad6b16",
};

function metric(snapshot: EvidenceSnapshot, id: string) {
  return snapshot.headline_metrics.find((row) => row.id === id);
}

function metricValue(row: HeadlineMetric, value: number) {
  if (row.unit === "seconds") return `${formatNumber(value, 3)} s`;
  if (row.unit === "bytes") return `${formatNumber(value)} B`;
  return formatNumber(value);
}

function ComparisonMetric({ row, label, icon: Icon }: { row: HeadlineMetric; label: string; icon: typeof Layers3 }) {
  const statebusWidth = Math.max(8, Math.min(100, (row.statebus / row.baseline) * 100));
  return (
    <article className="comparison-metric">
      <div className="comparison-metric__heading">
        <span><Icon size={17} />{label}</span>
        <strong>{row.delta_pct.toFixed(2)}%</strong>
      </div>
      <div className="comparison-metric__bars">
        <div><span>纯文本基线</span><i><b style={{ width: "100%" }} /></i><strong>{metricValue(row, row.baseline)}</strong></div>
        <div className="is-statebus"><span>StateBus</span><i><b style={{ width: `${statebusWidth}%` }} /></i><strong>{metricValue(row, row.statebus)}</strong></div>
      </div>
      <div className="comparison-metric__delta">
        <span>相同任务条件</span><ArrowRight size={13} /><strong>减少 {Math.abs(row.delta_pct).toFixed(2)}%</strong>
      </div>
    </article>
  );
}

function coverageOption(snapshot: EvidenceSnapshot): EChartsOption {
  return {
    animationDuration: 600,
    grid: { left: 126, right: 34, top: 14, bottom: 28 },
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    xAxis: {
      type: "value",
      axisLabel: { color: COLORS.muted },
      splitLine: { lineStyle: { color: COLORS.grid } },
    },
    yAxis: {
      type: "category",
      data: snapshot.task_scope.map((row) => row.label),
      axisTick: { show: false },
      axisLine: { show: false },
      axisLabel: { color: COLORS.ink, fontSize: 11 },
    },
    series: [{
      type: "bar",
      data: snapshot.task_scope.map((row, index) => ({
        value: row.count,
        itemStyle: { color: index === 0 ? COLORS.statebus : index === 3 ? "#3d6f91" : COLORS.statebusLight },
      })),
      barWidth: 18,
      label: { show: true, position: "right", color: COLORS.ink, fontWeight: 700 },
      itemStyle: { borderRadius: [0, 2, 2, 0] },
    }],
  };
}

function CommunicationEvidence({ snapshot }: { snapshot: EvidenceSnapshot }) {
  const data = snapshot.structured_control;
  const option: EChartsOption = {
    color: [COLORS.baseline, COLORS.statebus],
    grid: { left: 112, right: 24, top: 48, bottom: 36 },
    legend: { top: 4, right: 0, data: ["纯文本", "结构化"], textStyle: { color: COLORS.muted } },
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    xAxis: {
      type: "value",
      axisLabel: { color: COLORS.muted },
      splitLine: { lineStyle: { color: COLORS.grid } },
    },
    yAxis: {
      type: "category",
      data: ["控制面字节", "链路总字节"],
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: COLORS.ink },
    },
    series: [
      {
        name: "纯文本",
        type: "bar",
        barWidth: 14,
        data: [data.control_bytes_baseline, data.wire_bytes_baseline],
        itemStyle: { borderRadius: [0, 2, 2, 0] },
      },
      {
        name: "结构化",
        type: "bar",
        barWidth: 14,
        data: [data.control_bytes_structured, data.wire_bytes_structured],
        itemStyle: { borderRadius: [0, 2, 2, 0] },
        label: { show: true, position: "right", color: COLORS.statebus, fontWeight: 700 },
      },
    ],
  };
  return (
    <div className="evidence-detail-grid">
      <div className="detail-chart">
        <EChart option={option} ariaLabel="纯文本和结构化通信字节对比" />
      </div>
      <div className="evidence-facts">
        <div className="fact-row"><span>消息次数</span><strong>{data.messages_baseline} = {data.messages_structured}</strong></div>
        <div className="fact-row"><span>控制面字节</span><strong>{data.control_bytes_delta_pct.toFixed(2)}%</strong></div>
        <div className="fact-row"><span>链路总字节</span><strong>{data.wire_bytes_delta_pct.toFixed(2)}%</strong></div>
        <div className="fact-row"><span>同任务质量</span><strong>{data.quality_structured}/{data.case_count}</strong></div>
        <p className="evidence-note">消息数量保持一致，收益来自控制帧收敛和重证据引用化。</p>
      </div>
    </div>
  );
}

function StateEvidence({ snapshot }: { snapshot: EvidenceSnapshot }) {
  const data = snapshot.semantic_state;
  const steps = [
    { label: "生成", value: `${data.physical_state_count} 个 StateRef`, icon: Boxes },
    { label: "跨进程消费", value: `${data.cross_pid_receipts}/${data.physical_state_count}`, icon: Waypoints },
    { label: "改变选择", value: `${data.changed_decisions}/${data.physical_state_count}`, icon: Sparkles },
    { label: "释放", value: formatBytes(data.released_bytes), icon: CheckCircle2 },
  ];
  return (
    <div className="state-proof">
      <div className="state-flow">
        {steps.map((step, index) => {
          const Icon = step.icon;
          return (
            <div className="state-flow__step" key={step.label}>
              <div className="state-flow__icon"><Icon size={20} /></div>
              <span>{step.label}</span>
              <strong>{step.value}</strong>
              {index < steps.length - 1 && <div className="state-flow__connector" />}
            </div>
          );
        })}
      </div>
      <div className="proof-ledger">
        <div><span>留出集质量</span><strong>{data.holdout_passed}/{data.holdout_total}</strong></div>
        <div><span>状态任务</span><strong>{data.semantic_task_count}</strong></div>
        <div><span>影响选择次数</span><strong>{data.selected_occurrences}</strong></div>
        <div><span>发布 / 释放</span><strong>{formatBytes(data.published_bytes)} / {formatBytes(data.released_bytes)}</strong></div>
      </div>
    </div>
  );
}

function MemoryEvidence({ snapshot }: { snapshot: EvidenceSnapshot }) {
  const data = snapshot.memory;
  const option: EChartsOption = {
    color: ["#4d8f8a", "#38958b", "#21877e", "#147a72", "#0b675f"],
    tooltip: { trigger: "item", formatter: "{b}: {c}" },
    series: [{
      type: "funnel",
      left: "5%",
      top: 8,
      bottom: 8,
      width: "90%",
      min: 0,
      max: data.queries,
      minSize: "26%",
      maxSize: "100%",
      sort: "descending",
      gap: 4,
      label: { show: true, position: "inside", color: "#ffffff", fontWeight: 700, formatter: "{b}  {c}" },
      labelLine: { show: false },
      itemStyle: { borderColor: "#ffffff", borderWidth: 1 },
      data: [
        { name: "查询", value: data.queries },
        { name: "有候选", value: data.queries_with_candidates },
        { name: "兼容", value: data.compatible_queries },
        { name: "实际消费", value: data.actual_use_queries },
        { name: "跳过步骤", value: data.skipped_step_queries },
      ],
    }],
  };
  return (
    <div className="evidence-detail-grid">
      <div className="detail-chart detail-chart--funnel">
        <EChart option={option} ariaLabel="共享记忆从查询到跳步的漏斗" />
      </div>
      <div className="evidence-facts">
        <div className="fact-row"><span>实际使用率</span><strong>{data.actual_use_rate_pct.toFixed(0)}%</strong></div>
        <div className="fact-row"><span>不兼容候选拒绝</span><strong>{data.rejected_candidates}/{data.candidate_count}</strong></div>
        <div className="fact-row"><span>行为效果</span><strong>{data.effect_queries}/{data.queries}</strong></div>
        <div className="fact-row"><span>机制真实性测试</span><strong>{data.truth_suite_passed}/{data.truth_suite_total}</strong></div>
        <p className="evidence-note">兼容门先拒绝不安全复用，再将通过验证的记忆提升为可消费状态。</p>
      </div>
    </div>
  );
}

function CapabilityEvidence({ snapshot }: { snapshot: EvidenceSnapshot }) {
  const data = snapshot.capability;
  const option: EChartsOption = {
    grid: { left: 142, right: 34, top: 12, bottom: 24 },
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    xAxis: { type: "value", max: 8, splitLine: { lineStyle: { color: COLORS.grid } }, axisLabel: { color: COLORS.muted } },
    yAxis: {
      type: "category",
      data: data.families.map((row) => row.label),
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: COLORS.ink, fontSize: 11 },
    },
    series: [{
      type: "bar",
      data: data.families.map((row) => row.cases),
      barWidth: 17,
      itemStyle: { color: COLORS.statebus, borderRadius: [0, 2, 2, 0] },
      label: { show: true, position: "right", color: COLORS.ink, fontWeight: 700 },
    }],
  };
  return (
    <div className="evidence-detail-grid">
      <div className="detail-chart"><EChart option={option} ariaLabel="五类任务能力覆盖" /></div>
      <div className="evidence-facts">
        <div className="fact-row"><span>正式任务通过</span><strong>{data.passed}/{data.total}</strong></div>
        <div className="fact-row"><span>受限 Python 执行</span><strong>{data.python_codeact}</strong></div>
        <div className="fact-row"><span>结构化 DSL 执行</span><strong>{data.dsl}</strong></div>
        <div className="fact-row"><span>降级执行</span><strong>{data.fallback}</strong></div>
        <p className="evidence-note">25 个任务均由 Qwen3-32B 驱动；Executor 生成 18 个受限 Python 程序和 7 个结构化 DSL 程序，全部验证通过，未触发模型、Runtime 或沙箱降级路径。</p>
      </div>
    </div>
  );
}

function EfficiencyBreakdown({ snapshot }: { snapshot: EvidenceSnapshot }) {
  const data = snapshot.full_stack;
  const rows = [
    { label: "原始证据字节", baseline: data.raw_evidence_bytes.baseline, statebus: data.raw_evidence_bytes.statebus, delta: data.raw_evidence_bytes.delta_pct, unit: "bytes" },
    { label: "Prompt 可见字节", baseline: data.prompt_visible_bytes.baseline, statebus: data.prompt_visible_bytes.statebus, delta: data.prompt_visible_bytes.delta_pct, unit: "bytes" },
    { label: "控制面字节", baseline: data.control_bytes.baseline, statebus: data.control_bytes.statebus, delta: data.control_bytes.delta_pct, unit: "bytes" },
    { label: "Prompt Token", baseline: data.prompt_tokens.baseline, statebus: data.prompt_tokens.statebus, delta: data.prompt_tokens.delta_pct, unit: "tokens" },
    { label: "总 Token", baseline: data.total_tokens.baseline, statebus: data.total_tokens.statebus, delta: data.total_tokens.delta_pct, unit: "tokens" },
    { label: "10 任务总耗时", baseline: data.task_time_seconds.baseline, statebus: data.task_time_seconds.statebus, delta: data.task_time_seconds.delta_pct, unit: "seconds" },
  ] as const;
  const operating = data.operating_highlight;
  const display = (value: number, unit: string) => {
    if (unit === "seconds") return `${value.toFixed(3)} s`;
    if (unit === "bytes") return formatBytes(value);
    return formatNumber(value);
  };

  return (
    <section className="efficiency-breakdown-section">
      <div className="section-heading">
        <div><span className="eyebrow">效率拆解</span><h2>从证据输入到任务完成</h2></div>
        <span className="section-caption">同一组 10 个任务 · L0 纯文本 / L3 StateBus</span>
      </div>
      <div className="efficiency-breakdown-grid">
        <div className="efficiency-table" role="table" aria-label="完整效率指标对比">
          <div className="efficiency-table__header" role="row">
            <span>指标</span><span>纯文本 L0</span><span>StateBus L3</span><span>变化</span>
          </div>
          {rows.map((row) => (
            <div className="efficiency-table__row" role="row" key={row.label}>
              <strong>{row.label}</strong>
              <span>{display(row.baseline, row.unit)}</span>
              <span>{display(row.statebus, row.unit)}</span>
              <b>{row.delta.toFixed(2)}%</b>
            </div>
          ))}
        </div>
        <aside className="operating-highlight">
          <span>长证据任务表现</span>
          <strong>{operating.delta_pct.toFixed(2)}%</strong>
          <p>Operating metrics 共 {operating.case_count} 个任务，全部完成且 {operating.faster_cases}/{operating.case_count} 更快。</p>
          <dl>
            <div><dt>纯文本总耗时</dt><dd>{operating.baseline_seconds.toFixed(3)} s</dd></div>
            <div><dt>StateBus 总耗时</dt><dd>{operating.statebus_seconds.toFixed(3)} s</dd></div>
            <div><dt>质量门</dt><dd>同任务通过</dd></div>
          </dl>
        </aside>
      </div>
    </section>
  );
}

export function EvidencePage() {
  const [snapshot, setSnapshot] = useState<EvidenceSnapshot | null>(null);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [activeSection, setActiveSection] = useState<EvidenceSection>("communication");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [selectedDataset, setSelectedDataset] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    Promise.all([studioApi.evidence(), studioApi.catalog()])
      .then(([evidence, nextCatalog]) => {
        if (!active) return;
        setSnapshot(evidence);
        setCatalog(nextCatalog);
        setSelectedDataset(nextCatalog.datasets[0]?.dataset_id ?? "");
      })
      .catch((reason: Error) => active && setError(reason.message));
    return () => { active = false; };
  }, []);

  const coverage = useMemo(() => snapshot ? coverageOption(snapshot) : {}, [snapshot]);

  if (error) {
    return <div className="page-state page-state--error"><ShieldCheck size={24} /><h1>证据快照不可用</h1><p>{error}</p></div>;
  }
  if (!snapshot || !catalog) {
    return <div className="page-state"><span className="loading-ring" /><p>正在载入固定证据快照</p></div>;
  }

  const tokens = metric(snapshot, "total_tokens")!;
  const wire = metric(snapshot, "wire_bytes")!;
  const time = metric(snapshot, "task_time")!;
  const qualityText = `${snapshot.quality.formal_passed}/${snapshot.quality.formal_total}`;
  const sectionSummaries = [
    {
      id: "communication" as const,
      label: "结构化通信",
      value: `${snapshot.structured_control.control_bytes_delta_pct.toFixed(2)}%`,
      detail: `${snapshot.structured_control.messages_baseline} = ${snapshot.structured_control.messages_structured} 条消息`,
      icon: Radio,
    },
    {
      id: "state" as const,
      label: "非文本状态",
      value: `${snapshot.semantic_state.cross_pid_receipts}/${snapshot.semantic_state.physical_state_count}`,
      detail: "跨进程消费并改变选择",
      icon: Boxes,
    },
    {
      id: "memory" as const,
      label: "共享记忆",
      value: `${snapshot.memory.actual_use_rate_pct.toFixed(0)}%`,
      detail: `${snapshot.memory.skipped_step_queries} 次跳过步骤`,
      icon: Database,
    },
    {
      id: "capability" as const,
      label: "能力覆盖",
      value: `${snapshot.capability.passed}/${snapshot.capability.total}`,
      detail: `五类任务 · ${snapshot.capability.fallback} fallback`,
      icon: TerminalSquare,
    },
  ];

  return (
    <div className="page evidence-page">
      <section className="page-heading">
        <div>
          <span className="eyebrow">EVIDENCE CENTER / 固定基线</span>
          <h1>实验与证据</h1>
          <p>固定基线、机制证据与任务覆盖采用同一份结构化快照。</p>
        </div>
        <div className="page-heading__actions">
          <button className="secondary-button" onClick={() => setDrawerOpen(true)}><TableProperties size={17} />任务与数据</button>
        </div>
      </section>

      <div className="snapshot-strip">
        <span><Fingerprint size={15} />固定证据快照 {snapshot.measured_at}</span>
        <span>代码基线 <code>{shortHash(snapshot.git_sha, 8)}</code></span>
        <span className="snapshot-strip__pass"><CheckCircle2 size={15} />综合验证记录 {qualityText} 通过</span>
        <span>发布 {snapshot.published_at}</span>
      </div>

      <section className="metric-grid" aria-label="核心实验指标">
        <MetricCard label="同任务质量" value="10/10" detail="L0 10/10 · L3 10/10" icon={ShieldCheck} tone="green" />
        <MetricCard label="总 Token" value={`${tokens.delta_pct.toFixed(2)}%`} detail={`${formatNumber(tokens.baseline)} -> ${formatNumber(tokens.statebus)}`} icon={Layers3} tone="teal" />
        <MetricCard label="链路总字节" value={`${wire.delta_pct.toFixed(2)}%`} detail={`${formatNumber(wire.baseline)} -> ${formatNumber(wire.statebus)}`} icon={Radio} tone="blue" />
        <MetricCard label="10 任务总耗时" value={`${time.delta_pct.toFixed(2)}%`} detail={`${time.baseline.toFixed(3)}s -> ${time.statebus.toFixed(3)}s`} icon={Clock3} tone="neutral" />
      </section>

      <section className="primary-evidence-band">
        <div className="chart-block">
          <div className="section-heading">
            <div><span className="eyebrow">同任务对照</span><h2>纯文本协作 vs StateBus</h2></div>
            <span className="status-chip status-chip--verified"><FileCheck2 size={14} />L0 / L3 均为 10/10</span>
          </div>
          <div className="comparison-metric-grid">
            <ComparisonMetric row={tokens} label="总 Token" icon={Layers3} />
            <ComparisonMetric row={wire} label="链路总字节" icon={Radio} />
            <ComparisonMetric row={time} label="10 任务总耗时" icon={Clock3} />
          </div>
        </div>

        <div className="coverage-block">
          <div className="section-heading">
            <div><span className="eyebrow">实验覆盖范围</span><h2>验证记录构成</h2></div>
            <strong className="coverage-total">95 项记录</strong>
          </div>
          <EChart option={coverage} className="coverage-chart" ariaLabel="实验任务构成" />
          <div className="coverage-ledger">
            {snapshot.task_scope.map((row) => <div key={row.id}><span>{row.label}</span><small>{row.detail}</small></div>)}
          </div>
        </div>
      </section>

      <EfficiencyBreakdown snapshot={snapshot} />

      <section className="analysis-section">
            <div className="section-heading">
              <div><span className="eyebrow">机制证据</span><h2>三项机制与能力闭环</h2></div>
              <span className="section-caption">指标、回执与质量门联合验证</span>
            </div>
            <div className="evidence-proof-tabs" role="tablist" aria-label="机制证据">
              {sectionSummaries.map((section) => {
                const Icon = section.icon;
                return (
                  <button role="tab" aria-selected={activeSection === section.id} className={activeSection === section.id ? "is-active" : ""} onClick={() => setActiveSection(section.id)} key={section.id}>
                    <span><Icon size={17} />{section.label}</span>
                    <strong>{section.value}</strong>
                    <small>{section.detail}</small>
                  </button>
                );
              })}
            </div>
            <div className="evidence-detail-panel">
              {activeSection === "communication" && <CommunicationEvidence snapshot={snapshot} />}
              {activeSection === "state" && <StateEvidence snapshot={snapshot} />}
              {activeSection === "memory" && <MemoryEvidence snapshot={snapshot} />}
              {activeSection === "capability" && <CapabilityEvidence snapshot={snapshot} />}
            </div>
      </section>

      <DatasetDrawer
        datasets={catalog.datasets}
        selectedId={selectedDataset}
        open={drawerOpen}
        onSelect={setSelectedDataset}
        onClose={() => setDrawerOpen(false)}
      />
    </div>
  );
}

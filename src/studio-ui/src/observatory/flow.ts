import type { ObservatoryEvent, ObservatoryObject, ObservatoryTask } from "../types";

export type FlowRoute = "plan" | "dispatch" | "publish" | "resolve" | "state-read" | "query" | "verdict" | "retrieve-result" | "memory-executor" | "execute" | "summarize" | "memory-summarizer" | "result" | "commit" | "release";
export type FlowTone = "protocol" | "state" | "memory";
export interface FlowBeat {
  id: string;
  title: string;
  description: string;
  from: string;
  to: string;
  content: string;
  route: FlowRoute;
  tone: FlowTone;
  objectId: string;
  evidence: ObservatoryEvent[];
  // A runtime anchor locates grouped evidence; it is not a cross-source timestamp.
  anchor: ObservatoryEvent;
}
export interface FlowModel {
  beats: FlowBeat[];
  objects: ObservatoryObject[];
  evidenceByObject: Record<string, ObservatoryEvent[]>;
  state?: ObservatoryObject;
  query?: ObservatoryObject;
  sourceMemory?: ObservatoryObject;
  committedMemory?: ObservatoryObject;
  artifact?: ObservatoryObject;
  stateReceipt?: ObservatoryObject;
  memoryReceipts: ObservatoryObject[];
}

export function valueText(value: unknown): string {
  if (value === null || value === undefined || value === "") return "未记录";
  if (typeof value === "boolean") return value ? "是" : "否";
  if (Array.isArray(value)) return value.map(valueText).join(" · ");
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

export function buildFlow(task: ObservatoryTask): FlowModel {
  const runtime = task.events.filter((event) => event.source_ref.path.endsWith("runtime_events.jsonl"))
    .sort((a, b) => (a.source_ref.line ?? 0) - (b.source_ref.line ?? 0));
  const bySourceLine = (a: ObservatoryEvent, b: ObservatoryEvent) => (a.source_ref.line ?? 0) - (b.source_ref.line ?? 0);
  const stateRows = task.events.filter((event) => event.source_ref.path.endsWith("state-events.jsonl")).sort(bySourceLine);
  const memoryRows = task.events.filter((event) => event.source_ref.path.endsWith("memory-events.jsonl")).sort(bySourceLine);
  const handoffs = task.events.filter((event) => event.kind === "handoff.consume").sort(bySourceLine);
  const find = (kind: string, actor?: string) => runtime.find((event) => event.kind === kind && (!actor || event.actor === actor));
  const objects = task.objects.filter((object) => !["MemoryRef", "ExecutionArtifactRef", "CapabilityGrant"].includes(object.object_type));
  const evidenceByObject: FlowModel["evidenceByObject"] = {};
  const register = (object: ObservatoryObject, evidence: ObservatoryEvent[]) => {
    const previous = objects.findIndex((item) => item.id === object.id);
    if (previous >= 0) objects[previous] = object; else objects.push(object);
    evidenceByObject[object.id] = [...(evidenceByObject[object.id] ?? []), ...evidence].filter((event, index, all) => all.findIndex((item) => item.id === event.id) === index);
    return object;
  };
  const beats: FlowBeat[] = [];
  const add = (beat: Omit<FlowBeat, "id">) => beats.push({ ...beat, id: `${task.task_id}:${beats.length}:${beat.route}` });
  const state = objects.find((object) => object.object_type === "SemanticStateRef");
  if (state) evidenceByObject[state.id] = [...runtime.filter((event) => event.object_ids.includes(state.id)), ...stateRows];
  const planEvent = find("runtime.plan.approved");
  if (!planEvent) throw new Error(`${task.task_id} 缺少已批准计划的 Runtime 来源，无法建立回放链路`);
  if (planEvent) {
    const evidence = [planEvent, ...handoffs.filter(event => event.payload.receiver === "planner")];
    const plan = register({ id: String(planEvent.payload.approved_plan_hash), object_type: "ApprovedPlan", label: "已批准计划", summary: "Runtime 验证提案并批准执行计划", fields: planEvent.payload }, evidence);
    add({ title: "计划获准", description: "Planner 接收任务并提出计划，Runtime 检查提案与策略后批准执行。", from: "Planner", to: "Runtime", content: "ApprovedPlan", route: "plan", tone: "protocol", objectId: plan.id, evidence, anchor: planEvent });
  }
  for (const event of runtime.filter((event) => event.kind === "runtime.capability.grant")) {
    register({ id: String(event.payload.grant_hash), object_type: "CapabilityGrant", label: "执行授权", summary: `Runtime 授权 ${valueText(event.payload.capability_id)}`, fields: event.payload }, [event]);
  }
  for (const event of handoffs) {
    register({ id: String(event.payload.message_id), object_type: "TypedHandoff", label: "结构化交接", summary: `${valueText(event.payload.sender)} → ${valueText(event.payload.receiver)}`, fields: event.payload }, [event]);
  }
  const retrieveStart = find("runtime.step.running", "retriever");
  const retrieveHandoff = handoffs.find((event) => event.payload.receiver === "retriever");
  if (retrieveStart && retrieveHandoff) {
    add({ title: "检索任务交接", description: "Planner 向 Retriever 交付 typed 对象；Runtime 授予检索能力。此交接记录的载体是进程内 typed object。", from: "Planner", to: "Retriever", content: "TypedHandoff", route: "dispatch", tone: "protocol", objectId: String(retrieveHandoff.payload.message_id), evidence: [retrieveHandoff, retrieveStart, ...runtime.filter((event) => event.kind === "runtime.capability.grant" && event.payload.capability_id === "dsl-retrieve")], anchor: retrieveStart });
  }
  const publish = find("state.publish");
  if (state && publish) add({ title: "数值状态写入", description: `Retriever 生成 ${valueText(state.fields.shape)} 的 ${valueText(state.fields.dtype)} 语义矩阵，${Number(state.fields.size_bytes).toLocaleString()} B 载荷保存在 ${valueText(state.fields.storage_kind)}。`, from: "Retriever", to: "State store", content: "SemanticState", route: "publish", tone: "state", objectId: state.id, evidence: [publish, ...stateRows.filter((event) => event.payload.event === "publish")], anchor: publish });
  const resolve = find("state.resolve");
  if (state && resolve) add({ title: "交付引用，解析状态", description: "交付 SemanticStateRef，State worker 在另一进程按引用定位载荷。数值矩阵仍保存在 State store。", from: "Retriever", to: "State worker", content: "SemanticStateRef", route: "resolve", tone: "state", objectId: state.id, evidence: [resolve, ...stateRows.filter((event) => event.payload.event === "transfer")], anchor: resolve });
  const stateConsume = find("state.consume");
  const stateConsumeRow = stateRows.find((event) => event.payload.event === "consume");
  let stateReceipt: ObservatoryObject | undefined;
  if (stateConsumeRow) {
    const receipt = stateConsumeRow.payload.receipt as Record<string, unknown>;
    stateReceipt = register({ id: `${task.task_id}:semantic-consumer-receipt`, object_type: "StateReceipt", label: "状态读取回执", summary: "消费者读取矩阵并选择证据；本轮行为差异按原始回执记录", fields: receipt }, [stateConsumeRow, ...(stateConsume ? [stateConsume] : [])]);
  }
  if (state && stateConsume) add({ title: "按 Ref 读取并选择证据", description: `State worker 读取数值矩阵、选择证据并留下回执；${stateReceipt?.fields.behavioral_effect === "no_effect" ? "本轮证据选择未改变" : `本轮效果记录为 ${valueText(stateReceipt?.fields.behavioral_effect)}`}。`, from: "State store", to: "State worker", content: "StateReceipt", route: "state-read", tone: "state", objectId: stateReceipt?.id ?? state.id, evidence: [stateConsume, ...(stateConsumeRow ? [stateConsumeRow] : [])], anchor: stateConsume });
  const queryEvent = memoryRows.find((event) => event.payload.event === "query");
  const retrieveComplete = find("runtime.step.completed", "retriever");
  let query: ObservatoryObject | undefined;
  if (queryEvent && retrieveComplete) {
    query = register({ id: String(queryEvent.payload.query_id), object_type: "MemoryQuery/Verdict", label: "记忆查询与兼容判断", summary: `${valueText(queryEvent.payload.candidate_count)} 个候选；候选不代表实际消费`, fields: queryEvent.payload }, [queryEvent]);
    add({ title: "查询共享记忆", description: `检索阶段记录了 ${valueText(query.fields.candidate_count)} 个候选。查询证据归入此阶段，不用跨来源时间戳推断耗时。`, from: "Retriever", to: "Memory store", content: "MemoryQuery", route: "query", tone: "memory", objectId: query.id, evidence: [queryEvent, retrieveComplete], anchor: retrieveComplete });
    add({ title: Number(query.fields.candidate_count) ? "检查复用条件" : "无历史候选，继续计算", description: Number(query.fields.candidate_count) ? "Runtime 根据合同与输入来源检查候选；只有获准且实际消费的记忆才能标为复用。" : "本次查询没有候选；继续生成当前任务的产物，完成后再写入记忆。", from: "Memory store", to: "Runtime", content: "CompatibilityVerdict", route: "verdict", tone: "memory", objectId: query.id, evidence: [queryEvent], anchor: retrieveComplete });
  }
  const executionStart = find("runtime.step.running", "executor");
  const executionHandoff = handoffs.find((event) => event.payload.receiver === "executor");
  if (executionStart && executionHandoff) add({ title: "检索结果交给执行角色", description: "Retriever 向 Executor 交付 typed 对象；Runtime 授予执行能力，随后允许本轮计算或已获准的记忆消费。", from: "Retriever", to: "Executor", content: "TypedHandoff", route: "retrieve-result", tone: "protocol", objectId: String(executionHandoff.payload.message_id), evidence: [executionHandoff, executionStart, ...runtime.filter((event) => event.kind === "runtime.capability.grant" && event.payload.capability_id === "dsl-execute")], anchor: executionStart });
  const memoryReceipts: ObservatoryObject[] = [];
  const consumes = memoryRows.filter((event) => event.payload.event === "consume");
  let sourceMemory: ObservatoryObject | undefined;
  for (const event of consumes) {
    const fields = event.payload;
    const memory = register({ id: String(fields.memory_ref), object_type: "MemoryRef", label: `来源 ${valueText(fields.source_task_id)} 的记忆`, summary: "先前任务的验证产物，由本轮实际消费", fields: { memory_id: fields.memory_ref, source_task_id: fields.source_task_id, source_agent: fields.source_agent, artifact_ref_id: fields.artifact_ref_id, artifact_hash: fields.artifact_hash, verdict: fields.compatibility_verdict } }, [event, ...(queryEvent ? [queryEvent] : [])]);
    sourceMemory ??= memory;
    register({ id: String(fields.artifact_ref_id), object_type: "ExecutionArtifactRef", label: `来源 ${valueText(fields.source_task_id)} 的验证产物`, summary: "从消费记录读取的历史产物身份", fields: { artifact_ref_id: fields.artifact_ref_id, artifact_hash: fields.artifact_hash, artifact_read_bytes: fields.artifact_read_bytes, source_task_id: fields.source_task_id } }, [event]);
    memoryReceipts.push(register({ id: String(fields.consume_receipt), object_type: "Receipt", label: `${valueText(fields.consumer_agent)} 消费回执`, summary: `${valueText(fields.source_task_id)} → ${valueText(fields.consumer_agent)} · ${valueText(fields.replay_class)}`, fields }, [event]));
  }
  const consumeBeat = (role: string, route: FlowRoute) => {
    for (const event of consumes.filter((item) => item.payload.consumer_agent === role)) {
      const anchor = find("runtime.step.running", role);
      if (!anchor) continue;
      const fields = event.payload;
      add({ title: role === "executor" ? "消费记忆，复用验证产物" : "同一记忆，第二个消费者", description: role === "executor" ? `${valueText(fields.source_task_id)} 的验证产物被实际读取并用于 ${valueText(fields.replay_class)}；generation ${Number(fields.skipped_executor_generation) ? "已跳过，当前输入仍重新计算" : "未跳过"}。` : `${valueText(fields.source_task_id)} 的同一条记忆被 Summarizer 实际读取，用于产物辅助核查（${valueText(fields.replay_class)}）。`, from: "Memory store", to: role === "executor" ? "Executor" : "Summarizer", content: "MemoryRef → Receipt", route, tone: "memory", objectId: String(fields.consume_receipt), evidence: [event, anchor], anchor });
    }
  };
  consumeBeat("executor", "memory-executor");
  const execution = find("runtime.step.completed", "executor");
  const commit = find("memory.commit.verified");
  let artifact: ObservatoryObject | undefined;
  let committedMemory: ObservatoryObject | undefined;
  if (commit) {
    const fields = commit.payload;
    artifact = register({ id: String(fields.artifact_ref_id), object_type: "ExecutionArtifactRef", label: `${task.task_id} 本轮验证产物`, summary: "当前任务产物，由本轮 commit 记录确认身份", fields: { artifact_ref_id: fields.artifact_ref_id, artifact_hash: fields.artifact_hash, quality_report_hash: fields.quality_report_hash, source_task_id: task.task_id } }, [commit, ...(execution ? [execution] : [])]);
    committedMemory = register({ id: String(fields.memory_id), object_type: "MemoryRef", label: `${task.task_id} 新写入的记忆`, summary: "本轮验证产物提交成功，供后续任务检索", fields: { ...fields, source_task_id: task.task_id } }, [commit]);
  }
  const repairs = handoffs.filter(event => event.payload.sender === "runtime" && event.payload.receiver === "executor");
  if (execution) add({ title: "执行产物完成", description: (consumes.some((event) => event.payload.consumer_agent === "executor" && Number(event.payload.skipped_executor_generation)) ? "Executor 使用历史验证产物完成当前计算；跳过的是 generation，执行与验证仍然发生。" : "Executor 完成本轮计算，返回当前任务产物。") + (repairs.length ? `本轮还有 ${repairs.length} 条 Runtime → Executor 修复交接，可在来源中核查。` : ""), from: "Executor", to: "Runtime", content: "ExecutionArtifactRef", route: "execute", tone: "protocol", objectId: artifact?.id ?? "", evidence: [execution, ...repairs], anchor: execution });
  const summaryStart = find("runtime.step.running", "summarizer");
  const summaryHandoff = handoffs.find((event) => event.payload.receiver === "summarizer");
  if (summaryStart && summaryHandoff) add({ title: "产物交给总结角色", description: "Executor 向 Summarizer 交付 typed 对象，Runtime 调度总结步骤。", from: "Executor", to: "Summarizer", content: "TypedHandoff", route: "summarize", tone: "protocol", objectId: String(summaryHandoff.payload.message_id), evidence: [summaryHandoff, summaryStart], anchor: summaryStart });
  consumeBeat("summarizer", "memory-summarizer");
  const summaryComplete = find("runtime.step.completed", "summarizer");
  if (summaryComplete) add({ title: "总结完成", description: "Summarizer 完成总结步骤；Runtime 随后确认产物与记忆提交。", from: "Summarizer", to: "Runtime", content: "StepResult", route: "result", tone: "protocol", objectId: artifact?.id ?? "", evidence: [summaryComplete], anchor: summaryComplete });
  if (commit && committedMemory) add({ title: "本轮产物成为新记忆", description: `${task.task_id} 的产物经 Runtime 验证后提交到 Memory store。这是本轮新记忆，与刚才消费的历史记忆分别保存。`, from: "Runtime", to: "Memory store", content: "ArtifactRef → MemoryRef", route: "commit", tone: "memory", objectId: committedMemory.id, evidence: [commit], anchor: commit });
  const release = find("state.release");
  if (release && state) add({ title: "释放本轮状态", description: "Runtime 结束本轮状态生命周期；State store 回收载荷，验证产物与持久记忆继续保留。", from: "Runtime", to: "State store", content: "ReleaseReceipt", route: "release", tone: "state", objectId: state.id, evidence: [release, ...stateRows.filter((event) => event.payload.event === "release")], anchor: release });
  return { beats, objects, evidenceByObject, state, query, sourceMemory, committedMemory, artifact, stateReceipt, memoryReceipts };
}

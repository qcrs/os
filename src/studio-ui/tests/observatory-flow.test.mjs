import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import ts from "typescript";

const source = readFileSync(new URL("../src/observatory/flow.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
}).outputText;
const { buildFlow } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);
const bundle = new URL("../../statebus/studio/data/observatory/contest39-20260927/tasks/", import.meta.url);
const load = (id) => JSON.parse(readFileSync(new URL(`${id}.json`, bundle), "utf8"));
test("all 12 replay tasks include inspectable contracts and structured deliveries", () => {
  for (let round = 1; round <= 12; round++) {
    const id = `F${String(round).padStart(2, "0")}`;
    const task = load(id);
    assert.ok(task.task_contract.instructions);
    assert.equal(task.task_contract.source_ref.path, `finance/slots/${id}/manifest.json`);
    assert.equal(task.delivery.rows_source_ref.path, `finance/slots/${id}/rows.json`);
    assert.equal(task.delivery.report_source_ref.path, `finance/slots/${id}/report.json`);
    assert.equal(task.delivery.rows.length, 4);
    assert.equal(task.delivery.claim_set.claims.length, 4);
    assert.equal(task.delivery.claim_set.status, "ready");
    assert.ok(task.delivery.rows.every(row => Object.keys(task.task_contract.output_schema).every(key => Object.hasOwn(row, key))));
  }
});

test("all 12 runs preserve runtime order and evidence when concatenated logs are reordered", () => {
  for (let round = 1; round <= 12; round++) {
    const task = load(`F${String(round).padStart(2, "0")}`);
    const before = JSON.stringify(task);
    const model = buildFlow(task);
    assert.equal(model.beats[0].route, "plan");
    assert.equal(model.beats.at(-1).route, "release");
    const handoffs = model.beats.filter(beat => ["dispatch", "retrieve-result", "summarize"].includes(beat.route));
    const sourceHandoffs = task.events.filter(event => event.kind === "handoff.consume" && ["planner", "retriever", "executor"].includes(event.payload.sender));
    assert.equal(handoffs.length, sourceHandoffs.length, "only draw handoffs actually recorded in this run");
    assert.deepEqual(handoffs.map(beat => [beat.from.toLowerCase(), beat.to.toLowerCase()]), sourceHandoffs.map(event => [event.payload.sender, event.payload.receiver]));
    for (const handoff of task.events.filter(event => event.kind === "handoff.consume")) {
      assert.ok(model.beats.some(beat => beat.evidence.some(event => event.id === handoff.id)), "typed repair and task-input records remain inspectable");
    }
    for (const [index, beat] of model.beats.entries()) {
      assert.ok(beat.evidence.length, `${task.task_id}: ${beat.route} needs source evidence`);
      assert.ok(beat.anchor.source_ref.path.endsWith("runtime_events.jsonl"));
      if (index) assert.ok(beat.anchor.source_ref.line >= model.beats[index - 1].anchor.source_ref.line);
    }
    assert.equal(JSON.stringify(task), before, "adapter must not change the archived input");
    const reordered = buildFlow({ ...task, events: [...task.events].reverse() });
    assert.deepEqual(reordered.beats, model.beats, "cross-file concatenation must not drive playback");
  }
});

test("F01 shows cross-process Ref resolution, no memory consumption, then a new commit", () => {
  const model = buildFlow(load("F01"));
  assert.equal(model.sourceMemory, undefined);
  assert.equal(model.memoryReceipts.length, 0);
  assert.equal(model.query.fields.candidate_count, 0);
  assert.equal(model.committedMemory.id, "memory:F01:3b4d093b019198a0");
  assert.equal(model.state.fields.storage_kind, "mmap_file");
  assert.equal(model.state.fields.size_bytes, 20480);
  assert.notEqual(model.state.fields.producer_pid, model.state.fields.consumer_pid);
  assert.equal(model.state.fields.wire_bytes, null);
  assert.equal(model.stateReceipt.fields.behavioral_effect, "no_effect");
  assert.equal(model.beats.find(beat => beat.route === "state-read").to, "State worker");
});

test("F02 separates consumed F01 identity and hash from its newly committed F02 artifact", () => {
  const task = load("F02");
  const model = buildFlow(task);
  const consumption = task.events.find(event => event.source_ref.path.endsWith("memory-events.jsonl") && event.payload.event === "consume").payload;
  const commit = task.events.find(event => event.kind === "memory.commit.verified").payload;
  assert.equal(model.sourceMemory.id, "memory:F01:3b4d093b019198a0");
  assert.equal(model.committedMemory.id, "memory:F02:0b14decbb01c9b10");
  assert.notEqual(model.sourceMemory.id, model.committedMemory.id);
  assert.equal(model.sourceMemory.fields.artifact_hash, consumption.artifact_hash);
  assert.equal(model.artifact.fields.artifact_hash, commit.artifact_hash);
  assert.notEqual(model.sourceMemory.fields.artifact_hash, model.artifact.fields.artifact_hash);
  assert.equal(model.query.fields.decisions[0].verdict, "degraded");
  assert.equal(model.query.fields.decisions[0].policy_approved, true);
  assert.equal(model.memoryReceipts[0].fields.artifact_read_bytes, 384);
  assert.equal(model.memoryReceipts[0].fields.skipped_executor_generation, 1);
  assert.equal(model.memoryReceipts[0].fields.input_recomputed, true);
  assert.equal(model.beats.some(beat => beat.route === "retrieve-result"), false, "replay path must not invent a generation handoff");
  assert.ok(model.beats.findIndex(beat => beat.route === "verdict") < model.beats.findIndex(beat => beat.route === "memory-executor"));
});

test("F12 uses one F10 memory with distinct replay and assist receipts", () => {
  const model = buildFlow(load("F12"));
  assert.equal(model.query.fields.candidate_count, 11);
  assert.equal(model.sourceMemory.id, "memory:F10:3b7bf27d5a450bca");
  assert.equal(model.memoryReceipts.length, 2);
  const executor = model.memoryReceipts.find(receipt => receipt.fields.consumer_agent === "executor");
  const summarizer = model.memoryReceipts.find(receipt => receipt.fields.consumer_agent === "summarizer");
  assert.equal(executor.fields.memory_ref, summarizer.fields.memory_ref);
  assert.notEqual(executor.id, summarizer.id);
  assert.notEqual(executor.fields.grant_id, summarizer.fields.grant_id);
  assert.equal(executor.fields.replay_class, "validated_replay");
  assert.equal(executor.fields.skipped_executor_generation, 1);
  assert.equal(summarizer.fields.replay_class, "assist");
  assert.equal(summarizer.fields.skipped_executor_generation, 0);
  assert.equal(model.evidenceByObject[model.sourceMemory.id].filter(event => event.payload.event === "consume").length, 2);
});

test("unusable sources fail explicitly rather than hanging in loading state", () => {
  const task = load("F01");
  assert.throws(() => buildFlow({ ...task, events: [] }), /缺少已批准计划/);
});

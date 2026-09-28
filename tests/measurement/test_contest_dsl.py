from dataclasses import replace
import json

import pytest

from statebus.benchmark.contest_dsl_taskpack import (
    TASKS, bind_inputs, generate_sealed, release_task, tasks_for_family,
)
from statebus.benchmark.contest_dsl_fixtures import offline_program
from statebus.benchmark.contest_dsl_mainline import _r12_memory_witness, _select_r12_memory
from statebus.benchmark.contest_dsl_scorer import score_rows
from statebus.benchmark.contest_dsl_transport import HandoffTransport
from statebus.benchmark.contest_dsl_metrics import aggregate_slots, build_tables, memory_totals
from statebus.runtime.transform_dsl import TransformDslInterpreter, TransformProgramError
from statebus.runtime.capability_recompute import recompute_transform_program


@pytest.mark.parametrize("family", ["finance", "service_ops"])
def test_full_raw_dsl_chain_matches_independent_decimal_scorer(tmp_path, family):
    sealed, public = tmp_path / "sealed", tmp_path / "public"
    generate_sealed(sealed)
    history = {}
    for task in tasks_for_family(family):
        release_task(sealed, public, task.task_id)
        tables = bind_inputs(public, task.task_id, history=history)
        refs = {name: "source:" + name for name in tables}
        program = offline_program(task, refs)
        inputs = {refs[name]: rows for name, rows in tables.items()}
        result = TransformDslInterpreter().run(program, inputs=inputs)
        assert result == list(recompute_transform_program(program, inputs=inputs))
        assert score_rows(public, task.task_id, result)["passed"], (task.task_id, score_rows(public, task.task_id, result))
        assert len(program.operations) <= 6
        assert len(task.output_schema) <= 13
        assert "row_kind" not in json.dumps(tables)
        history[task.task_id] = result
        damaged = [dict(row) for row in result]
        numeric = next(field for field, kind in task.output_schema.items() if kind in {"number", "integer"})
        damaged[0][numeric] += 1
        assert not score_rows(public, task.task_id, damaged)["passed"]
    assert len(history) == 12


def test_release_order_and_missing_history_fail_closed(tmp_path):
    sealed, public = tmp_path / "sealed", tmp_path / "public"
    generate_sealed(sealed)
    with pytest.raises(ValueError, match="prior_release_missing"):
        release_task(sealed, public, "F02")
    release_task(sealed, public, "F01")
    assert not (public / "finance/actual_2026-02.csv").exists()
    release_task(sealed, public, "F02")
    with pytest.raises(ValueError, match="verified_history_missing"):
        bind_inputs(public, "F02")


@pytest.mark.parametrize("mode", ["text", "typed"])
def test_actual_receiver_observes_handoff_and_error(tmp_path, mode):
    path = tmp_path / "handoffs.jsonl"
    transport = HandoffTransport(path, mode=mode)
    source = {"rows": [{"x": 2}], "instruction": "sum x"}

    def receiver(payload):
        payload["rows"][0]["x"] += 1
        return sum(row["x"] for row in payload["rows"])

    assert transport.invoke("retriever", "executor", "run", source, receiver) == 3
    assert source["rows"][0]["x"] == 2
    with pytest.raises(ZeroDivisionError):
        transport.invoke("executor", "summarizer", "fail", source, lambda payload: 1 / 0)
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert [r["event"] for r in rows] == ["send", "receive", "consume", "send", "receive", "error"]
    received = rows[1]
    assert received["wire_bytes"] is None
    assert received["handoff_text_tokens"] is None if mode == "text" else received["handoff_text_tokens"] == 0


def test_metrics_do_not_invent_usage_or_reuse(tmp_path):
    ledger = [{"chain_id": "F:SB-FULL", "task_id": f"F{i:02}", "status": status}
              for i, status in enumerate(("success", "timeout", "blocked", "not_started"), 1)]
    summary = aggregate_slots(ledger)
    assert summary["started_count"] == 2
    assert summary["success_rate"] == 1 / 3
    assert summary["not_started_count"] == 1
    assert summary["provider_total_tokens"] is None
    tables = build_tables(ledger)
    assert all(row["status"] == "not_observed" for row in tables["memory"])
    totals = memory_totals([{"event": "query", "query_id": "q", "candidate_count": 1},
                            {"event": "consume", "query_id": "q", "consume_receipt": ""}])
    assert totals["hit_rate"] == 1
    assert totals["actual_reuse_rate"] == 0


def test_r12_memory_selector_and_witness_are_scoped_to_verified_producer_artifact():
    schema = {"unit_id": "string", "value": "number"}
    memory_inputs = (
        {
            "ref_id": "memory:F10:good",
            "source_task_id": "F10",
            "source_agent": "executor",
            "artifact_lineage": {
                "artifact_ref_id": "artifact:F10",
                "artifact_hash": "artifact-hash",
                "manifest_hash": "manifest-hash",
            },
        },
        {
            "ref_id": "memory:F10:wrong-agent",
            "source_task_id": "F10",
            "source_agent": "summarizer",
            "artifact_lineage": {"artifact_ref_id": "artifact:wrong"},
        },
    )
    assert _select_r12_memory(memory_inputs, task_id="F12") == ("memory:F10:good",)
    with pytest.raises(ValueError, match="candidate_missing:F10"):
        _select_r12_memory((memory_inputs[1],), task_id="F12")

    rows = ({"unit_id": "A", "value": 3.0},)
    witness = _r12_memory_witness(
        memory_inputs[:1], {"memory:F10:good": rows}, task_id="F12", output_schema=schema,
    )
    assert witness["producer_agent"] == "executor"
    assert witness["consumer_agent"] == "summarizer"
    assert witness["row_count"] == 1
    with pytest.raises(ValueError, match="schema_mismatch"):
        _r12_memory_witness(
            memory_inputs[:1], {"memory:F10:good": ({"unit_id": "A"},)},
            task_id="F12", output_schema=schema,
        )


@pytest.mark.parametrize("names", [("source",), ("source", "lookup", "prior")])
def test_provider_program_roundtrip_preserves_refs_and_operations(names):
    from statebus.benchmark.contest_dsl_mainline import _bind_provider_program, _logical_program
    from statebus.contracts import TransformProgram, TransformStep

    refs = {name: "source:" + name for name in names}
    steps = [TransformStep("join_by_key", {"right_ref": refs[name], "left_key": "id", "right_key": "id"})
             for name in names[1:]]
    steps.append(TransformStep("select", {"columns": ["wrong"]}))
    previous = TransformProgram("model-program", tuple(refs.values()), tuple(steps), "test-v1")
    before = previous.canonical_payload()
    logical = _logical_program(previous, refs)
    assert logical.input_artifact_refs == names
    assert [op.arguments["right_ref"] for op in logical.operations[:-1]] == list(names[1:])
    assert _bind_provider_program(logical.canonical_payload(), refs, "test-v1") == previous
    assert previous.canonical_payload() == before


@pytest.mark.parametrize("declared", [["source"], ["lookup", "source"], ["source", "source"],
                                      ["source:source", "source:lookup"], ["source", "foreign"]])
def test_provider_binding_rejects_dropped_reordered_duplicate_or_unauthorized_inputs(declared):
    from statebus.benchmark.contest_dsl_mainline import _bind_provider_program

    with pytest.raises(ValueError, match="provider_logical_input_bindings_mismatch"):
        _bind_provider_program({"input_artifact_refs": declared},
                               {"source": "source:source", "lookup": "source:lookup"}, "test-v1")


@pytest.mark.parametrize("right_ref", ["foreign", "source:lookup"])
def test_provider_binding_rejects_unauthorized_join(right_ref):
    from statebus.benchmark.contest_dsl_mainline import _bind_provider_program

    raw = {"input_artifact_refs": ["source", "lookup"], "output_contract_version": "test-v1",
           "operations": [{"op": "join_by_key", "arguments": {"right_ref": right_ref}}]}
    with pytest.raises(ValueError, match="provider_unauthorized_right_ref"):
        _bind_provider_program(raw, {"source": "source:source", "lookup": "source:lookup"}, "test-v1")


@pytest.mark.parametrize("task_id", ["F01", "O01"])
@pytest.mark.parametrize("repair_valid", [True, False])
def test_real_caller_repair_uses_logical_namespace_and_counts_failed_generation(tmp_path, monkeypatch, task_id, repair_valid):
    from statebus.benchmark import contest_dsl_mainline as runner
    from statebus.benchmark.request_journal import JournalClient
    from statebus.integrations.llm import LLMResult, LLMUsage
    from statebus.utils import sha256_digest

    sealed, public, root = tmp_path / "sealed", tmp_path / "public", tmp_path / "slots" / task_id
    generate_sealed(sealed)
    release_task(sealed, public, task_id)
    task = TASKS[task_id]
    requests = []

    class Client:
        request_events = []

        def describe(self):
            return {"backend": "offline-provider-fixture"}

        async def complete(self, messages, *, purpose, **kwargs):
            payload = json.loads(messages[-1].content)
            self.request_events.append({"role": purpose, "response_prompt_tokens": 10,
                                        "response_completion_tokens": 5, "response_total_tokens": 15})
            if purpose == "executor":
                requests.append(payload)
                names = payload["authorized_input_refs"]
                assert names == list(task.input_schemas)
                if len(requests) == 1:
                    assert payload["output_naming_constraints"]["select_cannot_rename"] is True
                    assert "outputs[i] must be exactly the same name" in payload["output_naming_constraints"]["aggregate_value_field_final_name_rule"]
                    raw = {"input_artifact_refs": names, "output_contract_version": task.output_contract_version,
                           "operations": [{"op": "select", "arguments": {"columns": ["invented"]}}]}
                else:
                    assert len(requests) == 2
                    context = payload["repair_context"]
                    assert context["stage"] == "execution_validation"
                    assert context["validation_errors"] == ["unknown_column:0"]
                    assert context["previous_program"]["input_artifact_refs"] == names
                    assert context["previous_program_hash"] == sha256_digest(context["previous_program"])
                    assert context["validation_error_details"]
                    assert context["aggregate_output_name_constraints"] == []
                    assert context["runtime_program_hash"] != context["previous_program_hash"]
                    raw = offline_program(task, {name: name for name in names}).canonical_payload()
                    if not repair_valid:
                        raw["input_artifact_refs"] = ["source:" + name for name in names]
            else:
                raw = {"claims": []}
                for row in payload["rows"]:
                    entity = row.get("unit_id", row.get("site_id"))
                    evidence = next(e for e in payload["evidence"] if e["text"].startswith(entity + " "))
                    text = " ".join(f"{key}={str(value).lower() if isinstance(value, bool) else value}"
                                    for key, value in row.items()) + ". " + evidence["text"]
                    raw["claims"].append({"text": text, "evidence_id": evidence["id"],
                                          "numeric_fields": {key: float(value) for key, value in row.items()
                                                             if type(value) in (int, float)}})
            return LLMResult(text=json.dumps(raw), model="offline", usage=LLMUsage(10, 5, 15))

    monkeypatch.setattr(runner, "_live_client", lambda path, *_: JournalClient(Client(), path))
    result = runner.run_slot(root, public, task_id, history={}, variant="P-TEXT", mode="live")
    assert result["status"] == ("success" if repair_valid else "runtime_fail")
    assert result["repair"] == 1
    assert result["metrics"]["executor_generation_count"] == 2
    assert result["metrics"]["executor_request_count"] == 2
    assert result["metrics"]["provider_request_count"] == (3 if repair_valid else 2)
    assert result["metrics"]["provider_total_tokens"] == (45 if repair_valid else 30)
    assert result["failure_codes"] == ([] if repair_valid else ["provider_logical_input_bindings_mismatch"])
    assert len(requests) == 2


def test_handoff_tokenizer_counts_actual_text_without_mixing_provider_usage(tmp_path):
    from tokenizers import Tokenizer, models, pre_tokenizers
    from statebus.benchmark.contest_dsl_mainline import _handoff_transport

    model_path = tmp_path / "model"
    model_path.mkdir()
    tokenizer = Tokenizer(models.WordLevel({"[UNK]": 0, "rows": 1}, unk_token="[UNK]"))
    tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
    tokenizer.save(str(model_path / "tokenizer.json"))
    for variant in ("P-TEXT", "SB-FULL"):
        root = tmp_path / variant
        transport = _handoff_transport(root, variant, model_path)
        payload = {"rows": [{"name": "测试", "value": 3}]}
        assert transport.invoke("a", "b", "step", payload, lambda received: received) == payload
        events = [json.loads(line) for line in (root / "handoffs.jsonl").read_text().splitlines()]
        send = events[0]
        if variant == "P-TEXT":
            expected = len(tokenizer.encode(send["text"], add_special_tokens=False).ids)
            assert expected > 0
            assert send["handoff_text_tokens"] == events[1]["handoff_text_tokens"] == expected
            assert send["tokenization"].endswith(":local_no_special_tokens")
        else:
            assert send["handoff_text_tokens"] == 0
        assert "provider_total_tokens" not in send
    missing = _handoff_transport(tmp_path / "missing", "P-TEXT", tmp_path / "absent")
    assert missing.token_counter is None


@pytest.mark.parametrize("observed", [True, False])
def test_state_projection_uses_observed_matrix_bytes_and_release_receipts(tmp_path, observed):
    from types import SimpleNamespace as NS
    from statebus.benchmark.contest_dsl_mainline import _mechanism_events

    publication = NS(handle=NS(size_bytes=20480), contract=NS(blob_hash="hash", schema_version="v1", producer_pid=10))
    receipt = {"producer_pid": 10, "consumer_pid": 20, "observed_blob_hash": "hash",
               "behavioral_effect": "changed", "selected_evidence_bytes": 360}
    if observed:
        receipt.update(observed_size_bytes=20480, read_started_at_ns=1_000_000, read_completed_at_ns=3_000_000)
    release = {"owner_released": True, "physical_reclaimed": True, "release_status": "reclaimed"}
    ctx = NS(memory_queries_by_task={}, memory_consumption_records=[],
             semantic_state_publications={"state": publication}, semantic_consumer_receipts={"state": receipt},
             state_release_reclaim_receipts={"state": release})
    event = NS(event_type="STATE_RESOLVED", channel="semantic_state", event_id="transfer-observed",
               payload={"ref_id": "state", "producer_pid": 10, "consumer_pid": 20},
               metrics={"semantic_state_transfer_count": 1})
    _mechanism_events(tmp_path, NS(context=ctx, runtime=NS(telemetry=NS(events=[event]))), variant="SB-FULL", task_id="case")
    tables = build_tables([{"chain_id": "chain", "task_id": "case", "status": "runtime_fail", "slot_root": str(tmp_path)}])
    events = {row["event"]: row for row in tables["state"]}
    assert set(events) == {"publish", "transfer", "consume", "release"}
    for operation in events:
        assert sum(row[operation + "_count"] for row in events.values()) == 1
    assert events["transfer"]["consumer_pid"] != events["transfer"]["producer_pid"]
    consume = events["consume"]
    assert consume["read_bytes"] == consume["hydrate_bytes"] == (20480 if observed else None)
    assert consume["consume_ms"] == (2 if observed else None)
    assert consume["selected_evidence_bytes"] == 360
    assert events["release"]["physical_reclaimed"] is True
    assert events["release"]["released_bytes"] == 20480


def test_outer_failure_preserves_started_repairs_and_failure_in_reports(tmp_path, monkeypatch):
    from statebus.benchmark import contest_dsl_mainline as runner
    from statebus.benchmark.request_journal import append_event

    def fail_slot(root, *args, **kwargs):
        append_event(root / "generation-events.jsonl", {"repair": False})
        append_event(root / "generation-events.jsonl", {"repair": True})
        raise TimeoutError("provider_timeout")

    monkeypatch.setattr(runner, "run_slot", fail_slot)
    output = tmp_path / "chain"
    runner.run_chain(output, family="finance", variant="P-TEXT", rounds=3, mode="live")
    ledger = json.loads((output / "ledger.json").read_text())
    assert [row["status"] for row in ledger[:3]] == ["timeout", "blocked", "blocked"]
    assert ledger[0]["repair"] == 1
    assert ledger[0]["metrics"]["executor_generation_count"] == 2
    assert ledger[0]["metrics"]["provider_request_count"] is None
    product = json.loads((output / "metrics/product.json").read_text())
    assert product[0]["failure_codes"] == ["provider_timeout"]
    assert product[0]["repair"] == 1

from __future__ import annotations

import copy
import csv
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from statebus.benchmark.adaptive_formal import recompute_formal_rows
from statebus.benchmark.contest_stage1 import final_history_context, publish
from statebus.benchmark.contest_stage1_scorer import reference_rows, score_rows
from statebus.benchmark.contest_stage1_taskpack import TASK_PERIODS, generate_sealed, make_case


def release_through(sealed, public, task):
    for index in range(1, int(task[1:]) + 1):
        publish(sealed, public, f'{task[0]}{index:02d}')


def rewrite_csv(path, edit):
    with path.open(newline='') as handle:
        reader = csv.DictReader(handle)
        fields, rows = reader.fieldnames, list(reader)
    edit(rows)
    with path.open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def recompute(public, task):
    case = make_case(public, task)
    return list(recompute_formal_rows(case.operation, case.spec.arguments, case.source_rows))


def test_main_taskpack_has_twenty_tasks_and_preserves_legacy_inputs(tmp_path):
    sealed = tmp_path / 'sealed'
    generate_sealed(sealed)
    assert len(TASK_PERIODS) == 20
    assert hashlib.sha256((sealed / 'finance/actual_2026-01.csv').read_bytes()).hexdigest() == 'be3caacd91d8ae084234d3e62c304b8090b46221cdbf2ed2b149c087727c8740'
    assert hashlib.sha256((sealed / 'finance/actual_2026-04.csv').read_bytes()).hexdigest() == '6e8433e989420fd2af04262fd6838e583ba91606a5240a40c836ae56575e42ee'


@pytest.mark.parametrize('prefix', ['F', 'O'])
def test_ten_rounds_release_in_order_with_independent_contracts(tmp_path, prefix):
    sealed, public = tmp_path / 'sealed', tmp_path / 'public'
    generate_sealed(sealed)
    for index in range(1, 11):
        task = f'{prefix}{index:02d}'
        publish(sealed, public, task)
        computed = recompute(public, task)
        assert computed and score_rows(public, task, computed)['passed'], task
        assert score_rows(public, task, reference_rows(public, task))['passed'], task
        if index == 8:
            assert not (public / 'finance/budget_2026-06.csv').exists()
            assert not (public / 'service_ops/latency_samples_W08.csv').exists()
    final = recompute(public, prefix + '10')
    if prefix == 'F':
        assert final[0]['half_year_net_revenue_cny'] == sum(final[0][f'm{i:02d}_net_revenue_cny'] for i in range(1, 7))
        assert final[0]['q1_profit_cny'] + final[0]['q2_profit_cny'] == final[0]['half_year_profit_cny']
    else:
        assert final[0]['weeks_included'] == 8
        assert final[0]['w08_p95_latency_ms'] == recompute(public, 'O09')[0]['p95_latency_ms']


@pytest.mark.parametrize('task,period,file,field,sequence,current', [
    ('F03', '2026-01', 'actual', 'cost_cny', 'm01_margin_pct', 'net_revenue_cny'),
    ('O03', 'W01', 'hourly', 'failed_request_count', 'w01_error_rate_pct', 'request_count'),
])
def test_third_round_really_depends_on_prior_raw_data(tmp_path, task, period, file, field, sequence, current):
    sealed, public = tmp_path / 'sealed', tmp_path / 'public'
    generate_sealed(sealed)
    publish(sealed, public, task)
    with pytest.raises(FileNotFoundError, match=task):
        make_case(public, task)
    release_through(sealed, public, task)
    before = recompute(public, task)
    family = 'finance' if task[0] == 'F' else 'service_ops'
    path = public / family / f'{file}_{period}.csv'
    rewrite_csv(path, lambda rows: rows[0].update({field: int(rows[0][field]) + 100}))
    after = recompute(public, task)
    assert after[0][sequence] != before[0][sequence]
    assert after[0][current] == before[0][current]
    assert score_rows(public, task, after)['passed']
    assert not score_rows(public, task, before)['passed']


def test_budget_is_joined_once_and_duplicates_rejected(tmp_path):
    sealed, public = tmp_path / 'sealed', tmp_path / 'public'
    generate_sealed(sealed)
    release_through(sealed, public, 'F08')
    actual = public / 'finance/actual_2026-05.csv'
    rewrite_csv(actual, lambda rows: [r.update(booked_revenue_cny=100, refund_cny=10, cost_cny=50) for r in rows])
    budget = public / 'finance/budget_2026-05.csv'
    rewrite_csv(budget, lambda rows: [r.update(budget_net_revenue_cny=600) for r in rows])
    result = recompute(public, 'F08')
    assert all(r['actual_net_revenue_cny'] == 540 and r['budget_net_revenue_cny'] == 600
               and r['under_budget'] is True and r['variance_cny'] == -60
               and 'variance_pct' not in r and 'attainment_pct' not in r
               for r in result)
    assert score_rows(public, 'F08', result)['passed']
    rewrite_csv(budget, lambda rows: rows.append(dict(rows[0])))
    for read in (lambda: make_case(public, 'F08'), lambda: reference_rows(public, 'F08')):
        with pytest.raises(ValueError, match='duplicate_budget_key'):
            read()


def test_p95_uses_122nd_request_sample_and_strict_threshold(tmp_path):
    sealed, public = tmp_path / 'sealed', tmp_path / 'public'
    generate_sealed(sealed)
    release_through(sealed, public, 'O08')
    samples = public / 'service_ops/latency_samples_W07.csv'
    rewrite_csv(samples, lambda rows: [r.update(latency_ms=379 + i % 128) for i, r in enumerate(rows)])
    result = recompute(public, 'O08')
    assert all(r['sample_count'] == 128 and r['p95_latency_ms'] == 500 and r['exceeds_slo'] is False for r in result)
    assert score_rows(public, 'O08', result)['passed']
    rewrite_csv(samples, lambda rows: [r.update(latency_ms=int(r['latency_ms']) + 1) for r in rows])
    changed = recompute(public, 'O08')
    assert all(r['p95_latency_ms'] == 501 and r['exceeds_slo'] is True for r in changed)
    assert score_rows(public, 'O08', changed)['passed']


@pytest.mark.parametrize('prefix', ['F', 'O'])
def test_closing_report_requires_all_verified_own_chain_outputs(tmp_path, prefix):
    sealed, public = tmp_path / 'sealed', tmp_path / 'public'
    generate_sealed(sealed)
    history = []
    for index in range(1, 10):
        task = f'{prefix}{index:02d}'
        publish(sealed, public, task)
        # Offline fixture only: never used as historical evidence in a live run.
        history.append(dict(task_id=task, ok=True, output_rows=reference_rows(public, task)))
    publish(sealed, public, prefix + '10')
    instructions, records = final_history_context(history, public, prefix + '10')
    assert len(records) == 9 and records[0]['rows']
    assert 'history_sources=' + ','.join(item['task_id'] for item in history) in instructions
    assert final_history_context(history, public, prefix + '09') == ('', ())
    with pytest.raises(ValueError, match='nine_verified'):
        final_history_context(history[1:], public, prefix + '10')
    wrong = copy.deepcopy(history)
    wrong[0]['output_rows'][0]['risk_change'] = 'forged'
    with pytest.raises(ValueError, match='history_failed_revalidation'):
        final_history_context(wrong, public, prefix + '10')
    wrong[0]['ok'] = False
    with pytest.raises(ValueError, match='nine_verified'):
        final_history_context(wrong, public, prefix + '10')


def test_common_metrics_include_failed_costs_repairs_tokens_and_timeouts(tmp_path, monkeypatch):
    from statebus.benchmark.contest_metrics import aggregate_metrics, record_handoff, unified_metrics
    from statebus.benchmark.request_journal import append_event
    tokenizer_dir = tmp_path / 'tokenizer'
    tokenizer_dir.mkdir()
    from tokenizers import Tokenizer
    from tokenizers.models import WordLevel
    tokenizer = Tokenizer(WordLevel({'[UNK]': 0}, unk_token='[UNK]'))
    tokenizer.save(str(tokenizer_dir / 'tokenizer.json'))
    monkeypatch.setenv('STATEBUS_VLLM_TOKENIZER_PATH', str(tokenizer_dir))
    record_handoff(tmp_path / 'handoffs.jsonl', 'executor', 'summarizer', text='结果', scope='test')
    append_event(tmp_path / 'provider.jsonl', dict(event='started', call_id='1', role='executor'))
    append_event(tmp_path / 'provider.jsonl', dict(event='finished', call_id='1', role='executor',
                 provider_events=[{'status': 'error', 'error_type': 'APITimeoutError'}]))
    append_event(tmp_path / 'execution/metric-events.jsonl', dict(event='repair_requested', kind='quality', role='executor'))
    append_event(tmp_path / 'execution/tool-events.jsonl', dict(returncode=124))
    metrics = unified_metrics({}, tmp_path, status='failed')
    assert metrics['provider_request_count'] == 1 and metrics['provider_total_tokens'] is None
    assert metrics['handoff_message_count'] == 1 and metrics['handoff_text_characters'] == 2
    assert metrics['handoff_utf8_bytes'] == 6 and metrics['handoff_tokens'] == 1
    assert metrics['repairs']['quality'] == 1 and metrics['repairs_by_role']['executor'] == 1
    assert metrics['timeout_count'] == 2
    aggregated = aggregate_metrics([dict(status='failed', metrics=metrics), dict(status='blocked_by_prior_failure')])
    assert aggregated['attempted_count'] == 1 and aggregated['provider_total_tokens'] is None
    monkeypatch.setenv('STATEBUS_VLLM_TOKENIZER_PATH', str(tmp_path / 'missing'))
    record_handoff(tmp_path / 'handoffs.jsonl', 'executor', 'summarizer', text='missing', scope='test')
    assert unified_metrics({}, tmp_path)['handoff_tokens'] is None


@pytest.mark.parametrize('stop', [False, True])
def test_main_runner_has_forty_slots_and_never_runs_past_a_failed_predecessor(tmp_path, monkeypatch, stop):
    import statebus.benchmark.contest_stage1 as runner
    root = tmp_path / 'main'
    calls = []
    class Worker:
        def __init__(self, command, **kwargs):
            calls.append(command)
            self.task = command[command.index('--task') + 1]
            self.profile = command[command.index('--profile') + 1]
            self.path = Path(command[command.index('--output-root') + 1])
            history = json.loads((self.path / 'history-before.json').read_text())
            assert [item['task_id'] for item in history] == [f'{self.task[0]}{i:02d}' for i in range(1, int(self.task[1:]))]
            self.failed = self.task == 'F03' and self.profile == 'SB-FULL'
            runner.write_json(self.path / 'result.json', dict(ok=not self.failed, output_rows=[], summary_text='offline fixture'))
        def wait(self, timeout=None):
            return int(self.failed)
    monkeypatch.setattr(runner.subprocess, 'Popen', Worker)
    args = SimpleNamespace(output_root=root, family='all', profile='both', dry_run=False, main_chain=True,
                           sb_memory_policy='validated_replay', stop_on_failure=stop,
                           embedding_model_path='unused', embedding_device='cpu')
    assert runner.run(args) == 1
    summary = json.loads((root / 'summary.json').read_text())
    assert summary['planned_count'] == 40 and len(summary['chain_results']) == 4
    assert summary['main_chain_completed'] is False
    assert [row['status'] for row in summary['ledger'][:10]] == ['success', 'success', 'failed'] + ['blocked_by_prior_failure']*7
    assert len(calls) == (3 if stop else 33)
    assert summary['passed_count'] == (2 if stop else 32)
    assert sum(c['completed_ten_rounds'] for c in summary['chain_results']) == (0 if stop else 3)


@pytest.mark.parametrize('prefix', ['F', 'O'])
def test_text_closer_sends_real_history_per_entity_batch_and_repairs_without_changing_numbers(tmp_path, monkeypatch, prefix):
    from statebus.benchmark import contest_stage1_text as text
    from statebus.benchmark.contest_stage1_report import REPORT_INSTRUCTIONS, report_sources
    from statebus.benchmark.contest_stage1_taskpack import files_for
    sealed, public = tmp_path / 'sealed', tmp_path / 'public'
    generate_sealed(sealed)
    history = []
    for index in range(1, 11):
        task = f'{prefix}{index:02d}'
        publish(sealed, public, task)
        if index < 10:
            history.append(dict(task_id=task, ok=True, output_rows=reference_rows(public, task)))
    instructions, history_records = final_history_context(history, public, task)
    case = make_case(public, task)
    rows = reference_rows(public, task)
    note = files_for(public, task)[-1]
    sources = report_sources(note.read_text(), source_name=note.name, period=TASK_PERIODS[task], entities=case.spec.target_entities)
    source = 'import json\nfrom pathlib import Path\nrows=json.loads(Path("inputs/task.json").read_text())\nPath("outputs/result.json").write_text(json.dumps(rows))\n'
    report_calls = []
    class Client:
        async def complete(self, messages, *, purpose, **kwargs):
            if purpose == 'summarizer':
                prompt = messages[-1].content
                batch = [rows[max(0, len(report_calls) - 1)]]
                supplied = prompt.split('Own-profile historical_results (cross-check only):\n')[1].split('\nPrior report errors:')[0]
                records = json.loads(supplied)
                key = 'unit_id' if prefix == 'F' else 'site_id'
                assert {row[key] for record in records for row in record['rows']} == {r[key] for r in batch}
                assert len(records) == 9
                report_calls.append(messages)
                summary = '\n'.join(f"{r[key]} risk={str(r.get('below_20_pct', r.get('exceeds_slo'))).lower()} risk_change={r['risk_change']} source={sources[r[key]]['locator']} {sources[r[key]]['context']} history_sources=" + ','.join(item['task_id'] for item in records) for r in batch)
                if len(report_calls) == 1:
                    summary = summary.replace('risk=', 'wrong=')
                return SimpleNamespace(text=json.dumps(dict(rows=batch, summary=summary)), finish_reason='stop')
            return SimpleNamespace(text={'planner': 'Read, compute, verify, report.', 'retriever': note.read_text(), 'executor': source}[purpose], finish_reason='stop')
    class Config:
        def with_mode(self, *args, **kwargs): return self
        def with_provider_override(self, *args, **kwargs): return self
        def with_role_override(self, *args, **kwargs): return self
        def role_config(self, *args, **kwargs): return SimpleNamespace(provider='local')
    def sandbox(self, *, outputs_dir, **kwargs):
        (outputs_dir / 'result.json').write_text(json.dumps(rows))
        return SimpleNamespace(actual_backend='offline_fixture', completed=SimpleNamespace(returncode=0, stdout='', stderr=''))
    monkeypatch.delenv('STATEBUS_PROVIDER_JOURNAL', raising=False)
    monkeypatch.setattr(text.LLMConfig, 'from_runtime', lambda: Config())
    monkeypatch.setattr(text, 'build_llm_client', lambda _: Client())
    monkeypatch.setattr(text.CodeActSandboxRunner, 'run_llm_bwrap', sandbox)
    result = text.run_text(case, tmp_path / 'execution', notes=note.read_text(), source_name=note.name, report_sources=sources,
                           historical_results=history_records, report_instructions=REPORT_INSTRUCTIONS + instructions)
    assert result['ok'] and result['output_rows'] == rows
    assert len(report_calls) == 5
    assert [c['batch'] for c in result['report_checks']] == [1, 1, 2, 3, 4]
    tokenizer_file = Path('/data/models/Qwen3-32B/tokenizer.json')
    if tokenizer_file.is_file():
        from tokenizers import Tokenizer
        tokenizer = Tokenizer.from_file(str(tokenizer_file))
        for messages in report_calls:
            # Includes room for chat-template tokens; 4096 output stays fixed.
            assert sum(len(tokenizer.encode(m.content, add_special_tokens=False).ids) for m in messages) + 4096 + 128 < 8192


def test_risk_repair_restates_public_truth_table_without_gold():
    from statebus.benchmark.adaptive_formal import _operation_semantics
    from statebus.runtime.llm_codeact import build_code_repair_guidance
    from statebus.contracts import CodeGenerationPolicy
    semantics = _operation_semantics('finance_quarterly_review', dict(periods=['2026-01','2026-02','2026-03']))
    guidance = build_code_repair_guidance(('quality_error:formal_recomputation_field_mismatch:risk_change',),
        CodeGenerationPolicy(capability_id='execute_bounded_python_v2'), operation_semantics=semantics)
    assert '(false,false)=still_clear' in guidance
    assert 'initial is allowed ONLY' in guidance
    assert 'U-D' not in guidance and '604836' not in guidance


def test_new_tasks_publish_explicit_evidence_contract_and_repair(tmp_path):
    from statebus.benchmark.adaptive_formal_mainline import _compact_planner_replan_context
    sealed, public = tmp_path / 'sealed', tmp_path / 'public'
    generate_sealed(sealed)
    release_through(sealed, public, 'O08')
    case = make_case(public, 'O08')
    assert 'Markdown PROSE' in case.sample.request_text
    assert 'retrieve_semantic_evidence_v1, NOT retrieve_table_evidence_v1' in case.sample.request_text
    context = _compact_planner_replan_context(case, SimpleNamespace(steps=()), policy_issues=(),
        repair_errors=('public_review_notes_are_markdown_prose_require_semantic_retrieval_not_table',))
    assert context['requirements']['evidence_capability'] == 'retrieve_semantic_evidence_v1'


@pytest.mark.parametrize('prefix', ['F', 'O'])
def test_typed_closing_history_reaches_actual_role_prompt_with_repair_budget(tmp_path, prefix):
    from statebus.runtime.role_path import RolePathRunner
    from statebus.benchmark.contest_stage1_report import REPORT_INSTRUCTIONS, report_sources
    from statebus.benchmark.contest_stage1_taskpack import files_for
    from statebus.utils import stable_json_dumps
    from statebus.integrations.llm import parse_tagged_json
    sealed, public = tmp_path / 'sealed', tmp_path / 'public'
    generate_sealed(sealed)
    history = []
    for i in range(1, 11):
        task = f'{prefix}{i:02d}'
        publish(sealed, public, task)
        if i < 10:
            history.append(dict(task_id=task, ok=True, output_rows=reference_rows(public, task)))
    instructions, records = final_history_context(history, public, task)
    row = reference_rows(public, task)[0]
    entity = row.get('unit_id', row.get('site_id'))
    scoped = [dict(task_id=item['task_id'], rows=[r for r in item['rows']
               if r.get('unit_id', r.get('site_id')) == entity]) for item in records]
    note = files_for(public, task)[-1]
    source = report_sources(note.read_text(), source_name=note.name, period=TASK_PERIODS[task], entities=(entity,))[entity]
    class Captured(Exception): pass
    rendered = []
    class Recorder(RolePathRunner):
        def _complete_json_role(self, *, prompt, **kwargs):
            rendered.append(prompt)
            raise Captured()
    previous = dict(claims=[dict(claim_id=entity, claim_text=f"{entity} risk=true risk_change=new {source['context']} history_sources=" + ','.join(item['task_id'] for item in records),
                    claim_type='risk', numeric_fields={k:v for k,v in row.items() if type(v) in (int,float)},
                    supporting_evidence_item_ids=['current-evidence'], supporting_artifact_ref_ids=['verified-artifact'], status='ready')], status='ready')
    for repair in (False, True):
        with pytest.raises(Captured):
            Recorder(llm_client=None).build_claim_set(task_id=task, claim_set_id='closing',
                verified_artifact_refs=('verified-artifact',), evidence_items=(dict(id='current-evidence',locator=source['locator'],text=source['source_text']),),
                task_goal='Complete the closing report. Own-profile historical_results (cross-check only): ' + stable_json_dumps(scoped),
                artifact_summaries=(dict(artifact_ref_id='verified-artifact',status='verified',rows=[row]),),
                expected_claim_count=1, report_requirements=REPORT_INSTRUCTIONS+instructions,
                repair_context=dict(previous_candidate=previous,validation_errors=['report_risk:'+entity]) if repair else None)
        payload = parse_tagged_json(rendered[-1], 'sb-claim-set-v1')
        assert records[0]['task_id'] in payload['task_goal']
        assert payload['reference_catalog']['artifacts'][0]['verified_rows'] == [row]
    tokenizer_file = Path('/data/models/Qwen3-32B/tokenizer.json')
    if tokenizer_file.is_file():
        from tokenizers import Tokenizer
        tokenizer = Tokenizer.from_file(str(tokenizer_file))
        assert all(len(tokenizer.encode(prompt,add_special_tokens=False).ids) + 4096 + 128 < 8192 for prompt in rendered)

"""Public v2 definitions, unchanged v1 inputs, and honest chain denominators."""
from dataclasses import replace
import csv
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from statebus.benchmark import contest_stage1, contest_stage2
from statebus.benchmark.adaptive_formal import recompute_formal_rows
from statebus.benchmark.contest_stage1_scorer import reference_rows, score_rows
from statebus.benchmark.contest_stage1_taskpack import generate_sealed, make_case, files_for, PERIODS
from statebus.benchmark.contest_stage1_text import output_matches, _current_entities


def test_v2_generation_preserves_original_v1_csv_bytes(tmp_path):
    # Hashes of the immutable Stage1 history-fix-20260925b released inputs.
    expected = {
        'finance/actual_2026-01.csv': 'be3caacd91d8ae084234d3e62c304b8090b46221cdbf2ed2b149c087727c8740',
        'finance/actual_2026-02.csv': '28ef94430dd3005d349ac4d9639498f4d4cb18140415fbebd19c139ba23b73a9',
        'service_ops/hourly_W01.csv': '6fe9dd590f7bcc041a3c9f4198b2aa896c33ff5727fc01fe22f333df74b8d217',
        'service_ops/hourly_W02.csv': 'a05e51389b30e4883ca55eda79925178ade2a9029d5ac086ca7744aadf958e22',
    }
    generate_sealed(tmp_path/'sealed')
    assert len(PERIODS) == 4
    for name, digest in expected.items():
        assert hashlib.sha256((tmp_path/'sealed'/name).read_bytes()).hexdigest() == digest


@pytest.mark.parametrize('task_id,entity_key,raw_field,output_field', [
    ('F06', 'unit_id', 'refund_cny', 'net_revenue_cny'),
    ('O06', 'site_id', 'final_failed_request_count', 'failed_request_count'),
])
def test_v2_published_inputs_drive_both_validators(tmp_path, task_id, entity_key, raw_field, output_field):
    sealed, public = tmp_path/'sealed', tmp_path/'public'
    generate_sealed(sealed)
    for suffix in ('01', '02'):
        contest_stage1.publish(sealed, public, task_id[0]+suffix)
    with pytest.raises(FileNotFoundError):
        make_case(public, task_id)
    assert not list(public.rglob('dictionary_v2.md'))
    old_case = make_case(public, task_id[0]+'02')
    contest_stage1.publish(sealed, public, task_id)
    case = make_case(public, task_id)
    expected = reference_rows(public, task_id)
    assert len(case.source_rows) == (24 if task_id.startswith('F') else 672)
    assert all(row['is_current'] for row in case.source_rows)
    assert case.source_schema != old_case.source_schema
    assert case.operation != old_case.operation
    assert raw_field in case.sample.request_text
    assert output_field not in case.source_schema
    assert {row['risk_change'] for row in expected} == {'initial'}
    assert _current_entities(case) == tuple(row[entity_key] for row in expected)
    computed = list(recompute_formal_rows(case.operation, case.spec.arguments, case.source_rows))
    assert computed == expected and output_matches(case, computed)
    assert score_rows(public, task_id, computed)['passed']

    # Deliberately apply the old business interpretation. Both gates reject it.
    wrong = [dict(row) for row in expected]
    group = [row for row in case.source_rows if row[entity_key] == expected[0][entity_key]]
    wrong[0][output_field] = sum(row['booked_revenue_cny' if task_id.startswith('F') else 'failed_attempt_count'] for row in group)
    assert not output_matches(case, wrong)
    assert not score_rows(public, task_id, wrong)['passed']

    # Mutate a released raw quantity; neither validator may reuse its prior answer.
    raw_path = next(p for p in files_for(public, task_id) if p.suffix == '.csv' and p.name != 'slo.csv')
    with raw_path.open(newline='') as f:
        reader = csv.DictReader(f); fields = reader.fieldnames; rows = list(reader)
    rows[0][raw_field] = str(int(rows[0][raw_field]) + 10)
    with raw_path.open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields); writer.writeheader(); writer.writerows(rows)
    changed = make_case(public, task_id)
    new_expected = reference_rows(public, task_id)
    assert new_expected != expected
    assert list(recompute_formal_rows(changed.operation, changed.spec.arguments, changed.source_rows)) == new_expected
    assert not output_matches(changed, expected)
    assert not score_rows(public, task_id, expected)['passed']

    if task_id.startswith('O'):
        # Diagnostic attempts must have no influence on the final-failure ratio.
        attempts = tuple(dict(row, failed_attempt_count=99999) for row in changed.source_rows)
        assert output_matches(replace(changed, source_rows=attempts), new_expected)


def test_chain_failure_preserves_blocked_and_unstarted_tasks(tmp_path, monkeypatch):
    started = []
    class Worker:
        def __init__(self, command, **kwargs):
            started.append(command[command.index('--task')+1])
        def wait(self, timeout=None):
            return 1
    monkeypatch.setattr(contest_stage1.subprocess, 'Popen', Worker)
    root = tmp_path/'chain'
    args = SimpleNamespace(output_root=root, dry_run=False, family='all', profile='SB-FULL',
                           sb_memory_policy='validated_replay', embedding_model_path='unused', embedding_device='cpu',
                           chain_tasks=('F01','F02','F06','O01','O02','O06'),
                           block_failed_chain=True, stop_on_failure=True)
    assert contest_stage1.run(args) == 1
    summary = json.loads((root/'summary.json').read_text())
    assert started == ['F01']
    assert summary['planned_count'] == 6 and summary['passed_count'] == 0
    assert [row['status'] for row in summary['ledger']] == [
        'failed', 'blocked_by_prior_failure', 'blocked_by_prior_failure', 'not_started', 'not_started', 'not_started']
    assert all(row['provider'] is None for row in summary['ledger'][1:])


@pytest.mark.parametrize('smoke,count', [(True,4), (False,12)])
def test_memory_caller_uses_public_worker_and_records_each_slot(tmp_path, monkeypatch, smoke, count):
    calls = []
    def worker(args):
        calls.append(args)
        ledger = [{'task_id': task, 'status':'success', 'ok':True, 'provider':None}
                  for task in args.chain_tasks]
        contest_stage1.write_json(args.output_root/'ledger.json', ledger)
        return 0
    monkeypatch.setattr(contest_stage1, 'run', worker)
    result = contest_stage2._run_stage1_memory_smoke(
        tmp_path, embedding_model_path='unused', embedding_device='cpu', smoke=smoke)
    assert result['status'] == 'passed'
    assert result['started_executions'] == result['planned_executions'] == count
    assert len(result['rows']) == count
    assert {args.sb_memory_policy for args in calls} == {'none','validated_replay'}
    if not smoke:
        assert all('F06' in args.chain_tasks and 'O06' in args.chain_tasks for args in calls)


def test_memory_startup_failure_never_counts_unstarted_requests(tmp_path, monkeypatch):
    def failed(args):
        raise RuntimeError('startup failure before a task starts')
    monkeypatch.setattr(contest_stage1, 'run', failed)
    result = contest_stage2._run_stage1_memory_smoke(
        tmp_path, embedding_model_path='unused', embedding_device='cpu', stop_on_failure=True)
    assert result['status'] == 'failed'
    assert result['smoke_executions'] == result['started_executions'] == 0
    assert result['planned_executions'] == len(result['rows']) == 4
    assert {r['status'] for r in result['rows']} == {'not_started'}


def test_diagnostic_communication_is_not_a_passed_live_smoke():
    result = contest_stage2.build_acceptance(
        mechanism='communication', smoke=True, plan=contest_stage2.build_plan('communication', smoke=True),
        components={'communication': {'status':'diagnostic_only'}}, stage1={}, preflight=None, live=True)
    assert result['ok']  # A diagnostic can finish successfully without proving the mechanism.
    assert not result['smoke_passed']
    assert not result['formal_stage2_ready'] and not result['stage3_allowed']


@pytest.mark.parametrize('offline_failure', [False, True])
def test_stopped_live_run_never_promotes_offline_passes(tmp_path, monkeypatch, offline_failure):
    def offline(root, mechanism, plan, **kwargs):
        return {
            'memory': {'status': 'failed' if offline_failure else 'passed'},
            'communication': {'status': 'passed', 'rows': [
                {'slot_id': 'communication:F01:text', 'status': 'success'}]},
        }
    def memory(*args, **kwargs):
        assert not offline_failure, 'offline failure must stop before model work'
        return {'status': 'failed', 'rows': []}
    monkeypatch.setattr(contest_stage2, 'run_offline_contracts', offline)
    monkeypatch.setattr(contest_stage2, '_run_stage1_memory_smoke', memory)
    root = tmp_path/'stage2'
    result = contest_stage2.run_stage2(
        output_root=root, stage1_root=tmp_path, mechanism='all', smoke=True,
        offline=False, stop_on_failure=True, profile='test',
        embedding_model_path='unused', embedding_device='cpu')
    assert result['components']['memory'] == 'failed'
    assert result['components']['communication'] == 'not_started'
    assert result['component_details']['communication']['offline_contract']['status'] == 'passed'
    assert not result['ok'] and not result['smoke_passed']
    rows = json.loads((root/'raw_rows.json').read_text())
    assert rows and {row['evidence_scope'] for row in rows} == {'offline_contract'}
    slots = json.loads((root/'task-plan.json').read_text())['slots']
    assert all(row['status'] == 'not_started' for row in slots if row['smoke_selected'])


def test_completed_memory_slots_are_persisted_as_executed(tmp_path, monkeypatch):
    monkeypatch.setattr(contest_stage2, 'run_offline_contracts',
                        lambda *args, **kwargs: {'memory': {'status': 'passed'}})
    def memory(*args, **kwargs):
        return {'status': 'passed', 'rows': [dict(row, status='success', ok=True)
                for row in contest_stage2.memory_plan(smoke=False)]}
    monkeypatch.setattr(contest_stage2, '_run_stage1_memory_smoke', memory)
    root = tmp_path/'stage2'
    result = contest_stage2.run_stage2(
        output_root=root, stage1_root=tmp_path, mechanism='memory', smoke=False,
        offline=False, stop_on_failure=True, profile='test',
        embedding_model_path='unused', embedding_device='cpu')
    assert result['not_started'] == []
    slots = json.loads((root/'task-plan.json').read_text())['slots']
    assert len(slots) == 12 and {row['status'] for row in slots} == {'success'}
    assert {row['evidence_scope'] for row in json.loads((root/'raw_rows.json').read_text())} == {'live'}
    assert not result['formal_stage2_ready']  # Memory alone cannot admit all Stage 2.


def test_state_records_retain_variant_outcomes(monkeypatch, tmp_path):
    from statebus.benchmark import semantic_holdout
    monkeypatch.setattr(semantic_holdout, 'run_semantic_state_ablation', lambda **kwargs: {
        'ok': False, 'rows': [
            {'task_id': 'semantic-holdout-s1', 'variant': mode, 'ok': mode != 'on'}
            for mode in ('off', 'on', 'consumer_off')]})
    plan = contest_stage2.build_plan('state', smoke=True)
    result = contest_stage2.run_live_components(
        tmp_path, tmp_path, 'state', plan, embedding_model_path='unused', embedding_device='cpu')
    assert result['state']['status'] == 'failed'
    assert [row['status'] for row in plan if row['smoke_selected']] == ['success', 'failed', 'success']


def test_memory_worker_error_reaches_task_ledger_and_stage2_failures(tmp_path, monkeypatch):
    error = 'model context overflow: messages=8685 completion=2200 limit=8192'
    class Worker:
        def __init__(self, command, **kwargs):
            task = Path(command[command.index('--output-root') + 1])
            contest_stage1.write_json(task/'failure.json', {'type': 'BadRequestError', 'error': error})
        def wait(self, timeout=None):
            return 1
    monkeypatch.setattr(contest_stage1.subprocess, 'Popen', Worker)
    monkeypatch.setattr(contest_stage2, 'run_offline_contracts',
                        lambda *args, **kwargs: {'memory': {'status': 'passed'}})
    root = tmp_path/'stage2'
    result = contest_stage2.run_stage2(
        output_root=root, stage1_root=tmp_path, mechanism='memory', smoke=True,
        offline=False, stop_on_failure=True, profile='test',
        embedding_model_path='unused', embedding_device='cpu')
    assert not result['ok']
    failures = json.loads((root/'failures.json').read_text())['rows']
    assert len(failures) == 1
    assert failures[0]['task_id'] == 'F01' and failures[0]['variant'] == 'none'
    assert failures[0]['error'] == error
    assert json.loads(Path(failures[0]['failure_path']).read_text())['error'] == error
    assert Path(failures[0]['log_path']).exists()
    rows = json.loads((root/'raw_rows.json').read_text())
    assert next(row for row in rows if row.get('status') == 'failed')['error'] == error

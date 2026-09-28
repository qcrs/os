from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace

import pytest

from statebus.benchmark.contest_stage1 import publish, write_json
from statebus.benchmark.contest_stage1_report import REPORT_CONTRACT_VERSION, report_sources
from statebus.benchmark.contest_stage1_scorer import reference_rows
from statebus.benchmark.contest_stage1_taskpack import generate_sealed, PERIODS, ENTITIES, FAMILIES, files_for
from statebus.benchmark.contest_stage_gate import audit_stage1, VARIANTS
from statebus.benchmark.request_journal import append_event, summarize_journal


def fixture_batch(root, variant):
    profile, label, policy = VARIANTS[variant]
    generate_sealed(root / 'sealed')
    ledger = []
    for task_id in PERIODS:
        task = root / FAMILIES[task_id[0]] / label / task_id
        public = task / 'public'
        producer = task_id[0] + '01'
        publish(root / 'sealed', public, producer)
        publish(root / 'sealed', public, task_id)
        rows = reference_rows(public, task_id)
        note = files_for(public, task_id)[-1]
        sources = report_sources(note.read_text(), source_name=note.name, period=PERIODS[task_id], entities=ENTITIES[task_id[0]])
        claims = []
        for row in rows:
            entity = row.get('unit_id', row.get('site_id'))
            risk = row.get('below_20_pct', row.get('exceeds_slo'))
            claims.append({'claim_text': f"{entity} risk={str(risk).lower()} risk_change={row['risk_change']} "
                                        f"{sources[entity]['locator']} {sources[entity]['context']}",
                           'supporting_evidence_item_ids': [entity], 'citation_locators': [sources[entity]['locator']]})
        result = dict(ok=True, task_id=task_id, profile=profile, external_score_passed=True, configuration_label=label, memory_policy=policy,
                      report_contract_version=REPORT_CONTRACT_VERSION, output_rows=rows,
                      summary_text='\n'.join(c['claim_text'] for c in claims), claim_sets=[{'claims': claims}],
                      report_evidence_items=[dict(id=k, text=v['source_text'], locator=v['locator']) for k,v in sources.items()])
        result.update(source_artifact_hash='input-' + task_id, execution_output_artifact_hash='output-' + task_id,
                      execution_records=[dict(output_hash='output-' + task_id, exit_code=0, output_quality_valid=True,
                                              output_schema_valid=True, source_hash='source-' + producer, verified_artifact_id='artifact-' + task_id)],
                      terminal_quality_reports=[dict(verified=True, recomputation_evaluated=True, recomputation_passed=True,
                                                     provenance_passed=True, output_artifact_hash='output-' + task_id)],
                      memory_consumption_records=[], memory_query_results={'retriever': {'retrieval_decision': 'no_match', 'compatibility_decisions': []}},
                      memory_commit_decision=dict(committed=policy != 'none', artifact_hash='output-' + task_id,
                                                  input_lineage_hashes=['input-' + task_id], benchmark_gold_used=False,
                                                  memory_admission_receipt_hash='admission-' + task_id, memory_id='memory-' + task_id))
        if variant == 'sb-full' and task_id.endswith('02'):
            result['runtime_session'] = dict(session_id=task_id, capability_grant_hashes=['grant'],
                                            attempt_records=[dict(attempt_id='attempt', step_id='step', owner_role='executor', state='COMPLETED')])
            result['memory_query_results']['retriever']['compatibility_decisions'] = [dict(memory_id='memory-' + producer,
                                                                                        policy_approved=True, replay_class='validated_replay')]
            result['memory_consumption_records'] = [dict(memory_id='memory-' + producer,
                memory_admission_receipt_hash='admission-' + producer, consumer_runtime_task_id=task_id,
                consumer_session_id=task_id, consumer_attempt_id='attempt', consumer_step_id='step', consumer_role='executor',
                capability_grant_hash='grant', attempt_result_admission_receipt_hash='admitted', memory_commit_hash='committed',
                replay_eligibility_receipt_hash='eligible', query_hash='query', recipe_recomputed=True,
                recipe_step_status='skipped_generation', replay_class='validated_replay', downstream_ref_ids=['artifact-' + task_id])]
        write_json(task / 'result.json', result)
        write_json(task / 'scorer.json', dict(passed=True, report_contract_version=REPORT_CONTRACT_VERSION, business_report_errors=[]))
        write_json(task / 'execution-environment.json', dict(profile=profile, embedding_device='cuda:0', configuration_label=label, memory_policy=policy))
        write_json(task / 'effective-budget.json', {'http':90})
        (task / 'effective-llm.yaml').write_text('model: test\n')
        append_event(task / 'provider.jsonl', dict(event='started', call_id='one', role='planner'))
        append_event(task / 'provider.jsonl', dict(event='finished', call_id='one', role='planner', provider_events=[
            dict(response_prompt_tokens=10, response_completion_tokens=5, response_total_tokens=15)]))
        ledger.append(dict(task_id=task_id, family=FAMILIES[task_id[0]], profile=profile, configuration_label=label,
                           memory_policy=policy, status='success', ok=True, result_path=str(task / 'result.json'),
                           provider=summarize_journal(task / 'provider.jsonl')))
    write_json(root / 'summary.json', dict(planned_count=4, passed_count=4, report_contract_version=REPORT_CONTRACT_VERSION,
                                         formal_headline_eligible=False, semantic_review_required=True, ledger=ledger))
    return root


@pytest.mark.parametrize('variant', VARIANTS)
def test_complete_batch_is_audited_against_sources_and_journal(tmp_path, variant):
    root = fixture_batch(tmp_path / variant, variant)
    report = audit_stage1(root, variant)
    assert report['ok'], report
    assert len(report['tasks']) == 4 and report['formal_headline_eligible'] is False
    if variant == 'sb-full':
        assert report['tasks'][1]['memory']['status'] == 'consumed'
        assert report['tasks'][1]['executor_provider_requests'] == 0


@pytest.mark.parametrize('file,mutation,error', [
    ('summary.json', lambda x: x['ledger'][0].update(task_id='F99'), 'task_ids'),
    ('summary.json', lambda x: x['ledger'][0].update(configuration_label='P-TEXT'), 'ledger_variant'),
    ('summary.json', lambda x: x['ledger'][0]['provider']['usage'].update(total_tokens=0), 'provider_journal_mismatch'),
    ('finance/SB-FULL/F02/scorer.json', lambda x: x.update(report_contract_version='old'), 'report_contract'),
    ('finance/SB-FULL/F02/result.json', lambda x: x.update(task_id='F01'), 'result_identity'),
    ('finance/SB-FULL/F02/result.json', lambda x: x['output_rows'][0].update(profit_cny=0), 'independent_score'),
    ('finance/SB-FULL/F02/result.json', lambda x: x['claim_sets'][0]['claims'][0].update(claim_text='U-A'), 'report_recheck'),
    ('finance/SB-FULL/F02/result.json', lambda x: x['memory_consumption_records'][0].update(recipe_recomputed=False), 'memory_recipe_not_recomputed'),
    ('finance/SB-FULL/F02/result.json', lambda x: x['memory_consumption_records'][0].update(capability_grant_hash='wrong'), 'memory_grant_mismatch'),
    ('finance/SB-FULL/F02/result.json', lambda x: x['memory_consumption_records'][0].update(memory_id='other-lane'), 'memory_not_from_own_producer'),
    ('finance/SB-FULL/F02/result.json', lambda x: x.update(source_artifact_hash='input-F01'), 'current_input_not_changed'),
])
def test_false_success_summary_does_not_bypass_evidence(tmp_path, file, mutation, error):
    root = fixture_batch(tmp_path / 'batch', 'sb-full')
    path = root / file
    payload = json.loads(path.read_text()); mutation(payload); write_json(path, payload)
    report = audit_stage1(root, 'sb-full')
    assert not report['ok'] and error in str(report['errors'])


def test_missing_artifact_and_legitimate_miss_are_distinguished(tmp_path):
    root = fixture_batch(tmp_path / 'batch', 'sb-full')
    path = root / 'finance/SB-FULL/F02/result.json'
    result = json.loads(path.read_text()); result['memory_consumption_records'] = []; write_json(path, result)
    report = audit_stage1(root, 'sb-full')
    assert report['ok'] and report['tasks'][1]['memory']['status'] == 'not_observed'
    (path.parent / 'scorer.json').unlink()
    assert not audit_stage1(root, 'sb-full')['ok']


def test_worker_failure_envelope_reports_root_cause_without_cascading_schema_errors(tmp_path):
    root = fixture_batch(tmp_path / 'batch', 'p-text')
    task = root / 'service_ops/P-TEXT/O01'
    write_json(task / 'result.json', {
        'ok': False,
        'error': 'worker_failed_before_result',
        'failure': {'error': 'text_tool_quality_failed:public_contract_recomputation_mismatch'},
        'output_rows': [],
        'quality_observed': False,
    })
    (task / 'scorer.json').unlink()
    summary = json.loads((root / 'summary.json').read_text())
    summary['ledger'][2].update(status='failed', ok=False, returncode=1)
    write_json(root / 'summary.json', summary)

    report = audit_stage1(root, 'p-text')
    assert not report['ok']
    errors = '\n'.join(report['errors'])
    assert 'O01:worker_failure:ValueError:worker_failed_before_result' in errors
    assert 'O01:result_identity' not in errors
    assert 'O01:report_contract' not in errors
    assert 'O01:independent_score' not in errors
    assert 'FileNotFoundError' in errors
    assert report['tasks'][2]['provider']['usage']['total_tokens'] == 15
    assert report['costs']['usage']['total_tokens'] == 60


def test_missing_usage_stays_null_and_has_explicit_reason(tmp_path):
    root = fixture_batch(tmp_path / 'batch', 'p-text')
    task = root / 'finance/P-TEXT/F01'
    events = [json.loads(line) for line in (task / 'provider.jsonl').read_text().splitlines()]
    events[1]['provider_events'][0].pop('response_total_tokens')
    (task / 'provider.jsonl').write_text('\n'.join(json.dumps(e) for e in events) + '\n')
    summary = json.loads((root / 'summary.json').read_text())
    summary['ledger'][0]['provider'] = summarize_journal(task / 'provider.jsonl')
    write_json(root / 'summary.json', summary)
    report = audit_stage1(root, 'p-text')
    assert report['ok'] and report['tasks'][0]['usage_status'] == 'missing_explicit'
    assert report['tasks'][0]['provider']['usage']['total_tokens'] is None


def test_dry_run_plan_json_is_separate_from_diagnostics(tmp_path, monkeypatch):
    import statebus.benchmark.contest_stage1 as runner
    monkeypatch.setattr(runner, 'effective_configuration', lambda: {'providers': {}, 'roles': {'executor': {'max_tokens': 1}}})
    monkeypatch.setattr(runner, 'effective_budget', lambda _: {'test': True})
    plan = tmp_path / 'plan.json'
    args = SimpleNamespace(output_root=tmp_path / 'unused', profile='SB-FULL', sb_memory_policy='none', family='all',
                           dry_run=True, embedding_model_path='local', embedding_device='cuda:0', plan_output=plan)
    assert runner.run(args) == 0
    assert json.loads(plan.read_text())['planned_count'] == 4 and not args.output_root.exists()


@pytest.mark.skipif(shutil.which('jq') is None, reason='Host shell orchestration requires jq')
def test_stage2_reports_required_invocation_without_docker_or_codeact_block():
    os_root = Path(__file__).resolve().parents[2]
    # Use an output within os as required; only a status artifact, no model work.
    env = dict(os.environ, STATEBUS_EMBED_DEVICE='cuda:0')
    with tempfile.TemporaryDirectory(prefix='gate-test-', dir=os_root / 'runs') as temporary:
        root = Path(temporary) / 'stage2'
        result = subprocess.run(['bash', 'scripts/run_contest_measurement_stages.sh', '--stage', '2', '--run-root', str(root)],
                                cwd=os_root, env=env, text=True, capture_output=True)
        assert result.returncode == 2, result.stderr
        admission = json.loads((root / 'stage2-admission.json').read_text())
        assert admission['live_memory']['deterministic_is_substitute'] is False
        assert admission['live_memory']['status'] == 'implemented_not_run'
        assert 'live_memory_runner_missing' not in admission['blocking_reasons']
        assert admission['cross_agent_memory']['status'] == 'blocked'
        assert admission['codeact_off']['status'] == 'not_applicable' and not admission['codeact_off']['blocking']
        assert not (root / 'preflight.log').exists()


@pytest.mark.parametrize('profile,model_gpu', [('qwen3-32b-gpu2-u050', '2'), ('qwen3-8b-gpu0-u050', '0')])
def test_campaign_dry_run_resolves_profiles_after_host_activation(profile, model_gpu):
    os_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(['bash', 'scripts/run_contest_measurement_stages.sh', '--stage', '1',
                             '--profile', profile, '--dry-run'], cwd=os_root, text=True, capture_output=True,
                            env=dict(os.environ, STATEBUS_EMBED_DEVICE='auto'))
    assert result.returncode == 0, result.stderr
    assert f'model_gpu={model_gpu} embedding_gpu=1' in result.stdout
    assert '--embedding-device cuda:0' in result.stdout and '/statebus_host/bin/python' in result.stdout
    assert result.stdout.count('-m statebus.benchmark.contest_stage1 ') == 3


def test_campaign_rejects_cpu_and_preflight_startup_conflict():
    os_root = Path(__file__).resolve().parents[2]
    command = ['bash', 'scripts/run_contest_measurement_stages.sh', '--stage', '1']
    cpu = subprocess.run(command + ['--dry-run'], cwd=os_root, text=True, capture_output=True,
                         env=dict(os.environ, STATEBUS_EMBED_DEVICE='cpu'))
    assert cpu.returncode == 2 and 'requires cuda:0' in cpu.stderr
    conflict = subprocess.run(command + ['--preflight-only', '--start-services'], cwd=os_root, text=True, capture_output=True,
                              env=dict(os.environ, STATEBUS_EMBED_DEVICE='auto'))
    assert conflict.returncode == 2 and 'cannot start services' in conflict.stderr


@pytest.mark.skipif(shutil.which('jq') is None, reason='Host shell orchestration requires jq')
@pytest.mark.parametrize('failure', ['runner', 'gate', 'none', 'unsafe_start', 'main', 'main_failed', 'main_incomplete'])
def test_campaign_audits_failures_and_stops_before_next_batch(tmp_path, failure):
    """Use only fake services; exercise the real orchestration control flow."""
    os_root = Path(__file__).resolve().parents[2]
    scripts = tmp_path / 'scripts'
    (scripts / 'vllm').mkdir(parents=True)
    (tmp_path / 'statebus').mkdir()
    (tmp_path / 'deploy').mkdir()
    shutil.copyfile(os_root / 'scripts/run_contest_measurement_stages.sh', scripts / 'run_contest_measurement_stages.sh')

    def executable(path, content):
        path.write_text(content)
        path.chmod(0o755)

    executable(scripts / 'start_statebus.sh', '''#!/bin/bash
printf '%s\n' 'export STATEBUS_VLLM_PROFILE=qwen3-32b-gpu2-u050' \
'export STATEBUS_VLLM_CUDA_VISIBLE_DEVICES=2' 'export STATEBUS_LOCAL_VLLM_HEALTH_URL=http://test/health' \
'export STATEBUS_LOCAL_VLLM_BASE_URL=http://test/v1' 'export STATEBUS_LOCAL_VLLM_MODEL=qwen3-32b' \
'export STATEBUS_VLLM_MAX_MODEL_LEN=8192' 'export STATEBUS_EMBED_MODEL_PATH=/test/model'
''')
    executable(scripts / 'vllm/manage_qwen3_32b.sh', '#!/bin/bash\nexit 0\n')
    executable(scripts / 'nvidia-smi', '#!/bin/bash\nprintf "GPU-test\\n"\n')
    executable(scripts / 'curl', '''#!/bin/bash
printf '%s\n' '{"data":[{"id":"qwen3-32b","max_model_len":8192}]}'
''')
    executable(scripts / 'run_g6b2_os_container.sh', f'#!{sys.executable}\n' + '''
import json, os, sys
from pathlib import Path
if sys.argv[1] == 'mount-mode':
    print('legacy-os-only'); sys.exit(0)
if sys.argv[1] == 'verify':
    sys.exit(0)
if sys.argv[1] == 'map-path':
    print(sys.argv[2]); sys.exit(0)
module = sys.argv[4].rsplit('.', 1)[-1]
def argument(name):
    return sys.argv[sys.argv.index(name) + 1]
if module == 'contest_preflight':
    sys.exit(0)
if module == 'contest_stage1' and '--dry-run' in sys.argv:
    Path(argument('--plan-output')).write_text(json.dumps({'planned_count': 4, 'embedding_device': 'cuda:0'}))
    sys.exit(0)
root = Path(argument('--output-root' if module == 'contest_stage1' else '--root'))
with Path(os.environ['TEST_CALLS']).open('a') as log:
    log.write(module + ':' + root.name + '\\n')
if '--main-chain' in sys.argv:
    assert root.name == 'main' and not root.exists()
    assert (root.parent / 'preflight.log').is_file()
    assert '--block-failed-chain' in sys.argv
    assert '--stop-on-failure' not in sys.argv
    root.mkdir()
    completed = os.environ['TEST_FAILURE'] == 'main'
    (root / 'summary.json').write_text(json.dumps(dict(planned_count=40, passed_count=40 if completed else 2,
        scope='main_chain_20_tasks', main_chain_completed=completed,
        chain_results=[dict(completed_ten_rounds=completed) for _ in range(4)])))
    sys.exit(1 if os.environ['TEST_FAILURE'] == 'main_failed' else 0)
root.mkdir(parents=True, exist_ok=True)
if module == 'contest_stage1':
    sys.exit(1 if os.environ['TEST_FAILURE'] == 'runner' else 0)
payload = {'ok': os.environ['TEST_FAILURE'] != 'gate', 'effective_configuration_hash': 'same', 'effective_budget': {}}
(root / 'acceptance.json').write_text(json.dumps(payload))
sys.exit(0 if payload['ok'] else 1)
''')
    calls = tmp_path / 'calls.txt'
    env = dict(os.environ, STATEBUS_EMBED_DEVICE='auto', TEST_CALLS=str(calls), TEST_FAILURE=failure,
               PATH=str(scripts) + os.pathsep + os.environ['PATH'])
    command = ['bash', str(scripts / 'run_contest_measurement_stages.sh'), '--stage', '3' if failure.startswith('main') else '1',
               '--run-root', str(tmp_path / 'runs/test')]
    if failure == 'unsafe_start':
        command.append('--start-services')
    result = subprocess.run(command, env=env, text=True, capture_output=True)
    if failure == 'unsafe_start':
        assert result.returncode == 2 and 'recreation is not authorized' in result.stderr
        assert not calls.exists()
        return
    observed = calls.read_text().splitlines()
    if failure.startswith('main'):
        assert observed == ['contest_stage1:main']
        assert result.returncode == (0 if failure == 'main' else 2), result.stderr
        assert (tmp_path / 'runs/test/main/summary.json').is_file()
        return
    expected = ['contest_stage1:sb-no-memory', 'contest_stage_gate:sb-no-memory']
    if failure == 'none':
        expected += ['contest_stage1:sb-full', 'contest_stage_gate:sb-full', 'contest_stage1:p-text', 'contest_stage_gate:p-text']
    assert observed == expected
    assert result.returncode == (0 if failure == 'none' else 2), result.stderr
    assert (tmp_path / 'runs/test/stage1/sb-no-memory/acceptance.json').exists()


@pytest.mark.parametrize('failure', ['failed', 'timeout'])
def test_rejected_batch_still_collects_every_task_and_failed_cost(tmp_path, failure):
    root = fixture_batch(tmp_path / 'batch', 'sb-no-memory')
    summary = json.loads((root / 'summary.json').read_text())
    summary['passed_count'] = 0
    for entry in summary['ledger']:
        entry.update(status=failure, ok=False, elapsed_ms=321.5, returncode=None if failure == 'timeout' else 1)
        path = Path(entry['result_path'])
        result = json.loads(path.read_text())
        result.update(ok=False, external_score_passed=False,
                      failure_classification={'error_code': 'report_body_rejected'})
        write_json(path, result)
        write_json(path.parent / 'execution/business-report-checks.json', [
            {'repair_index': 0, 'errors': ['report_risk:example']},
            {'repair_index': 1, 'errors': ['report_risk:example']}])
    write_json(root / 'summary.json', summary)
    # Missing scorer on one task must not hide its journal or the remaining tasks.
    (root / 'finance/SB-NO-MEMORY/F01/scorer.json').unlink()
    report = audit_stage1(root, 'sb-no-memory')
    assert not report['ok'] and len(report['tasks']) == 4
    assert all(not row['ok'] and row['provider']['usage']['total_tokens'] == 15 for row in report['tasks'])
    assert all(row['failure']['failure_classification']['error_code'] == 'report_body_rejected' for row in report['tasks'])
    assert all(len(row['report_checks']) == 2 for row in report['tasks'])
    assert report['costs']['provider_request_count'] == 4
    assert report['costs']['usage']['total_tokens'] == 60
    assert report['costs']['task_elapsed_ms_sum'] == 1286
    assert 'FileNotFoundError' in str(report['tasks'][0]['errors'])


def test_unresolved_failed_call_keeps_partial_cost_and_does_not_zero_usage(tmp_path):
    root = fixture_batch(tmp_path / 'batch', 'p-text')
    summary = json.loads((root / 'summary.json').read_text())
    entry = summary['ledger'][0]
    task = Path(entry['result_path']).parent
    append_event(task / 'provider.jsonl', dict(event='started', call_id='unsettled', role='executor'))
    entry.update(status='timeout', ok=False, provider=summarize_journal(task / 'provider.jsonl'))
    summary['passed_count'] = 3
    write_json(root / 'summary.json', summary)
    report = audit_stage1(root, 'p-text')
    assert not report['ok'] and len(report['tasks']) == 4
    assert report['tasks'][0]['usage_status'] == 'missing_explicit'
    assert report['costs']['provider_request_count'] is None
    assert report['costs']['observed_provider_request_count'] == 4
    assert report['costs']['usage']['total_tokens'] is None
    assert report['costs']['observed_usage_partial']['total_tokens'] == 60


def test_untrusted_ledger_result_path_is_not_followed(tmp_path):
    root = fixture_batch(tmp_path / 'batch', 'p-text')
    summary = json.loads((root / 'summary.json').read_text())
    summary['ledger'][0]['result_path'] = str(tmp_path / 'unrelated-private-file.json')
    write_json(root / 'summary.json', summary)
    report = audit_stage1(root, 'p-text')
    assert not report['ok'] and len(report['tasks']) == 4
    assert any('result_path' in e for e in report['tasks'][0]['errors'])
    assert report['costs']['usage']['total_tokens'] == 60


def test_corrupt_artifact_and_absent_journal_preserve_other_tasks(tmp_path):
    root = fixture_batch(tmp_path / 'batch', 'p-text')
    task = root / 'finance/P-TEXT/F01'
    (task / 'provider.jsonl').unlink()
    (task / 'effective-llm.yaml').write_text('invalid: [yaml')
    result = json.loads((task / 'result.json').read_text()); result['output_rows'] = [None]
    write_json(task / 'result.json', result)
    report = audit_stage1(root, 'p-text')
    assert not report['ok'] and len(report['tasks']) == 4
    assert report['costs']['usage']['total_tokens'] is None
    assert report['costs']['observed_usage_partial']['total_tokens'] == 45
    assert report['costs']['usage_missing_reason'] and report['costs']['missing_provider_task_ids'] == ['F01']
    assert all(row['provider']['usage']['total_tokens'] == 15 for row in report['tasks'][1:])

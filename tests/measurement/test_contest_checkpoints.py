"""Audit execution IDs do not alter business inputs, scores, or replay authority."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from statebus.benchmark import contest_stage1 as runner
from statebus.benchmark.adaptive_formal import _operation_semantics
from statebus.benchmark.contest_stage1_taskpack import generate_sealed, make_case, TASK_OPERATIONS
from statebus.benchmark.contest_stage1_scorer import reference_rows


@pytest.mark.parametrize('prefix', ['F', 'O'])
def test_checkpoint_preserves_business_identity_and_rejects_changed_inputs(tmp_path, prefix):
    sealed = tmp_path / 'sealed'
    generate_sealed(sealed)
    source, target = tmp_path / (prefix + '09'), tmp_path / (prefix + '11')
    for index in range(1, 10):
        for root in (source, target):
            runner.publish(sealed, root / 'public', f'{prefix}{index:02d}')
    original = make_case(source / 'public', prefix + '09')
    history = [dict(task_id=prefix + '09', ok=True, output_rows=reference_rows(source / 'public', prefix + '09'))]
    case, identity = runner.checkpoint_case(target, prefix + '11', history)
    assert case.task_id == prefix + '11'
    assert case.spec == original.spec and case.source_rows == original.source_rows
    assert case.operation_semantics == original.operation_semantics
    assert case.output_schema == original.output_schema
    assert identity['checkpoint_of'] == prefix + '09' and not identity['result_cache']
    with pytest.raises(ValueError, match='verified_producer'):
        runner.checkpoint_case(target, prefix + '11', [])
    bad = copy.deepcopy(history)
    bad[0]['output_rows'][0]['risk_change'] = 'forged'
    with pytest.raises(ValueError, match='failed_revalidation'):
        runner.checkpoint_case(target, prefix + '11', bad)
    # Raw published context is part of the recheck, not just the latest CSV.
    family = 'finance' if prefix == 'F' else 'service_ops'
    note = target / 'public' / family / ('notes_2026-06.md' if prefix == 'F' else 'events_W08.md')
    note.write_text(note.read_text().replace('## U-A', '## CHANGED') if prefix == 'F'
                    else note.read_text().replace('## S-A', '## CHANGED'))
    with pytest.raises(ValueError, match='checkpoint_input_or_contract_changed'):
        runner.checkpoint_case(target, prefix + '11', history)


@pytest.mark.parametrize('count', [1, 2])
def test_extended_runner_preserves_forty_slots_and_appends_rechecks(tmp_path, monkeypatch, count):
    commands = []
    class Worker:
        def __init__(self, command, **kwargs):
            commands.append(command)
            path = Path(command[command.index('--output-root') + 1])
            task = command[command.index('--task') + 1]
            history = json.loads((path / 'history-before.json').read_text())
            assert [h['task_id'] for h in history] == [f'{task[0]}{i:02d}' for i in range(1, int(task[1:]))]
            runner.write_json(path / 'result.json', dict(ok=True, output_rows=[], summary_text='offline fixture'))
        def wait(self, timeout=None): return 0
    monkeypatch.setattr(runner.subprocess, 'Popen', Worker)
    args = SimpleNamespace(output_root=tmp_path / 'run', family='all', profile='both', dry_run=False,
        main_chain=True, checkpoint_rounds=count, sb_memory_policy='validated_replay',
        embedding_model_path='unused', embedding_device='cpu')
    assert runner.run(args) == 0
    summary = json.loads((args.output_root / 'summary.json').read_text())
    assert summary['planned_count'] == summary['passed_count'] == 40 + 4 * count
    assert summary['base_campaign'] == dict(planned_count=40, passed_count=40)
    assert summary['main_chain_completed']
    assert all(c['completed_ten_rounds'] and c['completed_all_rounds'] for c in summary['chain_results'])
    assert len(summary['checkpoint_results']) == 4 * count
    assert len(commands) == 40 + 4 * count


def test_replay_requires_policy_consumption_quality_and_zero_requests():
    result = dict(ok=True, metrics=dict(executor_request_count=0),
        memory_query_results=[dict(compatibility_decisions=[dict(memory_id='memory', policy_approved=True)])],
        memory_consumption_records=[dict(memory_id='memory', recipe_step_status='skipped_generation',
            recipe_recomputed=True, replay_eligibility_receipt_hash='receipt')])
    assert runner.checkpoint_evidence(result)['positive_replay_observed']
    for change in (dict(ok=False), dict(metrics={}), dict(metrics=dict(executor_request_count=1)),
                   dict(memory_consumption_records=[]), dict(memory_query_results=[])):
        assert not runner.checkpoint_evidence({**result, **change})['positive_replay_observed']


def test_period_contract_scopes_risk_change_across_periods_and_preserves_key_case():
    for op in ('finance_quarterly_review', 'service_sequence_review'):
        semantic = _operation_semantics(op, dict(current_period='NOW', previous_period='BEFORE'))
        assert 'risk_change, and' not in semantic['formula']
        assert 'risk_change compares current_period risk against previous_period risk' in semantic['formula']
        assert 'period keys' in semantic['executor_invariants']
    from statebus.benchmark.contest_stage1_text import EXTENDED_OPERATIONS
    assert TASK_OPERATIONS['F08'] in EXTENDED_OPERATIONS
    assert TASK_OPERATIONS['F09'] in EXTENDED_OPERATIONS


def test_keyerror_repair_guidance_is_generic_and_diagnostic_scoped():
    from statebus.runtime.llm_codeact import build_code_repair_guidance
    from statebus.contracts import CodeGenerationPolicy
    policy = CodeGenerationPolicy(capability_id='execute_bounded_python_v2')
    guidance = build_code_repair_guidance(("runtime_error:KeyError: 'W01'",), policy)
    assert 'SAME key type and case' in guidance and 'boolean keys' in guidance
    assert 'W01' not in guidance and 'O03' not in guidance
    assert 'key type' not in build_code_repair_guidance(('runtime_error:ZeroDivisionError',), policy)

"""Prompt-39 contracts, release/history binding, and full Runtime chains."""
from dataclasses import replace
import json
from pathlib import Path
import subprocess

import pytest

from statebus.benchmark import contest_dsl_mainline as runner
from statebus.benchmark.contest_dsl_taskpack import (
    SIMPLE_PROFILE, bind_inputs, generate_sealed, release_task, task_contract, tasks_for_family,
)
from statebus.benchmark.contest_dsl_fixtures import offline_program
from statebus.benchmark.contest_dsl_scorer import score_rows
from statebus.runtime.transform_dsl import TransformDslInterpreter


def prepare_chain(root, family):
    sealed, public = root / 'sealed', root / 'public'
    generate_sealed(sealed, profile=SIMPLE_PROFILE)
    history = {}
    for task in tasks_for_family(family, profile=SIMPLE_PROFILE):
        release_task(sealed, public, task.task_id, profile=SIMPLE_PROFILE)
        inputs = bind_inputs(public, task.task_id, history=history, profile=SIMPLE_PROFILE)
        refs = {name: 'source:' + name for name in inputs}
        program = offline_program(task, refs)
        rows = TransformDslInterpreter().run(program, inputs={refs[k]: v for k, v in inputs.items()})
        scored = score_rows(public, task.task_id, rows, profile=SIMPLE_PROFILE)
        assert scored['passed'], (task.task_id, scored)
        assert 2 <= len(program.operations) <= 5
        damaged = [dict(row) for row in rows]
        field = next(k for k, v in task.output_schema.items() if v == 'number')
        damaged[0][field] += 1
        assert not score_rows(public, task.task_id, damaged, profile=SIMPLE_PROFILE)['passed']
        history[task.task_id] = rows
    return public, history


@pytest.mark.parametrize('family', ['finance', 'service_ops'])
def test_all_simple_contracts_independent_scorer_and_real_history(tmp_path, family):
    public, history = prepare_chain(tmp_path, family)
    prefix = 'F' if family == 'finance' else 'O'
    metric = 'revenue_cny' if family == 'finance' else 'failed_count'
    for number in (3, 4, 5, 10, 12):
        task_id = f'{prefix}{number:02}'
        contract = task_contract(task_id, profile=SIMPLE_PROFILE)
        missing = dict(history)
        missing.pop(contract.required_history[0])
        with pytest.raises(ValueError, match='verified_history_missing'):
            bind_inputs(public, task_id, history=missing, profile=SIMPLE_PROFILE)
        altered = {k: [dict(r) for r in rows] for k, rows in history.items()}
        altered[contract.required_history[0]][0][metric] += 9
        before = bind_inputs(public, task_id, history=history, profile=SIMPLE_PROFILE)
        after = bind_inputs(public, task_id, history=altered, profile=SIMPLE_PROFILE)
        assert before != after  # Binding consumes observed values, not scorer/gold.
    total = history[prefix + '10']
    assert all(row['period_count'] == (6 if prefix == 'F' else 8) for row in total)
    for number in (8, 9, 11):
        task = task_contract(f'{prefix}{number:02}', profile=SIMPLE_PROFILE)
        assert task.method == task_contract(prefix + '08', profile=SIMPLE_PROFILE).method
        assert task.input_schemas == task_contract(prefix + '08', profile=SIMPLE_PROFILE).input_schemas
        assert task.output_contract_version == task_contract(prefix + '08', profile=SIMPLE_PROFILE).output_contract_version
        assert not any('latency_samples' in name for name in task.required_files)
    # Semantic v1/v2 contract differences cannot silently replay across the change.
    assert task_contract(prefix+'01', profile=SIMPLE_PROFILE).output_contract_version != task_contract(prefix+'06', profile=SIMPLE_PROFILE).output_contract_version


def test_simple_plan_freeze_release_and_final_failure_mapping(tmp_path):
    sealed, public = tmp_path / 'sealed', tmp_path / 'public'
    generate_sealed(sealed, profile=SIMPLE_PROFILE)
    other = tmp_path / 'other'
    generate_sealed(other, profile=SIMPLE_PROFILE)
    assert (sealed / 'service_ops/plan_W07.csv').read_bytes() == (other / 'service_ops/plan_W07.csv').read_bytes()
    assert (sealed / 'service_ops/plan_W08.csv').read_bytes() == (other / 'service_ops/plan_W08.csv').read_bytes()
    for task in tasks_for_family('service_ops', profile=SIMPLE_PROFILE)[:8]:
        release_task(sealed, public, task.task_id, profile=SIMPLE_PROFILE)
        if task.round < 8:
            assert not (public / 'service_ops/plan_W07.csv').exists()
    tables = bind_inputs(public, 'O08', profile=SIMPLE_PROFILE)
    assert set(tables) == {'source', 'plans'}
    import csv
    with (public / 'service_ops/hourly_W07.csv').open() as file:
        raw = list(csv.DictReader(file))
    assert sum(r['failed_count'] for r in tables['source']) == sum(int(r['final_failed_request_count']) for r in raw)
    assert sum(r['failed_count'] for r in tables['source']) != sum(int(r['failed_attempt_count']) for r in raw)


@pytest.mark.parametrize('family', ['finance', 'service_ops'])
@pytest.mark.parametrize('variant', ['SB-FULL', 'P-TEXT'])
def test_full_12_round_runtime_simple_chain(tmp_path, family, variant):
    output = tmp_path / f'{family}-{variant}'
    summary = runner.run_chain(output, family=family, variant=variant, rounds=12, mode='offline', profile=SIMPLE_PROFILE)
    ledger = json.loads((output / 'ledger.json').read_text())
    assert len(ledger) == summary['aggregate']['passed_count'] == 12, [(r['task_id'], r['status'], r.get('error'), r.get('failure_codes')) for r in ledger]
    assert all(row['metrics']['provider_request_count'] == 0 for row in ledger)
    prefix = 'F' if family == 'finance' else 'O'
    if variant == 'SB-FULL':
        assert ledger[10]['metrics']['executor_generation_count'] == 0
        witness = json.loads((output / f'slots/{prefix}12/r12-memory-cross-check.json').read_text())
        assert witness['producer_agent'] != witness['consumer_agent']
        assert witness['source_task_id'] == prefix+'10'
        assert witness['values_match'] is True
        memory = [json.loads(line) for line in (output / f'slots/{prefix}11/memory-events.jsonl').read_text().splitlines()]
        assert any(e.get('input_recomputed') and e.get('consume_receipt') for e in memory)
        state = [json.loads(line) for line in (output / f'slots/{prefix}01/state-events.jsonl').read_text().splitlines()]
        assert {e['event'] for e in state} == {'publish', 'transfer', 'consume', 'release'}
        consume = next(e for e in state if e['event'] == 'consume')
        assert consume['producer_pid'] != consume['consumer_pid']
        assert consume['read_bytes'] > 0
    readiness = json.loads((output / 'readiness.json').read_text())
    assert readiness['continuous_12_completed'] is True
    assert readiness['continuous_12_live_passed'] is False


@pytest.mark.parametrize(
    ('family', 'failed_task', 'blocked_tasks', 'successful_tasks'),
    [
        ('finance', 'F03', ('F10', 'F12'), ('F01', 'F02', 'F04', 'F05', 'F06', 'F07', 'F08', 'F09', 'F11')),
        ('service_ops', 'O03', ('O05', 'O10', 'O12'), ('O01', 'O02', 'O04', 'O06', 'O07', 'O08', 'O09', 'O11')),
    ],
)
def test_simple_failure_blocks_only_declared_dependents(
    tmp_path, monkeypatch, family, failed_task, blocked_tasks, successful_tasks,
):
    def fail(*args, **kwargs):
        task_id = args[2]
        if task_id == failed_task:
            raise ValueError('deliberate_binding_failure')
        from statebus.benchmark.contest_dsl_fixtures import offline_program
        from statebus.runtime.transform_dsl import TransformDslInterpreter
        task = task_contract(task_id, profile=SIMPLE_PROFILE)
        history = kwargs['history']
        public = args[1]
        inputs = bind_inputs(public, task_id, history=history, profile=SIMPLE_PROFILE)
        refs = {name: 'source:' + name for name in inputs}
        return {
            'status': 'success', 'quality': True, 'business_quality': True,
            'mechanism_gate_passed': True, 'returncode': 0, 'repair': 0,
            'metrics': {'provider_request_count': 0, 'executor_generation_count': 0,
                        'executor_repair_count': 0},
            'failure_codes': [], 'scorer_errors': [],
            'rows': TransformDslInterpreter().run(
                offline_program(task, refs),
                inputs={refs[key]: value for key, value in inputs.items()},
            ),
        }
    monkeypatch.setattr(runner, 'run_slot', fail)
    root = tmp_path / family
    runner.run_chain(root, family=family, variant='SB-FULL', rounds=12, profile=SIMPLE_PROFILE)
    rows = json.loads((root / 'ledger.json').read_text())
    statuses = {row['task_id']: row['status'] for row in rows}
    assert statuses[failed_task] == 'runtime_fail'
    assert all(statuses[task_id] == 'success' for task_id in successful_tasks)
    assert all(statuses[task_id] == 'blocked' for task_id in blocked_tasks)
    blocked_rows = {row['task_id']: row for row in rows if row['status'] == 'blocked'}
    assert blocked_rows[blocked_tasks[0]]['blocked_reason'].startswith(
        f'blocked_by_dependency:{failed_task}:runtime_fail'
    )


def test_wrapper_dry_run_defaults_to_two_live_twelve_round_chains():
    script = Path(__file__).resolve().parents[2] / 'scripts/run_contest_dsl_mainchains.sh'
    result = subprocess.run(['bash', str(script), '--dry-run'], check=True, text=True, capture_output=True)
    text = result.stdout
    assert text.count('COMMAND=docker exec ') == 2
    assert text.count('"rounds": 12') == 2
    assert text.count('"mode": "live"') == 2
    assert text.count('"profile": "mechanism_simple_v2"') == 2
    assert text.count('"provider_timeout_s": 480.0') == 2
    assert '"task_id": "F12"' in text and '"task_id": "O12"' in text


def test_contest_live_provider_timeout_is_explicit_and_no_retry(monkeypatch, tmp_path):
    import statebus.integrations.llm as llm

    captured = {}

    def build(config):
        captured['config'] = config
        return object()

    monkeypatch.setattr(llm, 'build_llm_client', build)
    runner._live_client(tmp_path / 'provider.jsonl', 'qwen3-32b', 'http://127.0.0.1:53334/v1', 8192)
    provider = captured['config'].providers['default']
    assert provider.timeout_s == 480.0
    assert provider.request_max_attempts == 1
    assert captured['config'].role_config('executor').max_tokens == 3072
    assert captured['config'].role_config('summarizer').max_tokens == 1536
    with pytest.raises(ValueError, match='provider_timeout_s_must_be_positive'):
        runner._live_client(tmp_path / 'bad.jsonl', 'qwen3-32b', 'http://127.0.0.1:53334/v1', 8192, 0)


def test_openai_provider_timeout_is_recorded_as_timeout():
    import httpx
    from openai import APITimeoutError

    assert runner._is_timeout_error(APITimeoutError(request=httpx.Request('POST', 'http://127.0.0.1')))
    assert runner._is_timeout_error(TimeoutError('transport timeout'))
    assert not runner._is_timeout_error(ValueError('dsl failure'))


def test_provider_json_rejects_length_terminated_structured_output():
    from types import SimpleNamespace

    class Client:
        async def complete(self, messages, *, purpose, **kwargs):
            return SimpleNamespace(text='{"partial": true}', finish_reason='length')

    with pytest.raises(ValueError, match='provider_output_truncated:executor:finish_reason=length'):
        runner._provider_json(Client(), 'executor', {}, 'Return JSON')


def test_repair_guidance_requires_final_select_and_budget_reservation():
    details = runner._repair_error_details(['schema:0:missing=:unexpected=gross_cny'])
    assert 'final operation must be select' in details[0]
    assert 'Reserve one operation slot' in details[0]


def test_repair_guidance_preserves_unlisted_valid_program_parts():
    details = runner._repair_error_details(['derive_output_collision:1'])
    assert 'Preserve all unlisted valid operations' in details[0]
    assert 'explicit reference_updates' in details[0]


def test_repair_feedback_compacts_equivalent_row_index_errors():
    errors = (
        'schema:0:missing=:unexpected=gross_cny,refund_cny',
        'schema:1:missing=:unexpected=gross_cny,refund_cny',
        'schema:2:missing=:unexpected=gross_cny,refund_cny',
        'value:0:revenue_cny',
        'value:1:revenue_cny',
    )
    assert runner._compact_repair_errors(errors) == (
        'schema:0:missing=:unexpected=gross_cny,refund_cny',
        'value:0:revenue_cny',
    )
    assert len(runner._repair_error_details(errors)) == 2


def test_wrapper_preserves_failure_and_starts_independent_family(tmp_path):
    """Mock external commands only; no live calls or canonical business scores."""
    import os
    import shutil
    root = tmp_path / 'repo'
    (root / 'scripts').mkdir(parents=True)
    actual = Path(__file__).resolve().parents[2] / 'scripts'
    for name in ('run_contest_dsl_mainchains.sh', 'show_contest_dsl_results.py'):
        shutil.copyfile(actual / name, root / 'scripts' / name)
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    stubs = {
        'nvidia-smi': '#!/bin/bash\necho GPU-test\n',
        'curl': '#!/bin/bash\necho \'{"data":[{"id":"qwen3-32b","root":"/data/models/Qwen3-32B","max_model_len":8192}]}\'\n',
        'docker': '''#!/bin/bash
if [[ "$1" == inspect ]]; then echo running; exit 0; fi
if [[ "$*" == *contest_preflight* ]]; then exit 0; fi
printf '%s\\n' "$*" >> "$TEST_CALLS"
if [[ "$*" == *"--family finance"* ]]; then exit 7; fi
exit 0
''',
    }
    for name, content in stubs.items():
        target = bin_dir / name
        target.write_text(content)
        target.chmod(0o755)
    calls = tmp_path / 'calls'
    output = root / 'runs/test'
    result = subprocess.run(['bash', str(root / 'scripts/run_contest_dsl_mainchains.sh'), '--output', str(output)],
        env={**os.environ, 'PATH': f'{bin_dir}:{os.environ["PATH"]}', 'TEST_CALLS': str(calls)}, capture_output=True, text=True)
    assert result.returncode == 1, result.stderr
    assert (output / 'chain-exit-codes.tsv').read_text().splitlines() == ['family\treturncode', 'finance\t7', 'service_ops\t0']
    lines = calls.read_text().splitlines()
    assert len(lines) == 2
    assert '--family finance' in lines[0] and '--family service_ops' in lines[1]
    assert all('--rounds 12 --mode live' in line for line in lines)
    assert not any('--mode offline' in line for line in lines)


def test_scorer_schema_repair_identifies_missing_and_unexpected_names(tmp_path):
    generate_sealed(tmp_path / 'sealed', profile=SIMPLE_PROFILE)
    release_task(tmp_path / 'sealed', tmp_path / 'public', 'F01', profile=SIMPLE_PROFILE)
    task = task_contract('F01', profile=SIMPLE_PROFILE)
    tables = bind_inputs(tmp_path / 'public', 'F01', profile=SIMPLE_PROFILE)
    program = offline_program(task, {'source': 'source'})
    rows = TransformDslInterpreter().run(program, inputs=tables)
    for row in rows:
        row['sum_cost_cny'] = row.pop('cost_cny')
    scored = score_rows(tmp_path / 'public', 'F01', rows, profile=SIMPLE_PROFILE)
    assert not scored['passed']
    assert scored['errors'][0] == 'schema:0:missing=cost_cny:unexpected=sum_cost_cny'
    assert 'select projects existing names' in runner._repair_error_details(scored['errors'])[0]


def test_live_repair_context_exposes_finance_missing_aggregate_name():
    from statebus.contracts import TransformProgram, TransformStep

    task = task_contract('F02', profile=SIMPLE_PROFILE)
    program = TransformProgram('model-program', ('source',), (
        TransformStep('aggregate_grouped', {'group_fields': ['period', 'unit_id'],
            'value_fields': ['gross_cny', 'refund_cny', 'cost_cny'],
            'functions': ['sum', 'sum', 'sum'],
            'outputs': ['sum_gross_cny', 'sum_refund_cny', 'sum_cost_cny']}),
        TransformStep('derive_safe', {'calculations': [
            ['revenue_cny', 'difference', 'sum_gross_cny', 'sum_refund_cny'],
            ['profit_cny', 'difference', 'revenue_cny', 'sum_cost_cny']]}),
        TransformStep('select', {'columns': ['period', 'unit_id', 'sum_cost_cny', 'revenue_cny', 'profit_cny']}),
    ), task.output_contract_version)
    constraints = runner._repair_constraints(program, task.input_schemas, task.output_schema,
        ['schema:0:missing=cost_cny:unexpected=sum_cost_cny'])
    assert constraints['missing_final_columns'] == ['cost_cny']
    assert constraints['unexpected_final_columns'] == ['sum_cost_cny']
    assert constraints['aggregate_output_name_constraints'] == [
        {'operation_index': 0, 'value_field': 'cost_cny', 'function': 'sum',
         'current_output': 'sum_cost_cny', 'required_final_name': 'cost_cny',
         'matches_required_final_name': False},
    ]
    assert constraints['required_aggregate_renames'] == [{
        'operation_index': 0,
        'from': 'sum_cost_cny',
        'to': 'cost_cny',
        'value_field': 'cost_cny',
        'function': 'sum',
        'action': 'rename_existing_output_in_place',
        'update_downstream_references': True,
        'do_not_append_parallel_entry': True,
    }]
    assert 'cost_cny' in constraints['column_trace'][0]['input_columns']
    assert 'sum_cost_cny' in constraints['column_trace'][0]['output_columns']
    assert 'cost_cny' not in constraints['column_trace'][0]['output_columns']


def test_live_repair_context_identifies_missing_column_after_aggregation():
    from statebus.contracts import TransformProgram, TransformStep

    schemas = {'source': {'period': 'string', 'region': 'string', 'amount': 'number'}}
    program = TransformProgram('candidate', ('source',), (
        TransformStep('aggregate_grouped', {'group_fields': ['period', 'region'],
            'value_fields': ['amount'], 'functions': ['sum'], 'outputs': ['total_amount']}),
        TransformStep('select', {'columns': ['period', 'region', 'amount']}),
    ), 'generic-contract')
    constraints = runner._repair_constraints(program, schemas, {'period': 'string', 'amount': 'number'},
        ['unknown_column:1'])
    assert constraints['column_trace'][1]['error'] == 'unknown_column'
    assert constraints['missing_referenced_columns'] == ['amount']
    assert 'do not append a duplicate aggregate entry' in runner._repair_error_details(['unknown_column:1'])[0]


def test_grouped_repair_completion_is_contract_bounded_and_keeps_sb_valid_programs_untouched():
    from statebus.contracts import TransformProgram, TransformStep

    task = task_contract('O07', profile=SIMPLE_PROFILE)
    previous = TransformProgram('previous', ('source:source',), (
        TransformStep('aggregate_grouped', {
            'group_field': 'period', 'value_field': 'request_count',
            'functions': ['sum'], 'outputs': ['request_count'],
        }),
        TransformStep('aggregate_grouped', {
            'group_field': 'site_id', 'value_field': 'request_count',
            'functions': ['sum'], 'outputs': ['request_count'],
        }),
        TransformStep('aggregate_grouped', {
            'group_field': 'period', 'value_field': 'failed_count',
            'functions': ['sum'], 'outputs': ['failed_count'],
        }),
        TransformStep('aggregate_grouped', {
            'group_field': 'site_id', 'value_field': 'failed_count',
            'functions': ['sum'], 'outputs': ['failed_count'],
        }),
        TransformStep('select', {'columns': list(task.output_schema)}),
    ), task.output_contract_version)
    candidate = TransformProgram('candidate', ('source:source',), (
        TransformStep('aggregate_grouped', {
            'group_fields': ['period', 'site_id'],
            'value_fields': ['request_count', 'failed_count', 'request_count', 'failed_count'],
            'functions': ['sum', 'sum', 'count', 'count'],
            'outputs': ['request_count', 'failed_count', 'request_count_count', 'failed_count_count'],
        }),
    ), task.output_contract_version)
    completed = runner._complete_grouped_repair_candidate(
        candidate, previous, task.input_schemas, task.output_schema,
        ['invalid_grouped_aggregate_arguments:0'],
    )
    assert completed is not None
    assert [step.op for step in completed.operations] == ['aggregate_grouped', 'select']
    assert completed.operations[0].arguments['outputs'] == ['request_count', 'failed_count']
    assert completed.operations[-1].arguments['columns'] == list(task.output_schema)

    valid = TransformProgram('valid', ('source:source',), (
        TransformStep('aggregate_grouped', {
            'group_fields': ['period', 'site_id'],
            'value_fields': ['request_count', 'failed_count'],
            'functions': ['sum', 'sum'],
            'outputs': ['request_count', 'failed_count'],
        }),
        TransformStep('sort', {'columns': ['period', 'site_id']}),
        TransformStep('select', {'columns': list(task.output_schema)}),
    ), task.output_contract_version)
    assert runner._complete_grouped_repair_candidate(
        valid, valid, task.input_schemas, task.output_schema,
        ['invalid_grouped_aggregate_arguments:0'],
    ) is None


def test_live_repair_context_turns_final_aggregate_name_mismatch_into_in_place_action():
    from statebus.contracts import TransformProgram, TransformStep

    task = task_contract('F03', profile=SIMPLE_PROFILE)
    program = TransformProgram('candidate', ('source', 'history'), (
        TransformStep('aggregate_grouped', {
            'group_fields': ['period', 'unit_id'],
            'value_fields': ['gross_cny', 'refund_cny', 'cost_cny'],
            'functions': ['sum', 'sum', 'sum'],
            'outputs': ['gross_sum', 'refund_sum', 'cost_sum'],
        }),
        TransformStep('derive_safe', {'calculations': [
            ['revenue_cny', 'difference', 'gross_sum', 'refund_sum'],
            ['profit_cny', 'difference', 'revenue_cny', 'cost_sum'],
        ]}),
        TransformStep('join_by_key', {
            'right_ref': 'history', 'left_keys': ['unit_id'], 'right_keys': ['unit_id'],
        }),
        TransformStep('sort', {'columns': ['period', 'unit_id']}),
        TransformStep('select', {'columns': [
            'period', 'unit_id', 'revenue_cny', 'profit_cny', 'cost_cny',
            'period1_revenue_cny', 'period2_revenue_cny',
        ]}),
    ), task.output_contract_version)
    constraints = runner._repair_constraints(
        program, task.input_schemas, task.output_schema, ['unknown_column:4'])
    assert constraints['missing_referenced_columns'] == ['cost_cny']
    assert constraints['required_aggregate_renames'] == [{
        'operation_index': 0,
        'from': 'cost_sum',
        'to': 'cost_cny',
        'value_field': 'cost_cny',
        'function': 'sum',
        'action': 'rename_existing_output_in_place',
        'update_downstream_references': True,
        'do_not_append_parallel_entry': True,
    }]


def test_live_repair_context_identifies_duplicate_aggregate_outputs_without_weakening_validation():
    from statebus.contracts import TransformProgram, TransformStep
    from statebus.runtime.transform_dsl import TransformProgramValidator

    schemas = {'source': {'region': 'string', 'amount': 'number', 'fee': 'number'}}
    program = TransformProgram('candidate', ('source',), (
        TransformStep('aggregate_grouped', {'group_fields': ['region'],
            'value_fields': ['amount', 'fee', 'amount'], 'functions': ['sum', 'sum', 'sum'],
            'outputs': ['total', 'fee_total', 'total']}),
    ), 'generic-contract')
    report = TransformProgramValidator().validate(program, authorized_input_refs=('source',),
        available_columns={'source': tuple(schemas['source'])})
    assert not report.ok and report.error_code == 'invalid_aggregate_outputs' and report.operation_index == 0
    constraints = runner._repair_constraints(program, schemas, {'total': 'number'},
        ['invalid_aggregate_outputs:0'])
    assert constraints['aggregate_output_issues'] == {
        'operation_index': 0, 'value_field_count': 3, 'function_count': 3, 'output_count': 3,
        'duplicate_outputs': [{'name': 'total', 'positions': [0, 2]}],
        'duplicate_entries': [
            {'position': 0, 'value_field': 'amount', 'function': 'sum', 'output': 'total',
             'same_as_first_position': False},
            {'position': 2, 'value_field': 'amount', 'function': 'sum', 'output': 'total',
             'same_as_first_position': True},
        ],
    }
    assert 'delete the redundant position from all three parallel arrays' in runner._repair_error_details(
        ['invalid_aggregate_outputs:0'])[0]


def test_live_repair_context_emits_only_semantics_preserving_duplicate_deletes():
    from statebus.contracts import TransformProgram, TransformStep

    task = task_contract('F08', profile=SIMPLE_PROFILE)
    program = TransformProgram('candidate', ('source', 'budgets'), (
        TransformStep('aggregate_grouped', {
            'group_fields': ['period', 'unit_id'],
            'value_fields': ['gross_cny', 'refund_cny', 'cost_cny', 'gross_cny', 'refund_cny', 'cost_cny'],
            'functions': ['sum', 'sum', 'sum', 'sum', 'sum', 'count'],
            'outputs': ['sum_gross_cny', 'sum_refund_cny', 'cost_cny', 'sum_gross_cny', 'sum_refund_cny', 'count_rows'],
        }),
        TransformStep('select', {'columns': list(task.output_schema)}),
    ), task.output_contract_version)
    constraints = runner._repair_constraints(
        program, task.input_schemas, task.output_schema, ['invalid_aggregate_outputs:0'])
    deletes = [edit for edit in constraints['required_program_edits']
               if edit['kind'] == 'delete_parallel_array_position'
               and edit.get('reason') == 'duplicate_aggregate_output_same_semantics']
    assert [edit['position'] for edit in deletes] == [4, 3]
    assert all(edit['update_downstream_references'] is False for edit in deletes)


def test_live_repair_context_emits_unambiguous_in_place_aggregate_edit():
    from statebus.contracts import TransformProgram, TransformStep

    task = task_contract('F03', profile=SIMPLE_PROFILE)
    program = TransformProgram('candidate', ('source', 'history'), (
        TransformStep('aggregate_grouped', {
            'group_fields': ['period', 'unit_id'],
            'value_fields': ['gross_cny', 'refund_cny', 'cost_cny'],
            'functions': ['sum', 'sum', 'sum'],
            'outputs': ['revenue_cny_unadjusted', 'refund_cny_sum', 'cost_cny_sum'],
        }),
        TransformStep('derive_safe', {'calculations': [
            ['revenue_cny', 'difference', 'revenue_cny_unadjusted', 'refund_cny_sum'],
            ['profit_cny', 'difference', 'revenue_cny', 'cost_cny_sum'],
        ]}),
        TransformStep('join_by_key', {
            'right_ref': 'history', 'left_keys': ['unit_id'], 'right_keys': ['unit_id'],
        }),
        TransformStep('sort', {'columns': ['period', 'unit_id']}),
        TransformStep('select', {'columns': [
            'period', 'unit_id', 'revenue_cny', 'profit_cny', 'cost_cny',
            'period1_revenue_cny', 'period2_revenue_cny',
        ]}),
    ), task.output_contract_version)
    constraints = runner._repair_constraints(
        program, task.input_schemas, task.output_schema, ['unknown_column:4'])
    assert constraints['required_program_edits'] == [{
        'kind': 'replace_parallel_array_value',
        'operation_index': 0,
        'array': 'outputs',
        'position': 2,
        'from': 'cost_cny_sum',
        'to': 'cost_cny',
        'update_downstream_references': True,
        'reference_updates': [{
            'operation_index': 1,
            'path': ['arguments', 'calculations', 1, 3],
            'from': 'cost_cny_sum',
            'to': 'cost_cny',
        }],
        'do_not_append_parallel_entry': True,
        'preserve_parallel_array_lengths': True,
    }]


def test_live_repair_context_handles_misaligned_aggregate_arrays_without_crashing():
    from statebus.contracts import TransformProgram, TransformStep
    from statebus.runtime.transform_dsl import TransformProgramValidator

    schemas = {'source': {'region': 'string', 'amount': 'number', 'fee': 'number'}}
    program = TransformProgram('candidate', ('source',), (
        TransformStep('aggregate_grouped', {
            'group_fields': ['region'],
            'value_fields': ['amount', 'fee'],
            'functions': ['sum'],
            'outputs': ['total', 'fee_total'],
        }),
    ), 'generic-contract')
    report = TransformProgramValidator().validate(
        program, authorized_input_refs=('source',), available_columns={'source': tuple(schemas['source'])})
    assert not report.ok and report.error_code == 'invalid_aggregate_functions'
    constraints = runner._repair_constraints(
        program, schemas, {'total': 'number'}, [f'{report.error_code}:0'])
    issues = constraints['aggregate_output_issues']
    assert issues['validation_error'] == 'invalid_aggregate_functions'
    assert issues['parallel_array_lengths'] == {
        'value_fields': 2, 'functions': 1, 'outputs': 2,
    }
    assert issues['parallel_array_length_mismatch'] is True
    assert issues['duplicate_entries'] == []


def test_live_repair_context_respects_prior_derived_column_in_same_batch():
    from statebus.contracts import TransformProgram, TransformStep

    schemas = {'source': {'amount': 'number', 'fee': 'number'}}
    program = TransformProgram('candidate', ('source',), (
        TransformStep('derive_safe', {'calculations': [
            ['net', 'difference', 'amount', 'fee'],
            ['margin', 'ratio', 'net', 'missing_denominator']]}),
    ), 'generic-contract')
    constraints = runner._repair_constraints(program, schemas, {'margin': 'number'}, ['unknown_column:0'])
    assert constraints['missing_referenced_columns'] == ['missing_denominator']


def test_live_repair_context_exposes_derive_collision_origin_without_task_special_case():
    from statebus.contracts import TransformProgram, TransformStep

    task = task_contract('F01', profile=SIMPLE_PROFILE)
    program = TransformProgram('model-program', ('source',), (
        TransformStep('aggregate_grouped', {'group_fields': ['period', 'unit_id'],
            'value_fields': ['gross_cny', 'refund_cny', 'cost_cny', 'gross_cny', 'cost_cny'],
            'functions': ['sum', 'sum', 'sum', 'sum', 'sum'],
            'outputs': ['gross_cny', 'refund_cny', 'cost_cny', 'revenue_cny', 'profit_cny']}),
        TransformStep('derive_safe', {'calculations': [
            ['revenue_cny', 'difference', 'gross_cny', 'refund_cny'],
            ['profit_cny', 'difference', 'revenue_cny', 'cost_cny']]}),
    ), task.output_contract_version)
    constraints = runner._repair_constraints(program, task.input_schemas, task.output_schema,
        ['derive_output_collision:1'])
    assert constraints['colliding_derive_outputs'] == [
        {'operation_index': 1, 'calculation_index': 0, 'output': 'revenue_cny',
         'prior_declaration': {'operation_index': 0, 'op': 'aggregate_grouped'}},
        {'operation_index': 1, 'calculation_index': 1, 'output': 'profit_cny',
         'prior_declaration': {'operation_index': 0, 'op': 'aggregate_grouped'}},
    ]
    assert constraints['aggregate_output_name_constraints'] == []
    guidance = runner._repair_error_details(['derive_output_collision:1'])[0]
    assert 'colliding_derive_outputs' in guidance
    assert 'Changing the final select cannot fix' in guidance


def test_live_repair_context_emits_scoped_edit_for_derive_collision():
    from statebus.contracts import TransformProgram, TransformStep

    task = task_contract('F03', profile=SIMPLE_PROFILE)
    program = TransformProgram('model-program', ('source', 'history'), (
        TransformStep('aggregate_grouped', {
            'group_fields': ['period', 'unit_id'],
            'value_fields': ['gross_cny', 'refund_cny', 'cost_cny'],
            'functions': ['sum', 'sum', 'sum'],
            'outputs': ['revenue_cny', 'refund_cny', 'cost_cny'],
        }),
        TransformStep('derive_safe', {'calculations': [
            ['revenue_cny', 'difference', 'revenue_cny', 'refund_cny'],
            ['profit_cny', 'difference', 'revenue_cny', 'cost_cny'],
        ]}),
        TransformStep('join_by_key', {
            'right_ref': 'history', 'left_keys': ['unit_id'], 'right_keys': ['unit_id'],
        }),
        TransformStep('sort', {'columns': ['period', 'unit_id']}),
        TransformStep('select', {'columns': [
            'period', 'unit_id', 'budget_cny', 'budget_delta_cny', 'cost_cny_sum', 'revenue_cny', 'profit_cny',
        ]}),
    ), task.output_contract_version)
    constraints = runner._repair_constraints(
        program, task.input_schemas, task.output_schema, ['derive_output_collision:1'])
    edits = constraints['required_program_edits']
    assert edits[0]['kind'] == 'replace_parallel_array_value'
    assert edits[0]['position'] == 0
    assert edits[0]['from'] == 'revenue_cny'
    assert edits[0]['to'] == 'sum_gross_cny'
    assert edits[0]['reference_updates'] == [{
        'operation_index': 1,
        'path': ['arguments', 'calculations', 0, 2],
        'from': 'revenue_cny',
        'to': 'sum_gross_cny',
    }]


def test_live_repair_context_emits_delete_and_final_name_edits_for_duplicate_derives():
    from statebus.contracts import TransformProgram, TransformStep

    task = task_contract('F09', profile=SIMPLE_PROFILE)
    program = TransformProgram('model-program', ('source', 'budgets'), (
        TransformStep('aggregate_grouped', {
            'group_fields': ['period', 'unit_id'],
            'value_fields': ['gross_cny', 'refund_cny', 'cost_cny', 'gross_cny', 'cost_cny'],
            'functions': ['sum', 'sum', 'sum', 'sum', 'sum'],
            'outputs': ['gross_cny_sum', 'refund_cny_sum', 'cost_cny_sum', 'revenue_cny', 'profit_cny'],
        }),
        TransformStep('derive_safe', {'calculations': [
            ['revenue_cny', 'difference', 'gross_cny_sum', 'refund_cny_sum'],
            ['profit_cny', 'difference', 'revenue_cny', 'cost_cny_sum'],
        ]}),
        TransformStep('join_by_key', {
            'right_ref': 'budgets', 'left_keys': ['period', 'unit_id'], 'right_keys': ['period', 'unit_id'],
        }),
        TransformStep('derive_safe', {'calculations': [
            ['budget_delta_cny', 'difference', 'revenue_cny', 'budget_cny'],
        ]}),
        TransformStep('select', {'columns': list(task.output_schema)}),
    ), task.output_contract_version)
    constraints = runner._repair_constraints(
        program, task.input_schemas, task.output_schema, ['derive_output_collision:1'])
    edits = constraints['required_program_edits']
    assert [edit['position'] for edit in edits[:2]] == [4, 3]
    assert all(edit['kind'] == 'delete_parallel_array_position' for edit in edits[:2])
    assert edits[2]['kind'] == 'replace_parallel_array_value'
    assert edits[2]['position'] == 2
    assert edits[2]['from'] == 'cost_cny_sum'
    assert edits[2]['to'] == 'cost_cny'
    assert edits[2]['reference_updates']


def test_live_repair_context_emits_safe_join_prefix_edit():
    from statebus.contracts import TransformProgram, TransformStep

    task = task_contract('F08', profile=SIMPLE_PROFILE)
    program = TransformProgram('model-program', ('source', 'budgets'), (
        TransformStep('aggregate_grouped', {
            'group_fields': ['period', 'unit_id'],
            'value_fields': ['gross_cny', 'refund_cny', 'cost_cny'],
            'functions': ['sum', 'sum', 'sum'],
            'outputs': ['sum_gross_cny', 'sum_refund_cny', 'cost_cny'],
        }),
        TransformStep('derive_safe', {'calculations': [
            ['revenue_cny', 'difference', 'sum_gross_cny', 'sum_refund_cny'],
            ['profit_cny', 'difference', 'revenue_cny', 'cost_cny'],
        ]}),
        TransformStep('join_by_key', {
            'right_ref': 'budgets', 'left_keys': ['period', 'unit_id'], 'right_keys': ['period', 'unit_id'],
            'right_prefix': 'budget_',
        }),
        TransformStep('derive_safe', {'calculations': [
            ['budget_delta_cny', 'difference', 'revenue_cny', 'budget_budget_cny'],
        ]}),
        TransformStep('select', {'columns': [
            'period', 'unit_id', 'revenue_cny', 'cost_cny', 'profit_cny',
            'budget_budget_cny', 'budget_delta_cny',
        ]}),
    ), task.output_contract_version)
    constraints = runner._repair_constraints(
        program, task.input_schemas, task.output_schema, ['invalid_aggregate_outputs:0'])
    join_edits = [edit for edit in constraints['required_program_edits']
                  if edit['kind'] == 'remove_join_right_prefix']
    assert join_edits == [{
        'kind': 'remove_join_right_prefix',
        'operation_index': 2,
        'from': 'budget_',
        'to': '',
        'required_right_fields': ['budget_cny'],
        'preserve_shared_join_keys': True,
        'update_downstream_references': {'budget_budget_cny': 'budget_cny'},
        'reference_updates': [
            {'operation_index': 3, 'path': ['arguments', 'calculations', 0, 3],
             'from': 'budget_budget_cny', 'to': 'budget_cny'},
            {'operation_index': 4, 'path': ['arguments', 'columns', 5],
             'from': 'budget_budget_cny', 'to': 'budget_cny'},
        ],
        'reason': 'right_prefix_would_hide_required_final_columns',
        'do_not_add_rename_operation': True,
    }]


def test_required_repair_edits_are_idempotent_when_provider_already_removed_duplicates():
    from statebus.contracts import TransformProgram, TransformStep

    task = task_contract('F09', profile=SIMPLE_PROFILE)
    source = TransformProgram('source', ('source', 'budgets'), (
        TransformStep('aggregate_grouped', {
            'group_fields': ['period', 'unit_id'],
            'value_fields': ['gross_cny', 'refund_cny', 'cost_cny', 'gross_cny', 'cost_cny'],
            'functions': ['sum', 'sum', 'sum', 'sum', 'sum'],
            'outputs': ['gross_cny_sum', 'refund_cny_sum', 'cost_cny_sum', 'revenue_cny', 'profit_cny'],
        }),
        TransformStep('derive_safe', {'calculations': [
            ['revenue_cny', 'difference', 'gross_cny_sum', 'refund_cny_sum'],
            ['profit_cny', 'difference', 'revenue_cny', 'cost_cny_sum'],
        ]}),
        TransformStep('join_by_key', {
            'right_ref': 'budgets', 'left_keys': ['period', 'unit_id'], 'right_keys': ['period', 'unit_id'],
        }),
        TransformStep('derive_safe', {'calculations': [
            ['budget_delta_cny', 'difference', 'revenue_cny', 'budget_cny'],
        ]}),
        TransformStep('select', {'columns': [
            'period', 'unit_id', 'budget_cny', 'budget_delta_cny', 'cost_cny_sum', 'revenue_cny', 'profit_cny',
        ]}),
    ), task.output_contract_version)
    provider_candidate = TransformProgram('provider', ('source', 'budgets'), (
        TransformStep('aggregate_grouped', {
            'group_fields': ['period', 'unit_id'],
            'value_fields': ['gross_cny', 'refund_cny', 'cost_cny'],
            'functions': ['sum', 'sum', 'sum'],
            'outputs': ['gross_cny_sum', 'refund_cny_sum', 'cost_cny_sum'],
        }),
        source.operations[1], source.operations[2], source.operations[3],
        TransformStep('select', {'columns': [
            'period', 'unit_id', 'budget_cny', 'budget_delta_cny', 'cost_cny_sum', 'revenue_cny', 'profit_cny',
        ]}),
    ), task.output_contract_version)
    logical = runner._repair_constraints(
        source, task.input_schemas, task.output_schema, ['derive_output_collision:1'],
    )
    normalized, applied = runner._apply_required_program_edits(
        provider_candidate, logical['required_program_edits'], source_program=source,
    )
    assert normalized.operations[0].arguments['outputs'] == ['gross_cny_sum', 'refund_cny_sum', 'cost_cny']
    assert normalized.operations[1].arguments['calculations'][1][3] == 'cost_cny'
    assert normalized.operations[-1].arguments['columns'][4] == 'cost_cny'
    assert any(item['status'] == 'already_applied' for item in applied)


def test_required_repair_edits_reject_unlisted_aggregate_surface_changes():
    from statebus.contracts import TransformProgram, TransformStep

    schemas = {'source': {'period': 'string', 'unit_id': 'string', 'gross_cny': 'number',
                          'refund_cny': 'number', 'cost_cny': 'number'}}
    source = TransformProgram('source', ('source',), (
        TransformStep('aggregate_grouped', {
            'group_fields': ['period', 'unit_id'],
            'value_fields': ['gross_cny', 'refund_cny', 'cost_cny'],
            'functions': ['sum', 'sum', 'sum'],
            'outputs': ['revenue_cny', 'refund_cny', 'cost_cny'],
        }),
        TransformStep('derive_safe', {'calculations': [
            ['revenue_cny', 'difference', 'revenue_cny', 'refund_cny'],
        ]}),
    ), 'generic-contract')
    candidate = TransformProgram('candidate', ('source',), (
        TransformStep('aggregate_grouped', {
            'group_fields': ['period', 'unit_id'],
            'value_fields': ['gross_cny', 'refund_cny', 'cost_cny', 'gross_cny'],
            'functions': ['sum', 'sum', 'sum', 'count'],
            'outputs': ['sum_gross_cny', 'refund_cny', 'sum_cost_cny', 'count_rows'],
        }),
        TransformStep('derive_safe', {'calculations': [
            ['revenue_cny', 'difference', 'sum_gross_cny', 'refund_cny'],
        ]}),
    ), 'generic-contract')
    constraints = runner._repair_constraints(
        source, schemas, {'revenue_cny': 'number', 'refund_cny': 'number', 'cost_cny': 'number'},
        ['derive_output_collision:1'],
    )
    edits = constraints['required_program_edits']
    normalized, _ = runner._apply_required_program_edits(candidate, edits, source_program=source)
    mechanical, _ = runner._apply_required_program_edits(source, edits, source_program=source)
    assert not runner._required_edit_surfaces_match(normalized, mechanical, edits)
    assert mechanical.operations[0].arguments['outputs'] == ['sum_gross_cny', 'refund_cny', 'cost_cny']


def test_live_repair_context_does_not_guess_unsafe_join_prefix_removal():
    from statebus.contracts import TransformProgram, TransformStep

    schemas = {
        'source': {'period': 'string', 'unit_id': 'string', 'budget_cny': 'number'},
        'budgets': {'period': 'string', 'unit_id': 'string', 'budget_cny': 'number'},
    }
    program = TransformProgram('model-program', ('source', 'budgets'), (
        TransformStep('join_by_key', {
            'right_ref': 'budgets', 'left_keys': ['period', 'unit_id'], 'right_keys': ['period', 'unit_id'],
            'right_prefix': 'budget_',
        }),
    ), 'generic-contract')
    constraints = runner._repair_constraints(
        program, schemas, {'period': 'string', 'unit_id': 'string', 'budget_cny': 'number'},
        ['unknown_column:0'])
    assert not any(edit['kind'] == 'remove_join_right_prefix'
                   for edit in constraints.get('required_program_edits', []))


def test_live_repair_context_exposes_join_collision_and_prefixed_column():
    from statebus.contracts import TransformProgram, TransformStep

    task = task_contract('O08', profile=SIMPLE_PROFILE)
    aggregate = TransformStep('aggregate_grouped', {'group_fields': ['period', 'site_id'],
        'value_fields': ['request_count', 'failed_count'], 'functions': ['sum', 'sum'],
        'outputs': ['request_count', 'failed_count']})
    program = TransformProgram('model-program', ('source', 'plans'), (
        aggregate, TransformStep('join_by_key', {'right_ref': 'plans',
            'left_key': 'site_id', 'right_key': 'site_id'}),
    ), task.output_contract_version)
    constraints = runner._repair_constraints(program, task.input_schemas, task.output_schema,
        ['join_output_collision:1'])
    assert constraints['colliding_join_columns'] == ['period']
    assert constraints['shared_join_keys'] == ['period', 'site_id']
    assert constraints['column_trace'][1]['error'] == 'join_output_collision'
    assert 'output_columns' not in constraints['column_trace'][1]

    prefixed = TransformProgram('model-program', ('source', 'plans'), (
        aggregate, TransformStep('join_by_key', {'right_ref': 'plans',
            'left_keys': ['period', 'site_id'], 'right_keys': ['period', 'site_id'],
            'right_prefix': 'plan_'}),
        TransformStep('derive_safe', {'calculations': [
            ['plan_delta_count', 'difference', 'request_count', 'plan_planned_request_count']]}),
        TransformStep('sort', {'columns': ['period', 'site_id']}),
        TransformStep('select', {'columns': ['period', 'site_id', 'request_count',
            'failed_count', 'planned_request_count', 'plan_delta_count']}),
    ), task.output_contract_version)
    constraints = runner._repair_constraints(prefixed, task.input_schemas, task.output_schema,
        ['unknown_column:4'])
    assert constraints['column_trace'][4]['error'] == 'unknown_column'
    assert 'plan_planned_request_count' in constraints['column_trace'][4]['input_columns']
    assert 'planned_request_count' not in constraints['column_trace'][4]['input_columns']


def test_required_join_edit_rejects_unlisted_key_or_rhs_changes():
    from statebus.contracts import TransformProgram, TransformStep

    schemas = {
        'source': {'period': 'string', 'unit_id': 'string', 'revenue_cny': 'number'},
        'budgets': {'period': 'string', 'unit_id': 'string', 'budget_cny': 'number'},
    }
    source = TransformProgram('source', ('source', 'budgets'), (
        TransformStep('join_by_key', {
            'right_ref': 'budgets',
            'left_keys': ['period', 'unit_id'],
            'right_keys': ['period', 'unit_id'],
            'right_prefix': 'budget_',
        }),
    ), 'generic-contract')
    constraints = runner._repair_constraints(
        source, schemas,
        {'period': 'string', 'unit_id': 'string', 'revenue_cny': 'number', 'budget_cny': 'number'},
        ['join_output_collision:0'],
    )
    edits = constraints['required_program_edits']
    mechanical, _ = runner._apply_required_program_edits(source, edits, source_program=source)

    changed = TransformProgram('candidate', ('source', 'budgets'), (
        TransformStep('join_by_key', {
            'right_ref': 'budgets',
            'left_keys': ['unit_id'],
            'right_keys': ['unit_id'],
            'right_prefix': 'budget_',
        }),
    ), 'generic-contract')
    normalized, _ = runner._apply_required_program_edits(changed, edits, source_program=source)
    assert not runner._required_edit_surfaces_match(normalized, mechanical, edits)


@pytest.mark.parametrize('damage', [None, 'row', 'identity', 'context', 'source', 'memory'])
def test_structured_report_preserves_facts_citations_and_memory_checks(monkeypatch, damage):
    row = {'unit_id': 'U-A', 'period_count': 6, 'revenue_cny': 123}
    evidence = [{'id': 'a', 'locator': 'loc-a', 'text': 'U-A 2026-06: No causal inference.'},
                {'id': 'b', 'locator': 'loc-b', 'text': 'U-B 2026-06: Qualified observation.'}]
    payload = {'rows': [row], 'evidence': evidence, 'memory_cross_check': {
        'memory_id': 'memory:F10', 'producer_agent': 'executor', 'rows': [dict(row)]}}
    item = {'row': dict(row), 'evidence_id': 'a', 'context_text': evidence[0]['text'],
            'memory_id': 'memory:F10', 'matches_memory': True}
    if damage == 'row': item['row']['revenue_cny'] += 1
    if damage == 'identity': item['row']['unit_id'] = 'U-B'
    if damage == 'context': item['context_text'] = 'No causal inference.'
    if damage == 'source': item.update(evidence_id='b', context_text=evidence[1]['text'])
    if damage == 'memory': item['matches_memory'] = False
    monkeypatch.setattr(runner, '_provider_json', lambda *a, **k: {'claims': [item]})
    if damage:
        with pytest.raises(ValueError, match='report_'):
            runner._simple_report_claims(object(), payload, artifact_id='artifact:current', start=0)
    else:
        claims = runner._simple_report_claims(object(), payload, artifact_id='artifact:current', start=0)
        runner._checked_report(claims, [row])
        assert 'memory_ref=memory:F10' in claims[0].claim_text
        assert evidence[0]['text'] in claims[0].claim_text


def test_business_quality_is_not_mechanism_acceptance():
    from statebus.benchmark.contest_dsl_metrics import aggregate_slots
    result = aggregate_slots([{'chain_id': 'f', 'task_id': 'F11', 'status': 'quality_fail',
                               'quality': True, 'mechanism_gate_passed': False}])
    assert result['passed_count'] == 0
    assert result['business_quality_passed_count'] == 1
    assert result['quality_pass_rate'] == 1
    assert result['success_rate_planned'] == 0

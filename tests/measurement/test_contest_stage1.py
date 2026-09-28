from __future__ import annotations

import asyncio
from dataclasses import replace
import json
from pathlib import Path
import shutil

import pytest

from statebus.benchmark.contest_stage1 import publish, task_budget
from statebus.benchmark.contest_stage1_taskpack import generate_sealed, make_case, files_for, PERIODS
from statebus.benchmark.contest_stage1_report import report_sources
from statebus.benchmark.contest_stage1_scorer import score_rows, reference_rows
from statebus.benchmark.adaptive_formal import recompute_formal_rows, build_formal_quality_validator
from statebus.benchmark.request_journal import JournalClient, summarize_journal
from statebus.runtime.capability_validators import CapabilityQualityContext
from statebus.runtime.codeact_sandbox import CodeActSandboxConfig, CodeActSandboxRunner
from statebus.contracts import CodeGenerationPolicy
from statebus.runtime.llm_codeact import audit_generated_source


FAILURE_FIXTURES = Path(__file__).resolve().parents[1] / 'fixtures/contest_stage1_failures'


@pytest.fixture
def pack(tmp_path):
    sealed = tmp_path / 'sealed'
    generate_sealed(sealed)
    return sealed


@pytest.mark.parametrize('prefix,size', [('F',24),('O',672)])
def test_release_isolation_history_and_independent_score(pack, tmp_path, prefix, size):
    first, second = f'{prefix}01', f'{prefix}02'
    public = tmp_path / 'lane-a' / 'public'
    publish(pack, public, first)
    with pytest.raises(FileNotFoundError):
        make_case(public, second)
    case1 = make_case(public, first)
    assert len(case1.source_rows) == size
    expected1 = reference_rows(public, first)
    computed1 = recompute_formal_rows(case1.operation, case1.spec.arguments, case1.source_rows)
    assert score_rows(public, first, computed1)['passed']
    publish(pack, public, second)
    case2 = make_case(public, second)
    assert len(case2.source_rows) == 2*size
    computed2 = recompute_formal_rows(case2.operation, case2.spec.arguments, case2.source_rows)
    assert score_rows(public, second, computed2)['passed']
    assert not score_rows(public, second, expected1)['passed']
    assert sum(left != right for left,right in zip(computed1,computed2)) >= 2
    # The second review recomputes the previous/current risks from released raw
    # rows. Model-visible, verified historical results are tested at the closer.
    assert {row['is_current'] for row in case2.source_rows} == {False, True}
    assert 'is_current' in case1.source_schema == case2.source_schema
    wrong = [dict(row) for row in computed2]
    wrong[0]['profit_cny' if prefix == 'F' else 'request_count'] += 1
    assert not score_rows(public, second, wrong)['passed']
    wrong = [dict(row) for row in computed2]
    wrong[0]['note_locator' if prefix == 'F' else 'event_locator'] = 'future.md#bogus'
    assert not score_rows(public, second, wrong)['passed']
    other = tmp_path / 'lane-b' / 'public'
    publish(pack, other, first)
    assert len(make_case(other, first).source_rows) == size
    assert not any(('2026-02' if prefix == 'F' else 'W02') in path.name for path in other.rglob('*') if path.is_file())
    surface = case2.sample.request_text + str(case2.spec.canonical_payload())
    assert not any(word in surface for word in ('expected_facts', 'expected_skip', 'expected_hit', 'gold', 'F06', 'O06'))


def test_data_seed_is_fixed_and_changes_with_seed(tmp_path):
    for name, seed in [('a',20260924),('b',20260924),('c',20260925)]:
        generate_sealed(tmp_path/name, seed=seed)
    a = tmp_path/'a'/'finance'/'actual_2026-01.csv'
    assert a.read_bytes() == (tmp_path/'b'/'finance'/a.name).read_bytes()
    assert a.read_bytes() != (tmp_path/'c'/'finance'/a.name).read_bytes()
    with pytest.raises(FileExistsError):
        generate_sealed(tmp_path/'a')


def test_provider_failure_usage_is_null_and_started_survives(tmp_path):
    class FailedClient:
        request_events = []
        async def complete(self, messages, **kwargs):
            self.request_events.append({'status':'error','request_id':'failed'})
            raise TimeoutError('test_timeout')
    from statebus.integrations.llm import ChatMessage
    path = tmp_path/'provider.jsonl'
    with pytest.raises(TimeoutError):
        asyncio.run(JournalClient(FailedClient(),path).complete([ChatMessage('user','hello')],purpose='executor'))
    result = summarize_journal(path)
    assert result['provider_request_count'] == 1
    assert result['usage']['total_tokens'] is None
    assert result['call_count'] == 1
    events = [json.loads(line) for line in path.read_text().splitlines()]
    path.write_text(json.dumps(events[0])+'\n')
    result = summarize_journal(path)
    assert result['unresolved_call_ids'] and result['provider_request_count'] is None


def test_risk_threshold_uses_unrounded_ratio(pack,tmp_path):
    public=tmp_path/'public'; publish(pack,public,'F01')
    case=make_case(public,'F01')
    rows=[dict(row) for row in case.source_rows]
    for row in rows:
        row['net_revenue_cny']=100000000
        row['cost_cny']=80000001
    result=recompute_formal_rows(case.operation,case.spec.arguments,tuple(rows))
    assert result[0]['margin_pct']==20 and result[0]['below_20_pct'] is True


def test_budget_includes_actual_bounded_repairs():
    budget=task_budget()
    assert budget['outer_watchdog_s'] > budget['runtime_dispatch_budget_ms']/1000
    assert budget['provider_max_attempts']==1
    assert budget['python_repairs']=={'policy':1,'runtime':1,'quality':1}


@pytest.mark.parametrize('task_id', ['F02', 'O02'])
def test_review_quality_requires_bound_input_and_provenance(pack, tmp_path, task_id):
    public = tmp_path / 'public'
    publish(pack, public, task_id[0] + '01')
    publish(pack, public, task_id)
    case = make_case(public, task_id)
    output = recompute_formal_rows(case.operation, case.spec.arguments, case.source_rows)
    context = CapabilityQualityContext(
        capability_id=case.capability_id, validator_id='formal_analysis',
        input_rows=(case.source_rows,), output_rows=output,
        input_artifact_hashes=('sha256:current-authorized-input',),
        output_artifact_hash='sha256:output', required_fields=tuple(case.output_schema),
        provenance_item_ids=('controller-bound-source',),
    )
    validate = build_formal_quality_validator(case)
    assert validate(context).verified
    for field, error in [('input_artifact_hashes', 'missing_input_artifact_hash'),
                         ('provenance_item_ids', 'missing_provenance')]:
        rejected = validate(replace(context, **{field: ()}))
        assert not rejected.verified and error in rejected.error_codes
    stale = reference_rows(public, task_id[0] + '01')
    assert not validate(replace(context, output_rows=tuple(stale))).verified
    assert not validate(replace(context, input_rows=())).verified


def test_provider_success_usage_reconciles_actual_calls(tmp_path):
    from types import SimpleNamespace
    from statebus.integrations.llm import ChatMessage
    class SuccessfulClient:
        request_events = []
        async def complete(self, messages, **kwargs):
            self.request_events.append({'status': 'success', 'response_prompt_tokens': 11,
                                        'response_completion_tokens': 7, 'response_total_tokens': 18})
            return SimpleNamespace(text='observed output', model='local-test', finish_reason='stop')
    journal = JournalClient(SuccessfulClient(), tmp_path/'journal.jsonl')
    for role in ('planner', 'summarizer'):
        asyncio.run(journal.complete([ChatMessage('user', 'observed input')], purpose=role))
    result = summarize_journal(journal.path)
    assert result['call_count'] == result['provider_request_count'] == 2
    assert result['usage'] == {'prompt_tokens': 22, 'completion_tokens': 14, 'total_tokens': 36}
    assert result['unresolved_call_ids'] == []
    records = [json.loads(line) for line in journal.path.read_text().splitlines()]
    assert records[0]['messages'][0]['content'] == 'observed input'
    assert records[1]['raw_response'] == 'observed output'


def test_runner_keeps_failure_timeout_and_unstarted_denominator(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import subprocess
    import statebus.benchmark.contest_stage1 as runner
    root = tmp_path / 'smoke'
    observed_start_states = []
    calls = []
    killed = []
    class Worker:
        pid = 12345
        def __init__(self, command, **kwargs):
            self.index = len(calls)
            self.waits = 0
            calls.append(command)
            observed_start_states.append(json.loads((root/'ledger.json').read_text()))
        def wait(self, timeout=None):
            self.waits += 1
            if self.index == 1 and self.waits == 1:
                raise subprocess.TimeoutExpired(calls[self.index], timeout)
            return 1
    monkeypatch.setattr(runner.subprocess, 'Popen', Worker)
    monkeypatch.setattr(runner.os, 'killpg', lambda pid, sig: killed.append((pid, sig)))
    args = SimpleNamespace(output_root=root, family='finance', profile='SB-FULL', dry_run=False,
                           sb_memory_policy='validated_replay',
                           embedding_model_path='unused', embedding_device='cpu')
    assert runner.run(args) == 1
    assert [e['status'] for e in observed_start_states[0]] == ['running', 'not_started']
    summary = json.loads((root/'summary.json').read_text())
    assert summary['planned_count'] == 2 and summary['passed_count'] == 0
    assert [e['status'] for e in summary['ledger']] == ['failed', 'timeout']
    assert killed and all(e['elapsed_ms'] >= 0 for e in summary['ledger'])
    history = json.loads((root/'finance'/'SB-FULL'/'F02'/'history-before.json').read_text())
    assert len(history) == 1 and history[0]['ok'] is False and history[0]['output_rows'] == []
    assert all(e['provider']['usage']['total_tokens'] is None for e in summary['ledger'])


def test_effective_dry_run_reads_real_role_config(tmp_path, monkeypatch):
    import yaml
    from statebus.benchmark.contest_stage1 import effective_configuration, effective_budget
    path = tmp_path/'llm.yaml'
    path.write_text(yaml.safe_dump({'providers': {'local': {'timeout_s': 480, 'request_max_attempts': 3}},
                                  'roles': {role: {'model': 'test-model', 'provider': 'local', 'max_tokens': 432}
                                            for role in ('planner','retriever','executor','summarizer')}}))
    monkeypatch.setenv('STATEBUS_LLM_CONFIG_FILE', str(path))
    monkeypatch.setenv('STATEBUS_ADAPTIVE_PLANNER_MAX_TOKENS', '777')
    budget = effective_budget(effective_configuration())
    assert budget['roles']['planner'] == {'model':'test-model', 'max_tokens':777, 'timeout_s':90}
    assert budget['roles']['executor']['max_tokens'] == 2200
    assert budget['roles']['retriever']['max_tokens'] == 432
    assert yaml.safe_load(path.read_text())['providers']['local']['timeout_s'] == 480
    monkeypatch.setenv('STATEBUS_ADAPTIVE_EXECUTOR_MAX_TOKENS', '2500')
    budget = effective_budget(effective_configuration())
    assert budget['roles']['executor']['max_tokens'] == budget['code_max_tokens'] == 2500


def test_effective_configuration_applies_serving_context_cap_to_all_roles(tmp_path, monkeypatch):
    import yaml
    from statebus.benchmark.contest_stage1 import effective_configuration, effective_budget
    path = tmp_path/'llm.yaml'
    path.write_text(yaml.safe_dump({'providers': {'local': {'timeout_s': 480, 'request_max_attempts': 3}},
                                  'roles': {role: {'model': 'test-model', 'provider': 'local', 'max_tokens': 432}
                                            for role in ('planner','retriever','executor','summarizer')}}))
    monkeypatch.setenv('STATEBUS_LLM_CONFIG_FILE', str(path))

    configuration = effective_configuration(8192)
    budget = effective_budget(configuration)

    assert {values['max_context_tokens'] for values in configuration['roles'].values()} == {8192}
    assert {values['max_context_safety_margin_tokens'] for values in configuration['roles'].values()} == {128}
    assert budget['roles']['executor']['max_context_tokens'] == 8192
    assert budget['roles']['executor']['max_context_safety_margin_tokens'] == 128


def test_local_json_roles_preserve_numeric_compatibility(monkeypatch, tmp_path):
    import asyncio
    from types import SimpleNamespace
    import yaml
    from statebus.integrations.llm import ChatMessage, OpenAICompatibleLLMClient, LLMConfig
    path = tmp_path / 'llm.yaml'
    path.write_text(yaml.safe_dump({'mode': 'local_vllm', 'providers': {'default': {'base_url': 'http://127.0.0.1:53334/v1'}},
        'roles': {role: {'provider': 'default', 'model': 'test-model', 'json_output': True}
                  for role in ('planner','retriever','executor','summarizer')}}))
    client = OpenAICompatibleLLMClient.__new__(OpenAICompatibleLLMClient)
    client.config = LLMConfig.from_file(path)
    client.request_events = []
    monkeypatch.setattr(client, '_build_provider_client', lambda _: object())
    observed = []
    async def capture(**kwargs):
        observed.append(kwargs['request'])
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop',
            message=SimpleNamespace(content='{"claims":[]}'), logprobs=None)], model='test-model', usage=None)
    monkeypatch.setattr(client, '_create_completion_with_retry', capture)
    messages = [ChatMessage(role='user', content='report')]
    asyncio.run(client.complete(messages, purpose='summarizer', response_schema={'type':'object'}))
    asyncio.run(client.complete(messages, purpose='planner', response_schema={'type':'object'}))
    assert observed[0]['response_format'] == {'type':'json_object'}
    assert observed[1]['response_format']['type'] == 'json_schema'
    assert observed[1]['response_format']['json_schema']['schema'] == {'type':'object'}


def test_local_simple_fact_report_uses_schema_guided_summarizer(monkeypatch, tmp_path):
    import asyncio
    from types import SimpleNamespace
    import yaml
    from statebus.integrations.llm import ChatMessage, OpenAICompatibleLLMClient, LLMConfig
    path = tmp_path / 'llm.yaml'
    path.write_text(yaml.safe_dump({'mode': 'local_vllm', 'providers': {'default': {'base_url': 'http://127.0.0.1:53334/v1'}},
        'roles': {role: {'provider': 'default', 'model': 'test-model', 'json_output': True}
                  for role in ('planner','retriever','executor','summarizer')}}))
    client = OpenAICompatibleLLMClient.__new__(OpenAICompatibleLLMClient)
    client.config = LLMConfig.from_file(path)
    client.request_events = []
    monkeypatch.setattr(client, '_build_provider_client', lambda _: object())
    observed = []
    async def capture(**kwargs):
        observed.append(kwargs['request'])
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop',
            message=SimpleNamespace(content='{"claims":[]}'), logprobs=None)], model='test-model', usage=None)
    monkeypatch.setattr(client, '_create_completion_with_retry', capture)
    schema = {'title': 'statebus_simple_fact_report_v1', 'type': 'object',
              'additionalProperties': False, 'required': ['claims'],
              'properties': {'claims': {'type': 'array', 'items': {'type': 'object'}}}}
    asyncio.run(client.complete([ChatMessage(role='user', content='report')],
                                purpose='summarizer', response_schema=schema))
    assert observed[0]['response_format']['type'] == 'json_schema'
    assert observed[0]['response_format']['json_schema']['name'] == 'role_object'
    assert observed[0]['response_format']['json_schema']['schema']['title'] == 'statebus_simple_fact_report_v1'


def test_campaign_does_not_mutate_shared_config(tmp_path, monkeypatch):
    import yaml
    from statebus.benchmark.contest_stage1 import effective_configuration, effective_budget
    from statebus.integrations.llm import LLMConfig
    config = {'mode': 'local_vllm', 'providers': {'local': {'base_url': 'http://127.0.0.1:53334/v1'}},
              'roles': {role: {'model': 'test-model', 'provider': 'local', 'max_tokens': 432,
                               'json_output': role != 'executor',
                               'extra_body': {'chat_template_kwargs': {'enable_thinking': False}}}
                        for role in ('planner', 'retriever', 'executor', 'summarizer')}}
    path = tmp_path / 'shared.yaml'; path.write_text(yaml.safe_dump(config))
    monkeypatch.setenv('STATEBUS_LLM_CONFIG_FILE', str(path))
    effective = effective_configuration()
    for role in ('planner', 'retriever', 'executor', 'summarizer'):
        assert effective['roles'][role]['extra_body']['chat_template_kwargs'] == {'enable_thinking': False}
    assert yaml.safe_load(path.read_text()) == config
    # P-TEXT's role override must retain the same summarizer settings.
    path = tmp_path / 'effective.yaml'; path.write_text(yaml.safe_dump(effective))
    monkeypatch.setenv('STATEBUS_LLM_CONFIG_FILE', str(path))
    parsed = LLMConfig.from_runtime().with_role_override('summarizer', json_output=True)
    assert parsed.role_config('summarizer').extra_body['chat_template_kwargs']['enable_thinking'] is False


def test_text_tool_rejects_malformed_rows_and_bool_numbers(pack, tmp_path):
    from statebus.benchmark.contest_stage1_text import output_matches
    public = tmp_path/'public'; publish(pack,public,'F01')
    case = make_case(public,'F01')
    rows = reference_rows(public,'F01')
    assert output_matches(case,rows)
    for malformed in (None, {}, ['bad'], [None]):
        assert not output_matches(case,malformed)
    rows[0]['profit_cny'] = True
    assert not output_matches(case, rows)


@pytest.mark.parametrize('operation,required_fragments', [
    ('finance_monthly_review', (
        'Group ALL raw rows by unit_id and the boolean is_current',
        "set risk_change='initial' for every current entity",
        'missing derived risk key as false',
        'stale row variable',
        'note_locator',
    )),
    ('service_weekly_review', (
        'Group ALL raw rows by site_id and the boolean is_current',
        "set risk_change='initial' for every current entity",
        'missing derived risk key as false',
        'stale row variable',
        'event_locator',
    )),
])
def test_text_review_executor_guidance_is_operation_generic(operation, required_fragments):
    from statebus.benchmark.adaptive_formal import _operation_semantics

    guidance = _operation_semantics(operation, {})['executor_invariants']
    assert all(fragment in guidance for fragment in required_fragments)
    assert 'F01' not in guidance and 'O01' not in guidance
    assert 'final four current rows' not in guidance
    assert 'fixed literal' in guidance


@pytest.mark.parametrize('task_id', ['F01', 'O01'])
def test_no_prior_period_is_initial_not_still_clear(pack, tmp_path, task_id):
    """A missing previous aggregate is distinct from a present clear aggregate."""
    from statebus.benchmark.contest_stage1_text import output_matches

    public = tmp_path / 'public'
    publish(pack, public, task_id)
    case = make_case(public, task_id)
    expected = reference_rows(public, task_id)
    assert {row['risk_change'] for row in expected} == {'initial'}

    wrong = [dict(row, risk_change='still_clear') for row in expected]
    assert not output_matches(case, wrong)
    score = score_rows(public, task_id, wrong)
    assert not score['passed']
    assert all(not score['checks'][f'{index}:risk_change'] for index in range(4))


@pytest.mark.parametrize('task_id', ['F02', 'O02'])
def test_present_clear_previous_period_is_still_clear_not_initial(pack, tmp_path, task_id):
    """When prior rows exist, an all-clear prior/current pair has a real transition."""
    from statebus.benchmark.contest_stage1_text import output_matches

    public = tmp_path / 'public'
    publish(pack, public, task_id[0] + '01')
    publish(pack, public, task_id)
    case = make_case(public, task_id)
    rows = []
    for original in case.source_rows:
        row = dict(original)
        if task_id.startswith('F'):
            row['net_revenue_cny'] = 100
            row['cost_cny'] = 70
        else:
            row['request_count'] = 100
            row['failed_request_count'] = 1
            row['latency_sum_ms'] = 1000
        rows.append(row)
    case = replace(case, source_rows=tuple(rows))
    expected = list(recompute_formal_rows(case.operation, case.spec.arguments, case.source_rows))
    assert {row['risk_change'] for row in expected} == {'still_clear'}

    wrong = [dict(row, risk_change='initial') for row in expected]
    assert not output_matches(case, wrong)


@pytest.mark.parametrize('task_id,key', [('F02', 'unit_id'), ('O02', 'site_id')])
def test_period_review_uses_current_entities_and_treats_missing_prior_as_initial(pack, tmp_path, task_id, key):
    """Prior-only entities are ignored; current-only entities do not become all-clear."""
    public = tmp_path / 'public'
    publish(pack, public, task_id[0] + '01')
    publish(pack, public, task_id)
    case = make_case(public, task_id)
    current_period = '2026-02' if task_id.startswith('F') else 'W02'
    previous_period = '2026-01' if task_id.startswith('F') else 'W01'
    prior_only = 'legacy-only'
    current_only = 'new-current'
    rows = [dict(row) for row in case.source_rows]
    prior_template = next(row for row in rows if str(row[key]) == ('U-A' if task_id.startswith('F') else 'S-A')
                          and str(row['month' if task_id.startswith('F') else 'week']) == previous_period)
    prior_extra = dict(prior_template, **{key: prior_only})
    current_template = next(row for row in rows if str(row[key]) == ('U-B' if task_id.startswith('F') else 'S-B')
                            and str(row['month' if task_id.startswith('F') else 'week']) == current_period)
    current_extra = dict(current_template, **{key: current_only})
    rows.extend((prior_extra, current_extra))

    expected = recompute_formal_rows(case.operation, case.spec.arguments, tuple(rows))
    entities = [row[key] for row in expected]
    assert prior_only not in entities
    assert current_only in entities
    assert next(row for row in expected if row[key] == current_only)['risk_change'] == 'initial'


def test_service_review_binds_threshold_to_each_entity(pack, tmp_path):
    """A stale threshold from another entity must fail independent recomputation."""
    from statebus.benchmark.contest_stage1_text import output_matches

    public = tmp_path / 'public'
    publish(pack, public, 'O01')
    case = make_case(public, 'O01')
    thresholds = {'S-A': 0.01, 'S-B': 0.03, 'S-C': 0.02, 'S-D': 0.01}
    rows = []
    for original in case.source_rows:
        row = dict(original)
        site = row['site_id']
        row['slo_error_rate'] = thresholds[site]
        row['request_count'] = 100
        row['failed_request_count'] = 2
        row['latency_sum_ms'] = 1000
        rows.append(row)
    case = replace(case, source_rows=tuple(rows))
    expected = list(recompute_formal_rows(case.operation, case.spec.arguments, case.source_rows))
    by_site = {row['site_id']: row for row in expected}
    assert by_site['S-A']['exceeds_slo'] is True
    assert by_site['S-B']['exceeds_slo'] is False
    assert by_site['S-C']['exceeds_slo'] is False  # strict comparison at equality
    assert by_site['S-D']['exceeds_slo'] is True

    stale_threshold = [dict(row) for row in expected]
    for row in stale_threshold:
        if row['site_id'] in {'S-B', 'S-C'}:
            row['exceeds_slo'] = True  # what reusing S-D's 0.01 threshold would produce
    assert not output_matches(case, stale_threshold)


@pytest.mark.parametrize('task_id,key', [('F01', 'unit_id'), ('O01', 'site_id')])
def test_period_review_rejects_one_output_per_raw_row(pack, tmp_path, task_id, key):
    """The public contract is one current row per entity, not one row per CSV record."""
    from statebus.benchmark.contest_stage1_text import output_matches

    public = tmp_path / 'public'
    publish(pack, public, task_id)
    case = make_case(public, task_id)
    expected = reference_rows(public, task_id)
    by_entity = {row[key]: row for row in expected}
    projected = []
    for raw in case.source_rows:
        if raw['is_current']:
            row = dict(by_entity[raw[key]])
            projected.append(row)
    assert len(projected) > len(expected)
    assert not output_matches(case, projected)


def test_report_rejects_title_only_citation_and_missing_risk(pack, tmp_path):
    from statebus.benchmark.contest_stage1_report import report_errors
    public=tmp_path/'public'; publish(pack,public,'F01')
    rows=reference_rows(public,'F01')
    note = files_for(public, 'F01')[-1]
    sources = report_sources(note.read_text(), source_name=note.name, period=PERIODS['F01'],
                             entities=[r['unit_id'] for r in rows])
    evidence=[{'id': r['unit_id'], 'text': sources[r['unit_id']]['source_text'], 'locator':r['note_locator']}
              for r in rows]
    statements=[{'claim_text': f"{r['unit_id']} risk={str(r['below_20_pct']).lower()} risk_change={r['risk_change']} {r['note_locator']} {sources[r['unit_id']]['context']}",
                 'supporting_evidence_item_ids':[r['unit_id']], 'citation_locators':[r['note_locator']]}
                for r in rows]
    assert not report_errors(rows, statements, sources=sources, evidence_items=evidence)
    assert not report_errors(rows, statements, sources=sources)
    typed = [dict(s, claim_text=s['claim_text'].replace(r['note_locator'], '').strip())
             for s, r in zip(statements, rows)]
    assert not report_errors(rows, typed, sources=sources, evidence_items=evidence)
    assert 'report_current_locator:U-A' in report_errors(rows, typed, sources=sources)
    changed=[dict(s) for s in statements]
    changed[0]['claim_text']=changed[0]['claim_text'].replace('risk=true','risk=false')
    assert 'report_risk:U-A' in report_errors(rows, changed, sources=sources)
    changed[0]=dict(statements[0], supporting_evidence_item_ids=['title'])
    assert 'report_entity_evidence:U-A' in report_errors(rows, changed, sources=sources, evidence_items=evidence)
    changed[0]=dict(statements[0],claim_text='U-A has revenue; source notes_2026-01.md#U-A')
    errors=report_errors(rows,changed,sources=sources)
    assert 'report_risk:U-A' in errors and 'report_change:U-A' in errors


@pytest.mark.parametrize('task_id,key,risk,locator', [
    ('F01', 'unit_id', 'below_20_pct', 'note_locator'),
    ('O01', 'site_id', 'exceeds_slo', 'event_locator'),
])
@pytest.mark.parametrize('report_fault', ['summary_type', 'locator', 'context'])
def test_text_report_repair_preserves_verified_table_and_actual_handoffs(pack, tmp_path, monkeypatch, task_id, key, risk, locator, report_fault):
    from types import SimpleNamespace
    import statebus.benchmark.contest_stage1_text as text
    public = tmp_path / 'public'
    publish(pack, public, task_id)
    case = make_case(public, task_id)
    rows = reference_rows(public, task_id)
    note = files_for(public, task_id)[-1]
    sources = report_sources(note.read_text(), source_name=note.name, period=PERIODS[task_id],
                             entities=case.spec.target_entities)
    summary = '\n'.join(
        f"{row[key]} risk={str(row[risk]).lower()} "
        f"risk_change={row['risk_change']} {row[locator]} {sources[row[key]]['context']}"
        for row in rows
    )
    source = ('import json\nfrom pathlib import Path\nrows = json.loads(Path("inputs/task.json").read_text())\n'
              'Path("outputs/result.json").write_text(json.dumps(rows))\n')
    invalid_summary = {
        'summary_type': summary.splitlines(),
        'locator': summary.replace(rows[0][locator], rows[0][key]),
        'context': summary.replace(sources[rows[0][key]]['context'], 'See the cited note.'),
    }[report_fault]
    responses = iter([
        'Read, compute, verify, then report.',
        '\n'.join(s['source_text'] for s in sources.values()) + '\nU-B risk=true; unverified risk assertion.',
        source,
        source,
        json.dumps({'rows': rows, 'summary': invalid_summary}),
        json.dumps({'rows': rows, 'summary': summary}),
    ])
    calls = []
    schemas = []
    tool_calls = []
    class Client:
        async def complete(self, messages, *, purpose, **kwargs):
            calls.append((purpose, messages))
            schemas.append(kwargs.get('response_schema'))
            return SimpleNamespace(text=next(responses), finish_reason='stop')
    class Config:
        def with_mode(self, *args, **kwargs):
            return self
        def with_provider_override(self, *args, **kwargs):
            return self
        def with_role_override(self, *args, **kwargs):
            return self
        def role_config(self, *args, **kwargs):
            return SimpleNamespace(provider='local')
    def execute_fixture(self, *, outputs_dir, **kwargs):
        (outputs_dir / 'result.json').write_text(json.dumps(rows if tool_calls else rows * 2))
        tool_calls.append(outputs_dir)
        return SimpleNamespace(actual_backend='bwrap', completed=SimpleNamespace(returncode=0, stdout='', stderr=''))
    monkeypatch.delenv('STATEBUS_PROVIDER_JOURNAL', raising=False)
    monkeypatch.setattr(text.LLMConfig, 'from_runtime', lambda: Config())
    monkeypatch.setattr(text, 'build_llm_client', lambda _: Client())
    monkeypatch.setattr(text.CodeActSandboxRunner, 'run_llm_bwrap', execute_fixture)
    root = tmp_path / 'text'
    result = text.run_text(case, root, notes=note.read_text(), source_name=note.name, report_sources=sources)
    assert result['ok'] and result['output_rows'] == rows
    assert result['repairs']['quality'] == 1
    assert result['tool_records'][0]['errors'][0].startswith('output_row_count:expected=4,observed=8')
    assert result['report_checks'][0]['errors'] == [{
        'summary_type': 'report_summary_type:string_required',
        'locator': 'report_current_locator:' + rows[0][key],
        'context': 'report_current_context:' + rows[0][key],
    }[report_fault]]
    assert result['report_checks'][1]['errors'] == []
    assert [role for role, _ in calls] == ['planner', 'retriever', 'executor', 'executor', 'summarizer', 'summarizer']
    assert all(messages[0].role == 'system' for _, messages in calls)
    assert 'covering every current entity' in calls[1][1][-1].content
    assert 'all four entities' not in calls[1][1][-1].content
    report_rules = calls[-1][1][0].content
    assert 'public report contract' in report_rules
    assert 'current_below_20_pct' in calls[-1][1][-1].content
    assert 'Published source filename: ' + note.name in calls[1][1][-1].content
    assert 'note_locator' in report_rules and 'event_locator' in report_rules
    assert rows[0][locator] in calls[-1][1][-1].content
    executor_prompt = calls[2][1][-1].content
    assert 'Group ALL raw rows' in executor_prompt
    assert 'already bound in inputs/task.json' in executor_prompt
    assert "set risk_change='initial' for every current entity" in executor_prompt
    assert 'missing derived risk key as false' in executor_prompt
    repair_prompt = calls[3][1][-1].content
    assert 'Return the complete replacement Python file' in repair_prompt
    assert 'Group ALL raw rows' in repair_prompt
    assert "set risk_change='initial' for every current entity" in repair_prompt
    assert 'missing derived risk key as false' in repair_prompt
    assert schemas[-1]['properties']['summary']['type'] == 'string'
    assert schemas[-1]['properties']['rows']['items']['properties'] == {
        field: {'type': kind} for field, kind in case.output_schema.items()
    }
    assert schemas[-2] == schemas[-1]
    handoffs = [json.loads(line) for line in (root / 'handoffs.jsonl').read_text().splitlines()]
    assert len(handoffs) == 7
    tables = [json.loads(item['text']) for item in handoffs if item['sender'] == 'executor']
    assert tables == [rows, rows]


@pytest.mark.parametrize('task_id,key,risk,locator', [
    ('F02', 'unit_id', 'below_20_pct', 'note_locator'),
    ('O02', 'site_id', 'exceeds_slo', 'event_locator'),
])
def test_report_context_is_current_entity_scoped_and_in_body(pack, tmp_path, task_id, key, risk, locator):
    from statebus.benchmark.contest_stage1_report import report_errors
    public = tmp_path / 'public'
    publish(pack, public, task_id[0] + '01'); publish(pack, public, task_id)
    rows = reference_rows(public, task_id)
    note = files_for(public, task_id)[-1]
    sources = report_sources(note.read_text(), source_name=note.name, period=PERIODS[task_id],
                             entities=[r[key] for r in rows])
    statements = [dict(claim_text=f"{r[key]} risk={str(r[risk]).lower()} risk_change={r['risk_change']} "
                                 f"{r[locator]} Context: {sources[r[key]]['context']}",
                       supporting_evidence_item_ids=[r[key]], citation_locators=[r[locator]]) for r in rows]
    evidence = [dict(id=r[key], locator=r[locator], text=sources[r[key]]['source_text']) for r in rows]
    assert not report_errors(rows, statements, sources=sources, evidence_items=evidence)
    entity = rows[1][key]
    context = sources[entity]['context']
    for replacement in ('', 'See the note.', sources[rows[0][key]]['context'], context.split(';')[0] + '.'):
        changed = [dict(s) for s in statements]
        changed[1]['claim_text'] = changed[1]['claim_text'].replace(context, replacement)
        # Existing SB failures hid context in uncertainty_note rather than the delivered body.
        changed[1]['uncertainty_note'] = context
        for items in (None, evidence):
            assert 'report_current_context:' + entity in report_errors(rows, changed, sources=sources, evidence_items=items)
    # Typed IDs and citation strings alone do not establish current evidence.
    stale = [dict(e) for e in evidence]
    stale[1]['text'] = stale[1]['text'].replace(PERIODS[task_id], PERIODS[task_id[0] + '01'])
    assert 'report_entity_evidence:' + entity in report_errors(rows, statements, sources=sources, evidence_items=stale)
    wrong = [dict(s) for s in statements]
    wrong[1]['claim_text'] = wrong[1]['claim_text'].replace(rows[1][locator], rows[1][locator].replace(PERIODS[task_id], PERIODS[task_id[0] + '01']))
    assert 'report_current_locator:' + entity in report_errors(rows, wrong, sources=sources)
    # The checker reads the actual published source, not an entity->gold phrase table.
    new_sources = report_sources(note.read_text().replace(context, 'A newly published contextual fact.'),
                                 source_name=note.name, period=PERIODS[task_id], entities=[r[key] for r in rows])
    assert 'report_current_context:' + entity in report_errors(rows, statements, sources=new_sources)
    with pytest.raises(ValueError, match='report_source_current_context_missing'):
        report_sources(note.read_text(), source_name=note.name, period='unpublished', entities=[entity])


@pytest.mark.parametrize('policy,label', [('none', 'SB-NO-MEMORY'), ('validated_replay', 'SB-FULL')])
def test_worker_binds_memory_variant_and_report_validator(pack, tmp_path, monkeypatch, policy, label):
    from types import SimpleNamespace
    import statebus.benchmark.contest_stage1 as runner
    import statebus.benchmark.adaptive_formal_mainline as adaptive
    root = tmp_path / label / 'F01'
    publish(pack, root / 'public', 'F01')
    (root / 'history-before.json').write_text(json.dumps([{
        'task_id': 'F00', 'ok': True,
        'output_rows': [{'unit_id': 'stale', 'below_20_pct': True, 'risk_change': 'still_risk'}],
        'summary': 'stale answer must remain controller-only',
    }]))
    configuration = {'providers': {'local': {'timeout_s': 90}}, 'roles': {
        role: {'model': 'test', 'provider': 'local', 'max_tokens': 2200}
        for role in ('planner', 'retriever', 'executor', 'summarizer')}}
    monkeypatch.setattr(runner, 'effective_configuration', lambda *_: configuration)
    # execute_worker intentionally changes the child process environment; isolate it in this in-process test.
    monkeypatch.setattr(runner.os, 'environ', runner.os.environ.copy())
    def fake_adaptive(case, **kwargs):
        assert kwargs['memory_policy'] == policy
        assert kwargs['require_executor_model_role'] == (policy == 'none')
        assert kwargs['report_feedback'](['report_change:any-entity'])[0]['field'] == 'claim_text'
        assert kwargs['memory_store_root'] == root.parent / 'memory'
        assert 'complete current note/event sentence' in case.sample.request_text
        assert 'Own profile history' not in case.sample.request_text
        assert 'stale answer must remain controller-only' not in case.sample.request_text
        rows = reference_rows(root / 'public', 'F01')
        note = files_for(root / 'public', 'F01')[-1]
        sources = report_sources(note.read_text(), source_name=note.name, period=PERIODS['F01'],
                                 entities=case.spec.target_entities)
        claims = [dict(claim_text=f"{r['unit_id']} risk={str(r['below_20_pct']).lower()} risk_change=initial "
                                 f"{sources[r['unit_id']]['context']}",
                       supporting_evidence_item_ids=[r['unit_id']], citation_locators=[r['note_locator']]) for r in rows]
        evidence = [dict(id=r['unit_id'], locator=r['note_locator'], text=sources[r['unit_id']]['source_text']) for r in rows]
        assert not kwargs['report_validator'](rows[:2], claims[:2], evidence_items=evidence[:2])
        bad = [dict(c) for c in claims[:2]]
        bad[0]['claim_text'] = bad[0]['claim_text'].replace(sources['U-A']['context'], '')
        assert 'report_current_context:U-A' in kwargs['report_validator'](rows[:2], bad, evidence_items=evidence[:2])
        return {'ok': True, 'output_rows': rows, 'claim_sets': [{'claims': claims}], 'report_evidence_items': evidence}
    monkeypatch.setattr(adaptive, '_run_adaptive_case', fake_adaptive)
    args = SimpleNamespace(output_root=root, profile='SB-FULL', task='F01', sb_memory_policy=policy,
                           embedding_model_path='unused', embedding_device='cpu')
    assert runner.execute_worker(args) == 0
    result = json.loads((root / 'result.json').read_text())
    assert result['configuration_label'] == label and result['memory_policy'] == policy
    assert result['semantic_review_required'] is True
    assert json.loads((root / 'scorer.json').read_text())['business_report_errors'] == []


def test_memory_off_runner_names_and_isolates_chain_and_preserves_history(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import statebus.benchmark.contest_stage1 as runner
    root = tmp_path / 'off'
    observed = []
    class Worker:
        def __init__(self, command, **kwargs):
            assert command[command.index('--sb-memory-policy') + 1] == 'none'
            task = Path(command[command.index('--output-root') + 1])
            assert task.parent.name == 'SB-NO-MEMORY'
            history = json.loads((task / 'history-before.json').read_text())
            observed.append(history)
            runner.write_json(task / 'result.json', {'ok': True, 'output_rows': [{'own': task.name}], 'summary_text': task.name})
        def wait(self, timeout=None):
            return 0
    monkeypatch.setattr(runner.subprocess, 'Popen', Worker)
    args = SimpleNamespace(output_root=root, family='finance', profile='SB-FULL', sb_memory_policy='none',
                           dry_run=False, embedding_model_path='unused', embedding_device='cpu')
    assert runner.run(args) == 0
    assert observed[0] == [] and observed[1][0]['output_rows'] == [{'own': 'F01'}]
    summary = json.loads((root / 'summary.json').read_text())
    assert summary['planned_count'] == 2 and summary['passed_count'] == 2
    assert list(summary['chains_ms']) == ['finance/SB-NO-MEMORY']
    assert all(e['configuration_label'] == 'SB-NO-MEMORY' and e['memory_policy'] == 'none' for e in summary['ledger'])
    assert runner.execution_variant('P-TEXT', 'validated_replay') == {'configuration_label': 'P-TEXT', 'memory_policy': 'none'}


@pytest.mark.parametrize('task_id,key,amounts', [
    ('O02', 'site_id', ('request_count', 'failed_request_count')),
    ('F02', 'unit_id', ('net_revenue_cny', 'cost_cny')),
])
def test_period_risk_must_use_all_rows_not_last_row(pack, tmp_path, task_id, key, amounts):
    """Opposite last-row/prior-aggregate risks in both directions, not original-data coincidence."""
    import csv
    public = tmp_path / 'public'
    publish(pack, public, task_id[0] + '01'); publish(pack, public, task_id)
    family = 'service_ops' if task_id.startswith('O') else 'finance'
    folder = public / family
    old_entities = ('S-A', 'S-B', 'S-C', 'S-D') if task_id.startswith('O') else ('U-A', 'U-B', 'U-C', 'U-D')
    entities = ('zone-K17', 'zone-M32', 'zone-T08', 'zone-Z91')
    mapping = dict(zip(old_entities, entities))
    for note in folder.glob('*.md'):
        text = note.read_text()
        for old, new in mapping.items():
            text = text.replace(old, new)
        note.write_text(text)
    prior = 'W01' if task_id.startswith('O') else '2026-01'
    for path in folder.glob('*.csv'):
        with path.open() as handle:
            reader = csv.DictReader(handle); fields = reader.fieldnames; rows = list(reader)
        for row in rows:
            row[key] = mapping[row[key]]
        if path.name == 'slo.csv':
            for row in rows:
                row['slo_error_rate'] = '0.02'
        else:
            for index, entity in enumerate(entities):
                group = [row for row in rows if row[key] == entity]
                for row in group:
                    row[amounts[0]] = 100
                    row[amounts[1]] = 0 if task_id.startswith('O') else 70
                    if task_id.startswith('O'):
                        row['latency_sum_ms'] = 10000
                if prior in path.name:
                    # Even group: aggregate risky, last clear. Odd: aggregate clear, last risky.
                    first, last = group[0], group[-1]
                    first[amounts[0]] = 10000
                    first[amounts[1]] = (1000 if index % 2 == 0 else 0) if task_id.startswith('O') else (9900 if index % 2 == 0 else 6000)
                    last[amounts[1]] = (0 if index % 2 == 0 else 10) if task_id.startswith('O') else (50 if index % 2 == 0 else 99)
        with path.open('w', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader(); writer.writerows(rows)
    case = make_case(public, task_id)
    expected = reference_rows(public, task_id)
    recomputed = recompute_formal_rows(case.operation, case.spec.arguments, case.source_rows)
    assert expected == list(recomputed)
    wrong = [dict(row) for row in expected]
    for index, row in enumerate(wrong):
        assert row['risk_change'] == ('resolved' if index % 2 == 0 else 'still_clear')
        row['risk_change'] = 'still_clear' if index % 2 == 0 else 'resolved'
    score = score_rows(public, task_id, wrong)
    assert not score['passed'] and all(not score['checks'][f'{i}:risk_change'] for i in range(4))
    context = CapabilityQualityContext(
        capability_id=case.capability_id, validator_id='formal_analysis', input_rows=(case.source_rows,),
        output_rows=tuple(wrong), input_artifact_hashes=('current-input',), output_artifact_hash='wrong-output',
        required_fields=tuple(case.output_schema), provenance_item_ids=('bound-input',))
    quality = build_formal_quality_validator(case)(context)
    assert not quality.verified and 'formal_recomputation_mismatch' in quality.error_codes


def test_period_review_output_cardinality_comes_from_bound_current_entities(pack, tmp_path):
    from statebus.benchmark.contest_stage1_text import output_matches

    public = tmp_path / 'public'
    publish(pack, public, 'O01')
    case = make_case(public, 'O01')
    reduced = tuple(row for row in case.source_rows if row['site_id'] != 'S-D')
    case = replace(case, source_rows=reduced)
    expected = list(recompute_formal_rows(case.operation, case.spec.arguments, case.source_rows))

    assert len(expected) == 3
    assert output_matches(case, expected)
    assert 'Return precisely four rows' not in case.sample.request_text
    assert 'row count' in case.sample.request_text


@pytest.mark.parametrize(
    'fixture, expected_returncode',
    [('ptext_o02_runtime_candidate.py', 1), ('ptext_o02_quality_candidate.py', 0)],
)
def test_captured_ptext_o02_candidates_are_rejected_in_bwrap(pack, tmp_path, fixture, expected_returncode):
    """Replay captured combined-batch candidates without invoking a model."""
    if shutil.which('bwrap') is None:
        pytest.skip('bwrap is required for the captured CodeAct replay')
    from statebus.benchmark.contest_stage1_text import output_matches

    public = tmp_path / 'public'
    publish(pack, public, 'O01')
    publish(pack, public, 'O02')
    case = make_case(public, 'O02')
    attempt = tmp_path / 'attempt'
    inputs = attempt / 'inputs'; outputs = attempt / 'outputs'
    inputs.mkdir(parents=True); outputs.mkdir()
    (inputs / 'task.json').write_text(json.dumps(list(case.source_rows)), encoding='utf-8')
    (inputs / 'task.json').chmod(0o444); inputs.chmod(0o555); outputs.chmod(0o777)
    source = (FAILURE_FIXTURES / fixture).read_text(encoding='utf-8')
    source_path = attempt / 'generated.py'
    source_path.write_text(source, encoding='utf-8'); source_path.chmod(0o444)
    policy = CodeGenerationPolicy(
        capability_id='execute_bounded_python_v2', enabled=True, require_bwrap=True,
        allowed_module_roots=('json', 'pathlib', 're', 'statistics', 'collections'),
        allowed_input_relpaths=('inputs/task.json',), output_relpath='outputs/result.json',
        output_required_fields=tuple(case.output_schema), timeout_seconds=30,
    )
    assert audit_generated_source(source, policy).passed
    runner = CodeActSandboxRunner(CodeActSandboxConfig())
    readiness = runner.check_llm_bwrap_readiness(policy_version=policy.sandbox_policy_version)
    if not readiness.ready:
        pytest.skip(f'bwrap readiness unavailable: {readiness.reason}')
    executed = runner.run_llm_bwrap(
        source_path=source_path, inputs_dir=inputs, outputs_dir=outputs,
        policy_version=policy.sandbox_policy_version,
    )
    assert executed.completed.returncode == expected_returncode
    if expected_returncode:
        assert "NoneType" in executed.completed.stderr
    else:
        observed = json.loads((outputs / 'result.json').read_text(encoding='utf-8'))
        assert not output_matches(case, observed)

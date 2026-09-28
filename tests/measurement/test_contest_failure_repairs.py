"""Failure replay is offline: model responses are evidence, not fixed runtime answers."""
from copy import deepcopy
from functools import partial
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from statebus.benchmark.adaptive_formal_mainline import (
    _build_codeact_fallback_plan,
    _compile_formal_controller_wiring,
    _generate_claim_batch,
    _row_scoped_evidence_items,
    _summarizer_task_goal,
)
from statebus.benchmark.adaptive_formal import adapt_formal_sample
from statebus.benchmark.task_registry import load_c2b_positive_samples
from statebus.contracts import (
    AdaptiveTaskEnvelope,
    PlanProposal,
    PlanStepProposal,
    RiskClass,
    WorkflowMode,
)
from statebus.runtime.capability_registry import CapabilityRegistry
from statebus.runtime.domain_packs import register_generic_adaptive_analysis_capabilities
from statebus.runtime.plan_policy import PlanPolicyValidator
from statebus.runtime.adaptive_runtime import AdaptiveRuntimeRequest, AdaptiveStepResult
from statebus.runtime.driver import RuntimeDriver
from statebus.benchmark.contest_stage1_report import REPORT_INSTRUCTIONS, report_errors, report_feedback
from statebus.integrations.llm import LLMResult, LLMUsage, parse_tagged_json
from scripts.diagnostics import run_adaptive_agent_smoke as worker

FIXTURES = Path(__file__).resolve().parents[1] / 'fixtures/contest_stage1_failures'


def test_codeact_fallback_switch_only_marks_dsl_executor_for_replan():
    sample = next(item for item in load_c2b_positive_samples() if item.task_id == "formal-trend-005")
    case = adapt_formal_sample(sample)
    proposal = PlanProposal(
        proposal_id="switch-test",
        task_id=case.task_id,
        final_output_contract_version="statebus.cited_report.v1",
        steps=(
            PlanStepProposal(
                step_id="retriever",
                role="retriever",
                capability_id="retrieve_table_evidence_v1",
                goal="retrieve",
                output_contract_version="statebus.evidence_pack.v2",
            ),
            PlanStepProposal(
                step_id="executor",
                role="executor",
                capability_id="execute_analysis_dsl_v2",
                goal="analyze",
                input_ref_ids=(case.source_ref_id,),
                input_ref_kinds=("execution_artifact",),
                output_contract_version="statebus.analysis_result.v2",
            ),
            PlanStepProposal(
                step_id="summarizer",
                role="summarizer",
                capability_id="compose_claim_set_v2",
                goal="report",
                output_contract_version="statebus.cited_report.v1",
            ),
        ),
    )
    disabled, _ = _compile_formal_controller_wiring(case, proposal, allow_replan=False)
    enabled, _ = _compile_formal_controller_wiring(case, proposal, allow_replan=True)
    assert disabled.steps[1].on_failure == "fail"
    assert enabled.steps[1].on_failure == "request_replan"


def _codeact_fallback_plan_fixture(*, enabled=True, max_total_attempts=4):
    sample = next(item for item in load_c2b_positive_samples() if item.task_id == "formal-trend-005")
    case = adapt_formal_sample(sample)
    registry = CapabilityRegistry()
    domain_pack = register_generic_adaptive_analysis_capabilities(
        registry,
        analysis_validator_ids=("formal_analysis", "generic_analysis"),
    )
    envelope = AdaptiveTaskEnvelope(
        task_id=case.task_id,
        canonical_task_spec_hash=case.spec.spec_hash,
        workflow_mode=WorkflowMode.ADAPTIVE_BOUNDED,
        domain_pack_id=domain_pack.pack_id,
        allowed_capability_ids=domain_pack.capability_ids,
        allowed_output_contracts=tuple(sorted({
            registry.get(capability_id).output_contract_version
            for capability_id in domain_pack.capability_ids
        })),
        role_cardinality={"retriever": (1, 1), "executor": (1, 2), "summarizer": (1, 1)},
        max_plan_steps=4,
        max_dependency_depth=4,
        max_retrieval_steps=1,
        max_execution_runtime_ms=400_000,
        max_replans=1 if enabled else 0,
        max_total_attempts=max_total_attempts,
        risk_class=RiskClass.BOUNDED_CODE,
        allow_llm_python=True,
    )
    proposal = PlanProposal(
        proposal_id="fallback-replan-test",
        task_id=case.task_id,
        final_output_contract_version="statebus.cited_report.v1",
        steps=(
            PlanStepProposal(
                "retrieve", "retriever", "retrieve_table_evidence_v1", "retrieve",
                output_contract_version="statebus.evidence_pack.v2",
                completion_criteria={
                    "min_locator_count": 1,
                    "required_evidence_types": ["table"],
                    "max_conflicts": 0,
                },
            ),
            PlanStepProposal(
                "analyze", "executor", "execute_analysis_dsl_v2", "analyze",
                input_ref_ids=(case.source_ref_id,),
                input_ref_kinds=("execution_artifact",),
                output_contract_version="statebus.analysis_result.v2",
                completion_criteria={"min_rows": 1, "required_fields": list(case.output_schema)},
            ),
            PlanStepProposal(
                "report", "summarizer", "compose_claim_set_v2", "report",
                output_contract_version="statebus.cited_report.v1",
                completion_criteria={"min_locator_count": 1, "max_conflicts": 0},
            ),
        ),
    )
    compiled, errors = _compile_formal_controller_wiring(case, proposal, allow_replan=enabled)
    assert not any(
        field.startswith(("controller_wiring_", "formal_planner_"))
        for field in errors
    )
    outcome = PlanPolicyValidator(registry, allow_llm_python=True).validate(
        compiled,
        envelope,
        available_input_refs={case.source_ref_id: "execution_artifact"},
    )
    assert outcome.approved_plan is not None, outcome.report.canonical_payload()
    return case, registry, envelope, outcome.approved_plan


def test_codeact_fallback_requires_exhausted_dsl_repair_and_fresh_policy_approval(tmp_path):
    case, registry, envelope, approved = _codeact_fallback_plan_fixture()
    failed_step = next(step for step in approved.steps if step.role == "executor")
    common = {
        "current_plan": approved,
        # DSL may be scheduled before its independent Retriever. The runtime
        # can still replan; the Python replacement then waits for retrieval.
        "completed_step_ids": (),
        "failed_step": failed_step,
        "envelope": envelope,
        "registry": registry,
        "available_input_refs": {case.source_ref_id: "execution_artifact"},
    }

    fallback = _build_codeact_fallback_plan(
        **common,
        error_code="dsl_repair_exhausted:capability_quality_rejected",
    )
    assert fallback is not None
    fallback_plan, fallback_step = fallback
    assert fallback_step.capability_id == "execute_bounded_python_v2"
    assert fallback_step.step_id == "execute-analysis-codeact-fallback"
    assert fallback_step.on_failure == "fail"
    assert fallback_plan.steps[-1].depends_on == (
        "retrieve-evidence",
        fallback_step.step_id,
    )

    dispatched = []

    def replan(current_plan, completed_step_ids, failed_step, error_code):
        candidate = _build_codeact_fallback_plan(
            current_plan=current_plan,
            completed_step_ids=completed_step_ids,
            failed_step=failed_step,
            error_code=error_code,
            envelope=envelope,
            registry=registry,
            available_input_refs={case.source_ref_id: "execution_artifact"},
        )
        return None if candidate is None else candidate[0]

    def execute(step, grant):
        dispatched.append((step.step_id, step.capability_id, grant.attempt_id, grant.grant_hash))
        if step.capability_id == "execute_analysis_dsl_v2":
            return AdaptiveStepResult(
                grant_hash=grant.grant_hash,
                success=False,
                attempt_id=grant.attempt_id,
                error_code="dsl_repair_exhausted:capability_quality_rejected",
            )
        output_kind = (
            "canonical_evidence_pack"
            if step.role == "retriever"
            else "execution_artifact"
        )
        return AdaptiveStepResult(
            grant_hash=grant.grant_hash,
            success=True,
            attempt_id=grant.attempt_id,
            output_refs=(f"output:{step.step_id}",),
            output_ref_kinds=(output_kind,),
        )

    runtime_result = RuntimeDriver().run_adaptive(AdaptiveRuntimeRequest(
        trace_id="codeact-fallback-replan-test",
        task_id=case.task_id,
        canonical_task_spec_hash=case.spec.spec_hash,
        envelope=envelope,
        approved_plan=approved,
        registry=registry,
        runtime_root=str(tmp_path / "runtime"),
        workspace_root_id="workspace",
        available_input_refs={case.source_ref_id: "execution_artifact"},
        execute_step=execute,
        replan_for_step=replan,
    ))
    assert runtime_result.completed and runtime_result.plan_replaced
    assert [item[1] for item in dispatched] == [
        "execute_analysis_dsl_v2",
        "retrieve_table_evidence_v1",
        "execute_bounded_python_v2",
        "compose_claim_set_v2",
    ]
    assert len({item[2] for item in dispatched}) == 4
    assert len({item[3] for item in dispatched}) == 4
    assert runtime_result.session.replan_history[0].trigger_reason.startswith(
        "dsl_repair_exhausted:"
    )

    for error_code in (
        "capability_quality_rejected",
        "subprocess_transport_timeout",
        "llm_python_not_program_enabled",
    ):
        assert _build_codeact_fallback_plan(**common, error_code=error_code) is None

    disabled_case, disabled_registry, disabled_envelope, disabled_plan = (
        _codeact_fallback_plan_fixture(enabled=False)
    )
    disabled_step = next(step for step in disabled_plan.steps if step.role == "executor")
    assert _build_codeact_fallback_plan(
        current_plan=disabled_plan,
        completed_step_ids=("retrieve-evidence",),
        failed_step=disabled_step,
        error_code="dsl_repair_exhausted:capability_quality_rejected",
        envelope=disabled_envelope,
        registry=disabled_registry,
        available_input_refs={disabled_case.source_ref_id: "execution_artifact"},
    ) is None

    budget_case, budget_registry, budget_envelope, budget_plan = (
        _codeact_fallback_plan_fixture(max_total_attempts=3)
    )
    budget_step = next(step for step in budget_plan.steps if step.role == "executor")
    assert _build_codeact_fallback_plan(
        current_plan=budget_plan,
        completed_step_ids=("retrieve-evidence",),
        failed_step=budget_step,
        error_code="dsl_repair_exhausted:capability_quality_rejected",
        envelope=budget_envelope,
        registry=budget_registry,
        available_input_refs={budget_case.source_ref_id: "execution_artifact"},
    ) is None


def test_claim_set_adapter_normalizes_historical_top_level_key_without_changing_claims():
    payload = {
        'claim_set': [{
            'claim_id': 'U-A',
            'claim_text': 'unit_id=U-A risk=true risk_change=initial',
            'claim_type': 'fact',
            'supporting_evidence_item_ids': ['ctx-section-2'],
            'supporting_artifact_ref_ids': ['artifact-1'],
            'numeric_fields': {'variance_pct': -0.2973},
            'uncertainty_note': '',
            'status': 'ready',
        }],
        'status': 'ready',
    }

    claim_set = worker._claim_set_from_payload(payload)

    assert len(claim_set.claims) == 1
    assert claim_set.claims[0].claim_id == 'U-A'
    assert claim_set.claims[0].numeric_fields['variance_pct'] == -0.2973


def test_row_scoped_evidence_prefers_exact_entity_over_shared_risk_label():
    rows = (
        {
            'unit_id': 'U-A',
            'risk_change': 'resolved',
            'note_locator': 'notes_2026-02.md#U-A',
        },
        {
            'unit_id': 'U-B',
            'risk_change': 'new',
            'note_locator': 'notes_2026-02.md#U-B',
        },
    )
    evidence = (
        {'id': 'ctx-section-2', 'text': 'U-A\nU-A 2026-02: A partner promotion was active.'},
        {'id': 'ctx-section-4', 'text': 'U-C\nU-C 2026-02: Supplier prices changed; a new contract is under review.'},
        {'id': 'ctx-section-3', 'text': 'U-B\nU-B 2026-02: Expedited shipments increased fulfillment cost.'},
    )

    selected = _row_scoped_evidence_items(rows, evidence)

    assert [item['id'] for item in selected] == ['ctx-section-2', 'ctx-section-3']


def test_summarizer_prompt_excludes_non_authoritative_profile_history():
    request = (
        'Review the current batch. Use the verified rows.\n'
        'Own profile history:\n[{"unit_id":"U-A","below_20_pct":true}]'
    )

    goal = _summarizer_task_goal(request)

    assert goal == 'Review the current batch. Use the verified rows.'
    assert 'Own profile history' not in goal


def report_fixture(task_id):
    data = json.loads((FIXTURES / f'{task_id}-report.json').read_text())
    rows, sources, evidence = data['verified_rows'], {}, []
    for row, item in zip(rows, data['evidence']):
        entity = row.get('unit_id', row.get('site_id'))
        locator = row.get('note_locator', row.get('event_locator'))
        source_text = item['evidence_text'].split('\n', 1)[1]
        sources[entity] = dict(locator=locator, source_text=source_text, context=source_text.split(': ', 1)[1])
        evidence.append(dict(id=item['evidence_id'], text=item['evidence_text'], locator=locator))
    return data, sources, evidence


def corrected_candidate(data, sources):
    candidate = json.loads(data['raw_responses'][0])
    for row, claim in zip(data['verified_rows'], candidate['claims']):
        entity = row.get('unit_id', row.get('site_id'))
        risk = row.get('below_20_pct', row.get('exceeds_slo'))
        claim['claim_text'] = f"{entity} risk={str(risk).lower()} risk_change={row['risk_change']} {sources[entity]['context']}"
    return candidate


@pytest.mark.parametrize('fixed', [True, False])
def test_real_numeric_copy_failure_uses_one_batch_repair_with_rejected_candidate(monkeypatch, capsys, fixed):
    data, sources, evidence = report_fixture('F08')
    bad = json.loads(data['raw_responses'][0])
    good = deepcopy(bad)
    # Offline model fixture only: production must never overwrite model numbers.
    good['claims'][0]['numeric_fields']['variance_pct'] = data['verified_rows'][0]['variance_pct']
    replies = [bad, good if fixed else bad]
    rendered, checks = [], []

    class Client:
        def describe(self):
            return {'backend': 'offline-regression'}

        async def complete(self, messages, **kwargs):
            rendered.append(messages[0].content)
            return LLMResult(text=json.dumps(replies[len(rendered)-1]), model='offline',
                             usage=LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15))

    monkeypatch.setattr(worker, 'build_llm_client', lambda *_: Client())
    monkeypatch.setattr(worker, 'with_optional_request_journal', lambda client: client)

    def invoke(role, payload):
        monkeypatch.setattr(worker.sys, 'stdin', io.StringIO(json.dumps(payload)))
        worker._run_role_worker(role)
        return SimpleNamespace(**json.loads(capsys.readouterr().out))

    artifact_id = bad['claims'][0]['supporting_artifact_ref_ids'][0]
    payload = dict(task_id='generic-report', claim_set_id='candidate', task_goal='Report verified rows.',
                   verified_artifact_refs=[artifact_id], evidence_items=evidence,
                   report_requirements=REPORT_INSTRUCTIONS, expected_claim_count=2,
                   artifact_summaries=[dict(artifact_ref_id=artifact_id, status='verified', rows=data['verified_rows'])])
    def run():
        return _generate_claim_batch(invoke_role=invoke, payload=payload, batch=data['verified_rows'],
            evidence_items=evidence, report_validator=partial(report_errors, sources=sources),
            report_feedback=report_feedback, record_attempt=lambda w, i, errors: checks.append((i, errors)))
    if fixed:
        assert run().claims[0].numeric_fields['variance_pct'] == -0.2973
        assert checks[-1] == (1, [])
    else:
        with pytest.raises(RuntimeError, match='report_numeric_value:U-A:variance_pct'):
            run()
    assert len(rendered) == 2
    assert checks[0] == (0, ['report_numeric_value:U-A:variance_pct'])
    repair = parse_tagged_json(rendered[1], 'sb-claim-set-v1')['repair_context']
    assert repair['previous_candidate']['claims'][0]['numeric_fields']['variance_pct'] == -2.973
    assert repair['field_feedback'][0]['field'] == 'numeric_fields.variance_pct'
    assert 'decimal position' in repair['field_feedback'][0]['requirement']
    assert '-0.2973' not in str(repair['field_feedback'])  # no scorer answer injected


def test_numeric_copy_validation_is_row_bound_not_artifact_wide():
    data, sources, evidence = report_fixture('F08')
    claims = json.loads(data['raw_responses'][0])['claims']
    for claim, e in zip(claims, evidence):
        claim['citation_locators'] = [e['locator']]
    # A number from a different entity is still wrong even if present in the artifact.
    claims[0]['numeric_fields']['variance_pct'] = data['verified_rows'][1]['variance_pct']
    assert report_errors(data['verified_rows'], claims, sources=sources, evidence_items=evidence) == [
        'report_numeric_value:U-A:variance_pct']


@pytest.mark.parametrize('task_id', ['F01', 'F02', 'O01'])
def test_real_rejected_bodies_report_all_missing_fields(task_id):
    data, sources, evidence = report_fixture(task_id)
    for raw in data['raw_responses']:
        candidate = json.loads(raw)
        errors = report_errors(data['verified_rows'], candidate['claims'], sources=sources, evidence_items=evidence)
        for row in data['verified_rows']:
            entity = row.get('unit_id', row.get('site_id'))
            assert {'report_entity_coverage:' + entity, 'report_risk:' + entity, 'report_change:' + entity} <= set(errors)
    good = corrected_candidate(data, sources)
    for claim, e in zip(good['claims'], evidence):
        claim['citation_locators'] = [e['locator']]
    assert not report_errors(data['verified_rows'], good['claims'], sources=sources, evidence_items=evidence)
    # Adding the required content only to IDs must never make a body pass.
    for claim in good['claims']:
        claim['claim_id'], claim['claim_text'] = claim['claim_text'], 'See background.'
    assert report_errors(data['verified_rows'], good['claims'], sources=sources, evidence_items=evidence)


@pytest.mark.parametrize('fixed', [True, False])
def test_report_repair_reaches_real_role_prompt_with_candidate_and_all_errors(monkeypatch, capsys, fixed):
    data, sources, evidence = report_fixture('F01')
    bad = json.loads(data['raw_responses'][0])
    replies = [bad, corrected_candidate(data, sources) if fixed else bad]
    rendered = []

    class Client:
        def describe(self):
            return {'backend': 'offline-regression'}

        async def complete(self, messages, **kwargs):
            rendered.append(messages[0].content)
            return LLMResult(text=json.dumps(replies[len(rendered)-1]), model='offline',
                             usage=LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15))

    monkeypatch.setattr(worker, 'build_llm_client', lambda *_: Client())
    monkeypatch.setattr(worker, 'with_optional_request_journal', lambda client: client)

    def invoke(role, payload):
        monkeypatch.setattr(worker.sys, 'stdin', io.StringIO(json.dumps(payload)))
        worker._run_role_worker(role)
        return SimpleNamespace(**json.loads(capsys.readouterr().out))

    payload = dict(task_id='generic-report', claim_set_id='candidate', task_goal='Report verified current rows.',
                   verified_artifact_refs=bad['claims'][0]['supporting_artifact_ref_ids'],
                   evidence_items=evidence, report_requirements=REPORT_INSTRUCTIONS, expected_claim_count=2,
                   artifact_summaries=[dict(artifact_ref_id=bad['claims'][0]['supporting_artifact_ref_ids'][0],
                                            status='verified', rows=data['verified_rows'])])
    checks = []
    def run():
        return _generate_claim_batch(invoke_role=invoke, payload=payload, batch=data['verified_rows'], evidence_items=evidence,
            report_validator=partial(report_errors, sources=sources),
            report_feedback=report_feedback,
            record_attempt=lambda w, i, errors: checks.append((i, errors)))
    if fixed:
        candidate = run()
        assert candidate.claims[0].claim_text == replies[1]['claims'][0]['claim_text']
        assert checks[-1] == (1, [])
    else:
        with pytest.raises(RuntimeError, match='formal_summarizer_worker_failed'):
            run()
    assert len(rendered) == 2  # Same single repair budget, even on repeated failure.
    first = parse_tagged_json(rendered[0], 'sb-claim-set-v1')
    second = parse_tagged_json(rendered[1], 'sb-claim-set-v1')
    assert first['report_requirements'] == second['report_requirements'] == REPORT_INSTRUCTIONS
    assert 'repair_context' not in first
    assert second['repair_context']['validation_errors'] == checks[0][1]
    assert second['repair_context']['field_feedback'] == report_feedback(checks[0][1])
    assert second['repair_context']['previous_candidate']['claims'][0]['claim_text'] == bad['claims'][0]['claim_text']
    assert 'edit claim_text, not just claim_id' in rendered[1]
    assert len(checks[0][1]) == 6


@pytest.mark.parametrize('task_id', ['F01', 'F02'])
def test_real_colon_format_failure_has_actionable_non_answer_feedback(task_id):
    data, sources, evidence = report_fixture(task_id)
    responses = json.loads((FIXTURES / f'{task_id}-colon-responses.json').read_text())
    for raw in responses:
        claims = json.loads(raw)['claims']
        for claim, e in zip(claims, evidence):
            claim['citation_locators'] = [e['locator']]
        errors = report_errors(data['verified_rows'], claims, sources=sources, evidence_items=evidence)
        assert errors and all(e.startswith(('report_risk:', 'report_change:')) for e in errors)
        feedback = report_feedback(errors)
        assert len(feedback) == len(errors)
        assert all(f['field'] == 'claim_text' and "literal '='" in f['requirement'] for f in feedback)
        assert not any(word in str(feedback) for word in ('510696', 'resolved', 'initial'))
        for claim in claims:
            claim['claim_text'] = claim['claim_text'].replace('risk: ', 'risk=').replace('risk_change: ', 'risk_change=')
        assert not report_errors(data['verified_rows'], claims, sources=sources, evidence_items=evidence)


def test_real_unsupported_criteria_still_requires_model_to_remove_field(tmp_path):
    from dataclasses import replace
    from statebus.benchmark.contest_stage1 import publish
    from statebus.benchmark.contest_stage1_taskpack import generate_sealed, make_case
    from statebus.benchmark.adaptive_formal_mainline import _compile_formal_controller_wiring, _with_formal_runtime_budgets
    from statebus.contracts import AdaptiveTaskEnvelope, RiskClass, WorkflowMode
    from statebus.runtime.capability_registry import CapabilityRegistry
    from statebus.runtime.domain_packs import register_generic_adaptive_analysis_capabilities
    from statebus.runtime.plan_policy import PlanPolicyValidator
    generate_sealed(tmp_path / 'sealed')
    publish(tmp_path / 'sealed', tmp_path / 'public', 'O01'); publish(tmp_path / 'sealed', tmp_path / 'public', 'O02')
    case = make_case(tmp_path / 'public', 'O02')
    registry = CapabilityRegistry()
    pack = register_generic_adaptive_analysis_capabilities(registry, analysis_validator_ids=('formal_analysis', 'generic_analysis'))
    registry = _with_formal_runtime_budgets(registry)
    envelope = AdaptiveTaskEnvelope(task_id=case.task_id, canonical_task_spec_hash='test',
        workflow_mode=WorkflowMode.ADAPTIVE_BOUNDED, domain_pack_id=pack.pack_id,
        allowed_capability_ids=pack.capability_ids,
        allowed_output_contracts=('statebus.evidence_pack.v2', case.output_contract_version, 'statebus.cited_report.v1'),
        allowed_memory_policies=('none',), role_cardinality={'retriever':(1,1), 'executor':(1,2), 'summarizer':(1,1)},
        max_plan_steps=4, max_execution_runtime_ms=400000, max_replans=0, allow_llm_python=True, risk_class=RiskClass.BOUNDED_CODE)
    proposal = worker._proposal_from_payload(json.loads((FIXTURES / 'O02-unsupported-criteria.json').read_text()))
    compiled, _ = _compile_formal_controller_wiring(case, proposal, allow_replan=False)
    validator = PlanPolicyValidator(registry, allow_llm_python=True)
    rejected = validator.validate(compiled, envelope, available_input_refs={case.source_ref_id:'execution_artifact'})
    assert rejected.approved_plan is None
    assert any(i.error_code == 'completion_criteria_not_supported_by_capability'
               and i.field_path == 'completion_criteria.max_conflicts' for i in rejected.report.issues)
    # Simulate corrected MODEL output. No production Controller drops the field.
    steps = tuple(replace(s, completion_criteria={k:v for k,v in s.completion_criteria.items() if k != 'max_conflicts'})
                  if s.role == 'executor' else s for s in compiled.steps)
    accepted = validator.validate(replace(compiled, steps=steps), envelope,
                                  available_input_refs={case.source_ref_id:'execution_artifact'})
    assert accepted.approved_plan is not None, accepted.report


def test_claim_set_adapter_binds_only_authorized_default_artifact_for_numeric_claims():
    payload = {
        'claims': [
            {
                'claim_id': 'U-A',
                'claim_text': 'unit_id=U-A risk=true risk_change=initial',
                'claim_type': 'fact',
                'supporting_evidence_item_ids': ['ctx-section-2'],
                'numeric_fields': {'variance_cny': -1784},
                'status': 'ready',
            },
            {
                'claim_id': 'U-B-note',
                'claim_text': 'unit_id=U-B background note',
                'claim_type': 'fact',
                'supporting_evidence_item_ids': ['ctx-section-3'],
                'numeric_fields': {},
                'status': 'ready',
            },
        ],
        'status': 'ready',
    }

    claim_set = worker._claim_set_from_payload(
        payload,
        default_artifact_ref_ids=('artifact-F08-batch-1',),
    )

    assert claim_set.claims[0].supporting_artifact_ref_ids == ('artifact-F08-batch-1',)
    assert claim_set.claims[1].supporting_artifact_ref_ids == ()


def test_report_scorer_uses_current_risk_field_for_cross_period_rows():
    rows = [{
        'unit_id': 'U-A',
        'current_under_budget': True,
        'prior_under_budget': True,
        'risk_change': 'still_risk',
        'note_locator': 'notes_2026-06.md#U-A',
        'current_actual_net_revenue_cny': 598041,
        'prior_actual_net_revenue_cny': 598216,
    }]
    sources = {'U-A': {
        'locator': 'notes_2026-06.md#U-A',
        'source_text': 'U-A 2026-06: Refunds are reported separately from booked revenue; deduct them once under the v2 dictionary.',
        'context': 'Refunds are reported separately from booked revenue; deduct them once under the v2 dictionary.',
    }}
    evidence = [{
        'id': 'ctx-section-2',
        'locator': 'notes_2026-06.md#U-A',
        'text': 'U-A\nU-A 2026-06: Refunds are reported separately from booked revenue; deduct them once under the v2 dictionary.',
    }]
    statements = [{
        'claim_id': 'U-A',
        'claim_text': 'unit_id=U-A risk=true risk_change=still_risk Refunds are reported separately from booked revenue; deduct them once under the v2 dictionary.',
        'supporting_evidence_item_ids': ['ctx-section-2'],
        'citation_locators': ['notes_2026-06#U-A'],
        'numeric_fields': {
            'current_actual_net_revenue_cny': 598041,
            'prior_actual_net_revenue_cny': 598216,
        },
    }]
    statements[0]['claim_text'] += ' notes_2026-06.md#U-A'
    assert report_errors(rows, statements, sources=sources, evidence_items=None) == []

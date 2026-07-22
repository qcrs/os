from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from v2.benchmark.contest_evidence_closure import (
    PriorPytestEvidence,
    _pytest_junit_payload,
    _write_checksums,
    capture_contest_runtime_config,
    verify_artifact_checksums,
    write_a0_acceptance_bundle,
)
from v2.benchmark.runtime_modes import (
    audit_contest_treatment_matrices,
    contest_main_treatment_matrix,
    contest_prefix_treatment_matrix,
)
from v2.benchmark.semantic_holdout import runtime_freeze_audit


REPO_ROOT = Path(__file__).resolve().parents[2]
HISTORICAL_FREEZE = (
    REPO_ROOT
    / "docs/improvement/27_statebus_v2_remediation_and_native_latent_execution_20260721"
    / "final_runtime_freeze_snapshot.json"
)


def _runtime_config_environment() -> dict[str, str]:
    values = {
        "STATEBUS_LLM_CONFIG_FILE": str(
            REPO_ROOT / "deploy/statebus_llm.contest_rebuild.yaml"
        ),
        "STATEBUS_PREFIX_POLICY": "off",
        "STATEBUS_LOGIT_POLICY": "off",
        "STATEBUS_LATENT_MODE": "off",
        "STATEBUS_LATENT_HANDOFF_MODE": "off",
        "STATEBUS_LATENT_PROMPT_EMBEDS_ENABLED": "false",
        "STATEBUS_FORMAL_REQUEST_MODE": "serialized",
        "STATEBUS_FORMAL_REQUEST_CONCURRENCY": "1",
    }
    for gate in (
        "STATEBUS_CONTEST_ALLOW_METRICS_CHECK",
        "STATEBUS_CONTEST_ALLOW_TOP_LOGPROBS_PROBE",
        "STATEBUS_CONTEST_ALLOW_FILING_DOWNLOAD",
        "STATEBUS_CONTEST_ALLOW_FORMAL_EXPERIMENTS",
        "STATEBUS_CONTEST_ALLOW_COLD_CACHE",
        "STATEBUS_CONTEST_ALLOW_SERVICE_RESTART",
        "STATEBUS_CONTEST_ALLOW_OPENEULER_VALIDATION",
    ):
        values[gate] = "0"
    return values


def test_canonical_contest_treatment_matrices_change_only_registered_fields() -> None:
    audit = audit_contest_treatment_matrices()

    assert audit["ok"] is True
    assert [
        transition["observed_changed_fields"]
        for transition in audit["audits"]["main"]["adjacent_transitions"]
    ] == [["control_plane"], ["semantic_state"], ["memory_policy"]]
    assert [
        transition["observed_changed_fields"]
        for transition in audit["audits"]["prefix"]["adjacent_transitions"]
    ] == [["prefix_policy"]]
    assert [
        transition["observed_changed_fields"]
        for transition in audit["audits"]["logit"]["adjacent_transitions"]
    ] == [["logit_policy"], ["logit_policy"]]
    for matrix in audit["matrices"].values():
        assert all(lane["latent_mode"] == "off" for lane in matrix)
        assert all(lane["latent_handoff_mode"] == "off" for lane in matrix)
        assert all(
            lane["latent_prompt_embeds_enabled"] is False for lane in matrix
        )


def test_contest_treatment_matrix_rejects_hidden_cross_mechanism_change() -> None:
    lanes = list(contest_main_treatment_matrix())
    lanes[2] = replace(lanes[2], prefix_policy="on")

    audit = audit_contest_treatment_matrices(main=lanes)

    assert audit["ok"] is False
    assert any(
        error["kind"] == "adjacent_treatment_mismatch"
        for error in audit["audits"]["main"]["errors"]
    )


def test_contest_treatment_matrix_rejects_latent_and_empty_matrices() -> None:
    prefix = list(contest_prefix_treatment_matrix())
    prefix[1] = replace(prefix[1], latent_mode="native")

    latent_audit = audit_contest_treatment_matrices(prefix=prefix)
    empty_audit = audit_contest_treatment_matrices(main=())

    assert latent_audit["ok"] is False
    assert any(
        error["kind"] == "latent_treatment_forbidden"
        for error in latent_audit["audits"]["prefix"]["errors"]
    )
    assert empty_audit["ok"] is False


def test_formal_runtime_config_is_non_thinking_latent_off_and_serialized() -> None:
    payload = capture_contest_runtime_config(
        environ=_runtime_config_environment()
    )

    assert payload["ok"] is True
    assert payload["checks"] == {
        "llm_config_file_frozen": True,
        "formal_four_role_non_thinking_contract": True,
        "latent_off": True,
        "baseline_prefix_and_logit_off": True,
        "serialized_concurrency_one": True,
        "external_action_gates_off": True,
        "treatment_matrices_auditable": True,
    }
    assert set(payload["roles"]) == {
        "planner",
        "retriever",
        "executor",
        "summarizer",
    }
    assert all(
        role["enable_thinking"] is False
        and role["json_output"] is True
        and role["temperature"] == 0.0
        for role in payload["roles"].values()
    )


def test_formal_runtime_config_rejects_latent_or_live_action_gate() -> None:
    values = _runtime_config_environment()
    values["STATEBUS_LATENT_MODE"] = "native"
    values["STATEBUS_CONTEST_ALLOW_METRICS_CHECK"] = "1"

    payload = capture_contest_runtime_config(environ=values)

    assert payload["ok"] is False
    assert payload["checks"]["latent_off"] is False
    assert payload["checks"]["external_action_gates_off"] is False


def test_current_runtime_freeze_comparison_requires_explicit_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("STATEBUS_RUNTIME_FREEZE_SNAPSHOT", raising=False)

    with pytest.raises(ValueError, match="runtime_freeze_snapshot_required"):
        runtime_freeze_audit(project_root=REPO_ROOT)

    audit = runtime_freeze_audit(
        HISTORICAL_FREEZE,
        project_root=REPO_ROOT,
    )
    assert audit["current_tree_compared"] is True
    assert audit["snapshot_path"] == str(HISTORICAL_FREEZE)
    assert audit["historical_artifact_audit"]["ok"] is True


def test_a0_pytest_junit_parser_requires_quiet_passing_suite(tmp_path: Path) -> None:
    junit = tmp_path / "pytest.xml"
    junit.write_text(
        '<testsuites><testsuite tests="3" failures="0" errors="0" '
        'skipped="1" time="1.25" /></testsuites>\n',
        encoding="utf-8",
    )
    payload = _pytest_junit_payload(
        junit,
        command="python3 -m pytest -q --junitxml=/tmp/pytest.xml",
        source_git_commit="a" * 40,
    )

    assert payload["ok"] is True
    assert payload["tests"] == 3
    assert payload["passed_tests"] == 2
    with pytest.raises(ValueError, match="a0_test_command_must_use_pytest_q"):
        _pytest_junit_payload(
            junit,
            command="python3 -m pytest",
            source_git_commit="a" * 40,
        )


def test_a0_checksum_verifier_detects_post_freeze_mutation(tmp_path: Path) -> None:
    artifact = tmp_path / "environment.json"
    artifact.write_text('{"ok":true}\n', encoding="utf-8")
    _write_checksums(tmp_path)

    assert verify_artifact_checksums(tmp_path)["ok"] is True
    artifact.write_text('{"ok":false}\n', encoding="utf-8")
    verification = verify_artifact_checksums(tmp_path)
    assert verification["ok"] is False
    assert verification["errors"] == [
        {"kind": "checksum_mismatch", "path": "environment.json"}
    ]


def test_a0_bundle_materializes_required_contract_without_overwrite(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    commit = "a" * 40
    junit = tmp_path / "full-suite.xml"
    junit.write_text(
        '<testsuites><testsuite tests="7" failures="0" errors="0" '
        'skipped="0" time="2.5" /></testsuites>\n',
        encoding="utf-8",
    )
    prior_junit = tmp_path / "prior-failed-suite.xml"
    prior_junit.write_text(
        '<testsuites><testsuite tests="7" failures="2" errors="0" '
        'skipped="0" time="2.0" /></testsuites>\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "v2.benchmark.contest_evidence_closure.capture_contest_source_identity",
        lambda *args, **kwargs: {
            "git_commit": commit,
            "git_branch": "feat/statebus-v2-contest-rebuild",
            "git_clean": True,
            "complete": True,
        },
    )
    monkeypatch.setattr(
        "v2.benchmark.contest_evidence_closure.capture_contest_runtime_config",
        lambda **kwargs: {"ok": True},
    )
    monkeypatch.setattr(
        "v2.benchmark.contest_evidence_closure.capture_contest_a0_environment",
        lambda *args, **kwargs: {"ok": True, "test_executor": {}},
    )
    run_root = tmp_path / "A0" / "fresh-run"

    result = write_a0_acceptance_bundle(
        run_root=run_root,
        pytest_junit=junit,
        tested_git_commit=commit,
        test_command="python3 -m pytest -q --junitxml=/tmp/full-suite.xml",
        project_root=REPO_ROOT,
        environ={},
        prior_pytest_evidence=(
            PriorPytestEvidence(
                junit_path=prior_junit,
                source_git_commit="b" * 40,
                test_user="qcrs",
                nonselection_reason="identity_specific_bwrap_unavailable",
            ),
        ),
    )

    assert result["ok"] is True
    assert result["checksums"]["ok"] is True
    assert {
        "acceptance.json",
        "checksums.sha256",
        "environment.json",
        "pytest-junit.xml",
        "runtime_config.json",
        "source_identity.json",
        "tests.json",
    } == {path.name for path in run_root.iterdir()}
    tests_payload = json.loads(
        (run_root / "tests.json").read_text(encoding="utf-8")
    )
    assert tests_payload["test_executor"] == {}
    assert len(tests_payload["prior_test_runs"]) == 1
    assert tests_payload["prior_test_runs"][0]["status"] == "failed"
    assert tests_payload["prior_test_runs"][0]["source_git_commit"] == "b" * 40
    assert tests_payload["prior_test_runs"][0]["test_user"] == "qcrs"
    assert (
        tests_payload["prior_test_runs"][0]["nonselection_reason"]
        == "identity_specific_bwrap_unavailable"
    )
    assert tests_payload["prior_test_runs"][0]["selected_for_acceptance"] is False
    assert tests_payload["prior_test_runs"][0]["preserved"] is True
    with pytest.raises(FileExistsError, match="already exists"):
        write_a0_acceptance_bundle(
            run_root=run_root,
            pytest_junit=junit,
            tested_git_commit=commit,
            test_command="python3 -m pytest -q",
            project_root=REPO_ROOT,
            environ={},
        )

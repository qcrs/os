from __future__ import annotations

import json
from pathlib import Path

import pytest

from v2.benchmark import contest_accounting
from v2.benchmark.contest_accounting import write_a1_acceptance_bundle
from v2.benchmark.contest_evidence_closure import verify_artifact_checksums


def test_a1_bundle_materializes_h_and_s_fixtures_without_live_actions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        contest_accounting,
        "_source_identity",
        lambda _project_root: {
            "schema_version": "statebus.a1_source_identity.v1",
            "git_commit": "a" * 40,
            "git_tree": "b" * 40,
            "git_branch": "test-a1",
            "worktree_clean": True,
            "dirty_diff_digest": "c" * 64,
            "contract_file_hashes": {},
        },
    )
    junit = tmp_path / "pytest.xml"
    junit.write_text(
        '<testsuites><testsuite tests="2" failures="0" errors="0" '
        'skipped="0" time="1.0" /></testsuites>\n',
        encoding="utf-8",
    )
    run_root = tmp_path / "A1"
    result = write_a1_acceptance_bundle(
        run_root=run_root,
        project_root=Path.cwd(),
        pytest_junit=junit,
        test_command="python3 -m pytest -q tests/v2/test_contest_accounting.py",
    )

    assert result["ok"] is True
    assert result["checksums"]["ok"] is True
    assert verify_artifact_checksums(run_root)["ok"] is True
    assert (run_root / "accounting_contract.json").is_file()
    assert (run_root / "rejection_ledger.json").is_file()
    assert (run_root / "tests/pytest-junit.xml").is_file()
    for lane in ("H0", "H1", "H2", "H3"):
        assert (run_root / "fixtures/memory" / f"{lane}.json").is_file()
    for lane in ("S0", "S1", "S2", "S3"):
        assert (run_root / "fixtures/semantic" / f"{lane}.json").is_file()

    h1 = json.loads((run_root / "fixtures/memory/H1.json").read_text())
    h2 = json.loads((run_root / "fixtures/memory/H2.json").read_text())
    h3 = json.loads((run_root / "fixtures/memory/H3.json").read_text())
    s1 = json.loads((run_root / "fixtures/semantic/S1.json").read_text())
    s2 = json.loads((run_root / "fixtures/semantic/S2.json").read_text())
    assert h1["accounting"]["actual_consumed_count"] == 0
    assert h2["accounting"]["actual_consumed_count"] == 1
    assert h2["accounting"]["action_count"] == 1
    assert h2["accounting"]["behavioral_effect_count"] == 1
    assert h3["accounting"]["actual_consumed_count"] == 0
    assert h3["compatibility_decision"]["verdict"] == "incompatible"
    assert h3["compatibility_decision"]["policy_approved"] is False
    assert "runtime_signature_mismatch" in h3["compatibility_decision"]["reasons"]
    assert s1["accounting"]["cross_process_count"] == 1
    assert s1["accounting"]["released_count"] == 1
    assert s2["perturbation_changed_selected_ids"] is True
    assert s2["matching_permutation_preserved_identity"] is True

    with pytest.raises(FileExistsError, match="a1_run_root_already_exists"):
        write_a1_acceptance_bundle(
            run_root=run_root,
            project_root=Path.cwd(),
        )

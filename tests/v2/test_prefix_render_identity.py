from __future__ import annotations

from pathlib import Path

import pytest

from v2.contracts import CanonicalPrefixEntry
from v2.runtime import (
    build_canonical_shared_evidence_prefix,
    compile_exact_token_prefix_identity,
    compile_prefix_layout,
)


class _ByteChatTokenizer:
    def apply_chat_template(
        self,
        messages,
        *,
        tokenize,
        add_generation_prompt,
        enable_thinking,
    ):
        assert tokenize is True
        rendered = (
            f"thinking={int(enable_thinking)}\n"
            + "\n".join(f"{item['role']}:{item['content']}" for item in messages)
            + ("\nassistant:" if add_generation_prompt else "")
        )
        return list(rendered.encode("utf-8"))


def _entry(stable_key: str, text: str) -> CanonicalPrefixEntry:
    return CanonicalPrefixEntry(
        stable_key=stable_key,
        source_doc_hash="sha256:doc-a",
        locator_kind="table",
        locator_fields={"table_id": "metrics", "row_idx": stable_key},
        evidence_kind="hard_fact",
        rendered_text=text,
    )


def _compiled(role: str, shared_prefix: str):
    return compile_prefix_layout(
        role_label=role,
        instruction=f"Perform the {role} decision.",
        payload_tag=f"sb-{role}-v1",
        payload={"e": shared_prefix, "role": role},
        text_sections=(("Hydrated Evidence", shared_prefix),),
        evidence_blocks=(shared_prefix,),
        handoff_mode="structured_collaboration",
        prefix_alignment_mode="shared_evidence_prefix",
        shared_prefix_text=shared_prefix,
    )


def test_authorized_intersection_is_stable_and_does_not_expand_visibility() -> None:
    common = _entry("row-1", "Revenue was 122.4 MUSD.")
    executor_only = _entry("row-2", "Executor-only detail.")
    summarizer_only = _entry("row-3", "Summarizer-only detail.")

    prefix = build_canonical_shared_evidence_prefix(
        {
            "executor": (common, executor_only),
            "summarizer": (summarizer_only, common),
        }
    )

    assert prefix.eligible is True
    assert prefix.authorized_common_keys == ("row-1",)
    assert "Revenue was 122.4 MUSD." in prefix.rendered_text
    assert "Executor-only" not in prefix.rendered_text
    assert "Summarizer-only" not in prefix.rendered_text


def test_exact_identity_uses_final_chat_template_token_ids() -> None:
    prefix = build_canonical_shared_evidence_prefix(
        {"executor": (_entry("row-1", "Revenue 122.4"),), "summarizer": (_entry("row-1", "Revenue 122.4"),)}
    )
    executor = _compiled("executor", prefix.rendered_text)
    summarizer = _compiled("summarizer", prefix.rendered_text)

    identity = compile_exact_token_prefix_identity(
        _ByteChatTokenizer(),
        {"executor": executor.prompt, "summarizer": summarizer.prompt},
        shared_prefix_text=prefix.rendered_text,
        block_size=8,
    )

    assert identity.eligible is True
    assert identity.exact_token_count >= identity.full_block_token_count > 0
    assert identity.position_base == 0
    assert set(identity.full_request_token_ids_sha256) == {"executor", "summarizer"}
    assert identity.full_request_token_ids_sha256["executor"] != identity.full_request_token_ids_sha256["summarizer"]


def test_exact_identity_fails_closed_when_one_request_has_different_prefix() -> None:
    shared = "same evidence"
    executor = _compiled("executor", shared)
    summarizer = _compiled("summarizer", "different evidence")

    identity = compile_exact_token_prefix_identity(
        _ByteChatTokenizer(),
        {"executor": executor.prompt, "summarizer": summarizer.prompt},
        shared_prefix_text=shared,
        block_size=8,
    )

    assert identity.eligible is False
    assert identity.ineligible_reason == "shared_prefix_not_at_request_start"


def test_real_qwen_chat_template_identity_when_local_tokenizer_is_available() -> None:
    tokenizer_path = Path("/statebus/models/Qwen3-Embedding-0.6B")
    if not tokenizer_path.exists():
        pytest.skip("local Qwen tokenizer is not mounted")
    transformers = pytest.importorskip("transformers")
    tokenizer = transformers.AutoTokenizer.from_pretrained(
        tokenizer_path,
        local_files_only=True,
    )
    shared = "\n".join(["Metric row: revenue_musd=122.4"] * 24)
    executor = _compiled("executor", shared)
    summarizer = _compiled("summarizer", shared)

    identity = compile_exact_token_prefix_identity(
        tokenizer,
        {"executor": executor.prompt, "summarizer": summarizer.prompt},
        shared_prefix_text=shared,
        block_size=16,
        chat_template_kwargs={"enable_thinking": False},
    )

    assert identity.eligible is True
    assert identity.full_block_token_count >= 16

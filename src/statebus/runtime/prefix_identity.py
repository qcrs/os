from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from statebus.contracts.prefix import (
    CanonicalPrefixEntry,
    CanonicalSharedEvidencePrefix,
    ExactTokenPrefixIdentity,
    PrefixParticipantRole,
)
from statebus.utils import sha256_digest, stable_json_dumps


SHARED_PREFIX_LAYOUT_VERSION = "statebus.shared_evidence_prefix.v2"
SHARED_PREFIX_NORMALIZER_VERSION = "statebus.prefix_normalizer.v2"
SHARED_PREFIX_OPEN = "<statebus-shared-prefix-v2>"
SHARED_PREFIX_CLOSE = "</statebus-shared-prefix-v2>"
SHARED_PREFIX_SEPARATOR = "\n\n"


def build_canonical_shared_evidence_prefix(
    entries_by_role: Mapping[str, Sequence[CanonicalPrefixEntry]],
    *,
    participant_roles: tuple[str, ...] = (
        PrefixParticipantRole.EXECUTOR.value,
        PrefixParticipantRole.SUMMARIZER.value,
    ),
    visibility_policy_version: str = "statebus.role_visibility.v1",
) -> CanonicalSharedEvidencePrefix:
    roles = tuple(str(role).strip().lower() for role in participant_roles if str(role).strip())
    if len(roles) < 2 or len(set(roles)) != len(roles):
        return _ineligible_shared_prefix(roles, "invalid_participant_roles", visibility_policy_version)
    if any(role not in {item.value for item in PrefixParticipantRole} for role in roles):
        return _ineligible_shared_prefix(roles, "unsupported_participant_role", visibility_policy_version)
    missing_roles = tuple(role for role in roles if role not in entries_by_role)
    if missing_roles:
        return _ineligible_shared_prefix(
            roles,
            f"missing_role_entries:{','.join(missing_roles)}",
            visibility_policy_version,
        )

    indexed_by_role: dict[str, dict[str, CanonicalPrefixEntry]] = {}
    for role in roles:
        index: dict[str, CanonicalPrefixEntry] = {}
        for entry in entries_by_role[role]:
            if entry.stable_key in index:
                return _ineligible_shared_prefix(
                    roles,
                    f"duplicate_stable_key:{role}:{entry.stable_key}",
                    visibility_policy_version,
                )
            index[entry.stable_key] = entry
        indexed_by_role[role] = index

    common_keys = set(indexed_by_role[roles[0]])
    for role in roles[1:]:
        common_keys.intersection_update(indexed_by_role[role])
    if not common_keys:
        return _ineligible_shared_prefix(
            roles,
            "authorized_visibility_intersection_empty",
            visibility_policy_version,
        )

    common_entries: list[CanonicalPrefixEntry] = []
    for stable_key in common_keys:
        candidates = tuple(indexed_by_role[role][stable_key] for role in roles)
        if len({entry.entry_digest for entry in candidates}) != 1:
            return _ineligible_shared_prefix(
                roles,
                f"conflicting_common_entry:{stable_key}",
                visibility_policy_version,
            )
        common_entries.append(candidates[0])
    common_entries.sort(key=_entry_sort_key)
    ordered_keys = tuple(entry.stable_key for entry in common_entries)
    rendered_text = _render_shared_evidence_entries(tuple(common_entries))
    return CanonicalSharedEvidencePrefix(
        participant_roles=roles,
        authorized_common_keys=ordered_keys,
        entries=tuple(common_entries),
        rendered_text=rendered_text,
        eligible=True,
        prefix_layout_version=SHARED_PREFIX_LAYOUT_VERSION,
        normalizer_version=SHARED_PREFIX_NORMALIZER_VERSION,
        visibility_policy_version=visibility_policy_version,
    )


def shared_prefix_envelope(shared_prefix_text: str) -> str:
    normalized = shared_prefix_text.strip()
    if not normalized:
        return ""
    return (
        f"{SHARED_PREFIX_OPEN}\n"
        f"{normalized}\n"
        f"{SHARED_PREFIX_CLOSE}"
        f"{SHARED_PREFIX_SEPARATOR}"
    )


def compile_exact_token_prefix_identity(
    tokenizer: Any,
    prompts_by_role: Mapping[str, str],
    *,
    shared_prefix_text: str,
    block_size: int,
    min_full_blocks: int = 1,
    chat_template_kwargs: Mapping[str, Any] | None = None,
) -> ExactTokenPrefixIdentity:
    normalized_prompts: dict[str, str] = {}
    for role, prompt in prompts_by_role.items():
        normalized_role = str(role).strip().lower()
        if not normalized_role or normalized_role in normalized_prompts:
            continue
        normalized_prompts[normalized_role] = str(prompt)
    roles = tuple(sorted(normalized_prompts))
    kwargs = {"enable_thinking": False, **dict(chat_template_kwargs or {})}
    message_shape_digest = sha256_digest(
        {
            "roles": list(roles),
            "message_roles": ["user"],
            "message_count": 1,
            "add_generation_prompt": True,
            "chat_template_kwargs": kwargs,
        }
    )
    prefix_text = shared_prefix_text.strip()
    prefix_text_sha256 = sha256_digest(prefix_text.encode("utf-8")) if prefix_text else ""
    prefix_bytes = len(prefix_text.encode("utf-8"))
    if block_size <= 0:
        raise ValueError("block_size must be positive")
    if min_full_blocks <= 0:
        raise ValueError("min_full_blocks must be positive")
    if len(roles) < 2:
        return _ineligible_token_identity(
            roles,
            block_size,
            "insufficient_participants",
            message_shape_digest,
            prefix_text_sha256,
            prefix_bytes,
        )
    envelope = shared_prefix_envelope(prefix_text)
    if not envelope:
        return _ineligible_token_identity(
            roles,
            block_size,
            "shared_prefix_empty",
            message_shape_digest,
            prefix_text_sha256,
            prefix_bytes,
        )
    if any(not normalized_prompts[role].startswith(envelope) for role in roles):
        return _ineligible_token_identity(
            roles,
            block_size,
            "shared_prefix_not_at_request_start",
            message_shape_digest,
            prefix_text_sha256,
            prefix_bytes,
        )

    try:
        request_token_ids = {
            role: _chat_request_token_ids(tokenizer, normalized_prompts[role], kwargs)
            for role in roles
        }
        sentinel_a = _chat_request_token_ids(
            tokenizer,
            envelope + '<statebus-role-suffix-v2 role="identity-a">\nA',
            kwargs,
        )
        sentinel_b = _chat_request_token_ids(
            tokenizer,
            envelope + '<statebus-role-suffix-v2 role="identity-b">\nB',
            kwargs,
        )
    except (TypeError, ValueError, RuntimeError) as exc:
        return _ineligible_token_identity(
            roles,
            block_size,
            f"tokenizer_or_template_unavailable:{type(exc).__name__}",
            message_shape_digest,
            prefix_text_sha256,
            prefix_bytes,
        )
    if any(not token_ids for token_ids in request_token_ids.values()):
        return _ineligible_token_identity(
            roles,
            block_size,
            "empty_request_token_ids",
            message_shape_digest,
            prefix_text_sha256,
            prefix_bytes,
        )

    actual_lcp = _longest_common_prefix(tuple(request_token_ids.values()))
    boundary_lcp = _longest_common_prefix((sentinel_a, sentinel_b))
    exact_token_ids = _longest_common_prefix((actual_lcp, boundary_lcp))
    full_block_token_count = (len(exact_token_ids) // block_size) * block_size
    required_tokens = block_size * min_full_blocks
    eligible = full_block_token_count >= required_tokens
    reason = "" if eligible else "insufficient_full_prefix_blocks"
    return ExactTokenPrefixIdentity(
        participant_roles=roles,
        exact_token_ids=tuple(exact_token_ids),
        full_request_token_ids_sha256={
            role: sha256_digest(list(token_ids))
            for role, token_ids in request_token_ids.items()
        },
        block_size=block_size,
        full_block_token_count=full_block_token_count,
        eligible=eligible,
        ineligible_reason=reason,
        message_shape_digest=message_shape_digest,
        shared_prefix_text_sha256=prefix_text_sha256,
        prefix_bytes=prefix_bytes,
    )


def _chat_request_token_ids(
    tokenizer: Any,
    prompt: str,
    chat_template_kwargs: Mapping[str, Any],
) -> tuple[int, ...]:
    apply_template = getattr(tokenizer, "apply_chat_template", None)
    if not callable(apply_template):
        raise RuntimeError("apply_chat_template is required for exact request identity")
    messages = [{"role": "user", "content": prompt}]
    kwargs = {
        "tokenize": True,
        "add_generation_prompt": True,
        **dict(chat_template_kwargs),
    }
    try:
        value = apply_template(messages, **kwargs)
    except TypeError as exc:
        raise RuntimeError("chat template kwargs are not supported by the request tokenizer") from exc
    if isinstance(value, str):
        raise RuntimeError("chat template did not return token ids")
    if hasattr(value, "tolist"):
        value = value.tolist()
    if value and isinstance(value[0], (list, tuple)):
        if len(value) != 1:
            raise ValueError("chat template returned multiple token sequences")
        value = value[0]
    try:
        return tuple(int(token_id) for token_id in value)
    except (TypeError, ValueError) as exc:
        raise ValueError("chat template returned invalid token ids") from exc


def _longest_common_prefix(sequences: Sequence[Sequence[int]]) -> tuple[int, ...]:
    if not sequences:
        return ()
    shortest = min(len(sequence) for sequence in sequences)
    length = 0
    for index in range(shortest):
        value = sequences[0][index]
        if any(sequence[index] != value for sequence in sequences[1:]):
            break
        length += 1
    return tuple(int(value) for value in sequences[0][:length])


def _entry_sort_key(entry: CanonicalPrefixEntry) -> tuple[str, str, str, str, str]:
    return (
        entry.source_doc_hash,
        entry.locator_kind,
        stable_json_dumps(dict(sorted(dict(entry.locator_fields).items()))),
        entry.evidence_kind,
        entry.stable_key,
    )


def _render_shared_evidence_entries(entries: tuple[CanonicalPrefixEntry, ...]) -> str:
    lines = [
        f"prefix_layout_version={SHARED_PREFIX_LAYOUT_VERSION}",
        f"normalizer_version={SHARED_PREFIX_NORMALIZER_VERSION}",
        f"evidence_entry_count={len(entries)}",
        "evidence:",
    ]
    lines.extend(stable_json_dumps(entry.canonical_payload()) for entry in entries)
    return "\n".join(lines)


def _ineligible_shared_prefix(
    roles: tuple[str, ...],
    reason: str,
    visibility_policy_version: str,
) -> CanonicalSharedEvidencePrefix:
    return CanonicalSharedEvidencePrefix(
        participant_roles=roles,
        authorized_common_keys=(),
        entries=(),
        rendered_text="",
        eligible=False,
        ineligible_reason=reason,
        prefix_layout_version=SHARED_PREFIX_LAYOUT_VERSION,
        normalizer_version=SHARED_PREFIX_NORMALIZER_VERSION,
        visibility_policy_version=visibility_policy_version,
    )


def _ineligible_token_identity(
    roles: tuple[str, ...],
    block_size: int,
    reason: str,
    message_shape_digest: str,
    shared_prefix_text_sha256: str,
    prefix_bytes: int,
) -> ExactTokenPrefixIdentity:
    return ExactTokenPrefixIdentity(
        participant_roles=roles,
        exact_token_ids=(),
        full_request_token_ids_sha256={},
        block_size=block_size,
        full_block_token_count=0,
        eligible=False,
        ineligible_reason=reason,
        message_shape_digest=message_shape_digest,
        shared_prefix_text_sha256=shared_prefix_text_sha256,
        prefix_bytes=prefix_bytes,
    )

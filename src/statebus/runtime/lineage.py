from __future__ import annotations

from dataclasses import dataclass

from statebus.contracts import RefStatus
from statebus.refs import ExecutionArtifactRef, SemanticStateRef


@dataclass(frozen=True)
class TaskLineageView:
    task_id: str
    semantic_state_ids: tuple[str, ...]
    candidate_artifact_ids: tuple[str, ...]
    verified_artifact_ids: tuple[str, ...]
    replay_restorable_artifact_ids: tuple[str, ...]


def build_task_lineage_view(
    *,
    task_id: str,
    semantic_states: list[SemanticStateRef],
    artifacts: list[ExecutionArtifactRef],
) -> TaskLineageView:
    return TaskLineageView(
        task_id=task_id,
        semantic_state_ids=tuple(sorted(state.state_id for state in semantic_states)),
        candidate_artifact_ids=tuple(
            sorted(
                artifact.artifact_id
                for artifact in artifacts
                if artifact.verification_state == RefStatus.CANDIDATE
            )
        ),
        verified_artifact_ids=tuple(
            sorted(
                artifact.artifact_id
                for artifact in artifacts
                if artifact.verification_state == RefStatus.VERIFIED
            )
        ),
        replay_restorable_artifact_ids=tuple(
            sorted(artifact.artifact_id for artifact in artifacts if artifact.replay_ready)
        ),
    )

# StateBus v2 Planning

这个目录只保留当前 `v2` clean-room 开发仍需要的规划与合同。

## 当前入口

- `adaptive_mainline_semantic_state_integration_plan_20260719.md`: 当前 `feat/yzm-v2-migration` 的 Adaptive 主 Runtime、真实 embedding state、hybrid memory、Docker 与静默测试实施合同和执行 Prompt。
- `statebus_v2_clean_room_rebuild_plan_20260625.md`: v2 clean-room rebuild 主规划。
- `statebus_v2_container_refactor_bootstrap_20260627.md`: v2 container / openEuler bootstrap 规划。
- `continuous_task_family_design_20260630.md`: continuous task family 设计。
- `implementation_plan.md`: 赛题要求拆解与历史 host-mainline 规划，按当前 README 和 truth audit 校准后使用。

## 当前合同

- `runtime_state_machine_contract.md`
- `task_compiler_contract.md`
- `ref_registry_and_manifest_storage_contract.md`
- `runtime_compatibility_signature_contract.md`
- `semantic_provenance_and_hydration_contract.md`
- `execution_artifact_and_workspace_contract.md`
- `canonical_evidence_pack_and_fan_in_contract.md`
- `replay_admissibility_contract.md`
- `benchmark_quality_floor_contract.md`
- `telemetry_event_contract.md`
- `lifecycle_matrix.md`
- `ephemeral_neural_state_boundary_note.md`
- `kv_cache_and_embedding_interaction_note.md`

旧 host-mainline、v1/v3 benchmark/headline 规划已归档到 `../archive/legacy_202606_host_mainline/planning/`。

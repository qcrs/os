# Ref Registry And Manifest Storage Contract

日期：2026-06-26  
状态：`v2` 跨合同文档  
作用：定义 `StateRef`、`ExecutionArtifactRef`、`HydrateManifest`、`CanonicalEvidencePack` 等引用对象在控制面、索引面和重量级元数据面的正式落点。

---

## 1. 目标

这份合同要定死：

1. 控制总线上到底传什么
2. SQLite 到底存什么
3. CAS / sidecar 到底存什么
4. 为什么不走 `SQLite-only`

---

## 2. 三层落点

### 2.1 控制面

`SystemPacket` 只传：

1. `state_ref_ids[]`
2. `artifact_ref_ids[]`
3. 必要的轻量 header

不传：

1. 大 JSON manifest
2. 完整 artifact metadata blob

### 2.2 索引面

SQLite 负责：

1. `ref_id -> kind/storage/status`
2. `manifest_hash`
3. `blob_hash`
4. `root_id`
5. `relpath`
6. 可查询的小字段

### 2.3 重量级元数据面

CAS sidecar JSON 负责：

1. `HydrateManifest`
2. `CanonicalEvidencePack`
3. 大型 provenance metadata
4. 输出 manifest

---

## 3. 为什么不建议 `SQLite-only`

如果把大 metadata 全塞 SQLite：

1. UDS 控制包虽轻，但查询后的对象仍会过度膨胀
2. 大 JSON 更新和审计不方便
3. 与 CAS/blob hash 的关系不清楚

因此更稳的默认方案是：

1. SQLite 做 registry/index
2. CAS sidecar 做重量级 schema

---

## 4. 建议最小 registry 字段

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class RefRegistryEntry:
    ref_id: str
    ref_kind: str
    storage_kind: str
    status: str
    blob_hash: str = ""
    manifest_hash: str = ""
    root_id: str = ""
    relpath: str = ""
    workspace_relpath: str = ""
    schema_version: str = ""
```

---

## 5. 各对象默认落点

### 5.1 `SemanticStateRef`

1. 控制面：`state_ref_id`
2. SQLite：shape/dtype/storage/manifest_hash/status
3. CAS sidecar：必要时放 `HydrateManifest`

### 5.2 `ExecutionArtifactRef`

1. 控制面：`artifact_ref_id`
2. SQLite：`artifact_type/root_id/relpath/blob_hash/size/status`
3. CAS sidecar：输出 manifest、validator report

当前冻结决定：

4. `ExecutionArtifactRef` 首轮就作为正式 ref family 建表与建索引
5. 不再以“临时塞进 StateRef.metadata”作为主路径

### 5.3 `HydrateManifest`

1. 不直接进入控制面
2. 以 `manifest_hash` 由 SQLite 索引
3. 正文存 sidecar JSON / CAS blob

### 5.4 `CanonicalEvidencePack`

1. 控制面只传 `pack_id` 或 `state_ref_id`
2. SQLite 存 `pack_hash` 与摘要字段
3. 正文存 sidecar JSON / CAS blob

---

## 6. 查找路径

默认 lookup 流程：

```text
packet -> ref_id
  -> sqlite registry
  -> small fields / manifest hash
  -> cas sidecar json if needed
```

这样控制面永远保持小包，而 metadata 仍可审计。

---

## 7. `MVP` 实现建议

1. 先统一 `ref_registry` 表
2. 先把 `HydrateManifest` 和 output manifest 做 sidecar JSON
3. 先不追求所有 metadata 一步到位

---

## 8. 验收建议

建议最小验收：

1. 控制包不包含大型 metadata
2. 给定 `state_ref_id` 能经 registry 找到 manifest
3. 给定 `artifact_ref_id` 能找到输出 manifest 与 blob hash
4. sidecar 缺失时，系统能明确报 `ref_manifest_missing`

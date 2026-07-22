# 04 企业垂类数据、预处理与两组十轮任务设计

> **事实来源**：五个现有 continuous-family manifest/原始样本、[`readiness audit`](../../reports/statebus_v2_contest_readiness_audit_20260722.md)，以及 XBRL International 的公开 filings repository 说明。
> **设计假设**：未来可下载并冻结 English ESEF/UKSEF Inline XBRL reports；正式前须完成 source terms、上游 authority、redistribution 和 parser validation gate。本轮未下载数据。
> **待验证实验**：R11 provenance/holdout、R3 两组十轮、R12 natural capability coverage；所有正式数据 hash 和 gold 在运行前冻结。

文档导航：[索引](README.md) | [00 决策与包装](00_executive_decision_and_packaging.md) | [01 现状与整改](01_current_state_and_remediation.md) | [02 Prefix](02_prefix_engine_local_reuse_design.md) | [03 LogitState](03_logitstate_core_chain_design.md) | [04 数据与任务](04_vertical_data_preprocess_and_task_design.md) | [05 实验](05_experiment_matrix_metrics_and_statistics.md) | [06 实施与验收](06_implementation_plan_and_acceptance.md) | [07 辅助核对](07_auxiliary_verification_record.md)

## 1. 数据决定

### 1.1 正式 headline 数据源

选择 [filings.xbrl.org](https://filings.xbrl.org/docs/about) 的公开 Inline XBRL 企业披露作为 formal source family。该站由 XBRL International 提供 ESEF/UKSEF 等 filing repository，包含 viewer、xBRL-JSON 和原始 XBRL Report Package，记录 source authority 和 SHA-256；其当前 Terms of use 页面写明数据使用方式“at present, there are no restrictions”。

选择理由：

- 真实企业、监管披露、表格与长文本同源，符合企业财报/经营分析叙事；
- 有 LEI、period、filing system、source authority、report hash，便于 provenance；
- xBRL-JSON 可做 deterministic numeric extraction，report package 可做 narrative/locator retrieval；
- 可完全离线冻结，避免 formal run 联网；
- 同一披露可支持 semantic/table 两种自然任务，而无需把 route 写进提示。

约束：repository 自述不完整，部分 filings 有 validation error/warning；页面上的 hash 不能替代本地 raw package hash。正式纳入前必须记录页面 terms snapshot hash、上游 OAM、filing validation状态和允许的再分发范围。若 terms/rights gate 未通过，数据不得复制进提交包，只保留可重取 ledger/derived facts，或改用通过审查的来源版本。

### 1.2 备选/交叉来源

[SEC EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) 只作为 future source-disjoint holdout 备选。下载必须遵守 [SEC developer/Fair Access](https://www.sec.gov/developer) 和 per-filing rights review；本轮只读页面请求遇到 rate-threshold 页面，因此不把 SEC 数据写成已取得或已许可。不能为补数据临时绕过访问策略。

### 1.3 数据分层决定

| 当前 family/source | 未来层级 | 保留用途 | 禁止用途 |
| --- | --- | --- | --- |
| `formal_financial_reports_v1` ACME/BETA | dev contract fixture | cross-period、schema drift、rejection、long lineage 回归 | 真实企业、公开来源、external generalization |
| `cross_period_financial_v1` ACME/BETA | dev memory/replay fixture | validated strategy reuse 与计算依赖 | formal headline |
| `formal_operating_metrics_v1` disease/weather | diagnostic | CSV parser、missingness/outlier/groupby、CodeAct regression | 企业经营垂类主张；当前 `formal_primary` 标签需未来降级/迁移 |
| `csv_table_profile_v1` disease/weather | diagnostic | artifact-first table flow | 企业财报/运营泛化 |
| `kv_prefix_reuse_v1` Orion/Nova | mechanism-only | P-A/P-B schedule、long-prefix、quality deterministic | P-C 业务泛化；当前 manifest 已标 `demo_secondary` |
| `semantic_holdout` | internal mechanism holdout | selected-ID/hydration counterfactual | 第三方/开放域 holdout |
| 新 `public_financial_chain_v1` | formal primary | 财务跨期 10 轮、L0-L3/R1-R4 | 未过 R11 前不得发布 |
| 新 `public_operating_chain_v1` | formal primary | operating KPI + narrative/table 10 轮、R12 | 未过 R11 前不得发布 |

现有文件不在本轮修改。未来变更必须新建 manifest version，旧 family/artifact 保留。

## 2. Source 与许可/terms ledger

每个 raw filing 一行，至少包含：

| 字段 | 说明 |
| --- | --- |
| `source_record_id` | 本地不可变 ID |
| `repository/source_url` | filings.xbrl.org filing API/page；无追踪参数 |
| `upstream_authority/source_authority_url` | OAM/filing authority identity |
| `entity_name/LEI/country/language` | issuer metadata；formal 默认 English |
| `filing_system/reporting_period/added_date` | ESEF/UKSEF 和时间范围 |
| `repository_report_sha256` | repository 提供的 full hash |
| `retrieved_at_utc/retriever_version/user_agent` | 可复现访问上下文 |
| `terms_url/terms_snapshot_sha256/terms_checked_at` | 使用条款证据 |
| `redistribution_status/rights_reviewer` | `allowed/derived_only/link_only/rejected`；默认未审查即 rejected |
| `raw_package_sha256/raw_size/media_type` | 下载后本地 hash；不能只信 URL |
| `validation_status/errors/warnings` | XBRL parser + repository 状态 |
| `supersedes/amendment_relation` | 修订 filing 不混为新 period |
| `split` | dev/calibration/validation/test；freeze 后不可移动 |
| `ledger_schema_version` | versioned contract |

License/terms 不是自由文本备注：formal freeze 要求 `terms_snapshot_sha256` 和 `redistribution_status != rejected`。如果只允许 derived facts，提交包不含 raw report，只含 hash、locator、转换后可分发对象和重取说明。

## 3. 可复现 ingestion pipeline

```text
source roster (pre-registered selection rule)
  -> fetch raw Report Package + xBRL-JSON
  -> verify repository hash/local SHA-256/terms status
  -> safe unpack (path traversal/size/member limits)
  -> deterministic XBRL parser + validation report
  -> canonical filing metadata/entity/period/unit/context table
  -> canonical financial/operating fact table
  -> canonical narrative blocks + source locators
  -> deduplicate by source hash + fact context
  -> evidence catalog/chunk registry/schema profile
  -> task manifest (runtime-visible contract only)
  -> separately authored gold + validator
  -> split/freeze/checksum ledger
```

建议未来文件：

```text
v2/data/public_filings/
  source_contracts.py
  fetch_xbrl_filings.py
  safe_report_package.py
  parse_xbrl_json.py
  canonicalize_filing.py
  build_evidence_catalog.py
  freeze_dataset.py
v2/benchmark/samples/public_enterprise_v1/
  source_ledger.jsonl
  transform_manifest.json
  split_manifest.json
  corpus/                 # only redistributable normalized objects
  task_manifests/
  gold_private/           # excluded from runtime surface
```

### 3.1 canonical facts

每条 numeric fact：`entity_lei`、concept QName、human label、period start/end/instant、dimensions、unit、decimals/precision、raw lexical value、normalized decimal、filing/source hashes、document/table locator、parser version。不得根据任务 gold 丢弃其他同行/同表 facts。

### 3.2 canonical narrative

每个 block：section heading path、language、text hash、source DOM/XBRL fact ID、character offsets、page/anchor（若可靠）、source hashes。只做 deterministic whitespace/Unicode/boilerplate normalization；原文和 normalized hash 都保留。

### 3.3 稳定排序与 locator

```text
financial facts: (entity_lei, period_end, concept_qname, dimensions_digest,
                  unit, source_fact_id)
narrative:       (entity_lei, period_end, heading_path, source_dom_order,
                  source_fact_id)
```

同事实冲突不静默覆盖；形成 `ConflictItem`，validator 依据 filing amendment/current-period policy选择或拒绝。

## 4. 允许与禁止的预处理

| 允许 | 禁止 |
| --- | --- |
| safe unpack、格式验证、单位/日期/decimal规范化 | 根据 expected answer 只保留目标行/段 |
| XBRL context/dimension解析、表结构重建 | 把 gold、正确 route/tool、candidate rank 写进 corpus metadata |
| deterministic section/chunk、locator和hash | 用 LLM 按题目预总结成答案式 evidence |
| schema alias从公开 taxonomy/extension mapping产生并版本化 | 在 test 上人工修 alias/threshold 后覆盖原 manifest |
| 去重、language过滤、PII/security清洗并记录规则 | Runtime 读取 `expected_facts`/private gold |
| parser error/warning保留，必要时 formal reject | 删除失败 filing 而不更新 selection ledger |
| 内容无关的 size/validity/period选择规则 | 因模型表现差而替换 test issuer/period |

“预处理不预解题”审计必须对 runtime workspace、rendered role requests 和 source corpus 做 gold substring/digest 扫描。

## 5. Source roster 与 split 冻结

### 5.1 纳入规则（在看任务答案前）

- English ESEF/UKSEF report；entity LEI 和 period 可解析；
- 至少三个相邻 fiscal periods或同 issuer 多个 annual/interim filings；
- 至少包含 revenue、operating profit/income 或 cash-flow 等可映射财务概念；
- 至少一个可审计的 custom operating KPI/table或 management narrative + numeric fact组合；
- report package/local xBRL-JSON hash匹配；无 fatal validation error；
- terms/redistribution review通过；
- 单文档/解压总体积在预注册资源上限；
- 不以模型是否答对作为纳入条件。

### 5.2 分割

| split | 用途 | 隔离规则 |
| --- | --- | --- |
| dev | parser、任务模板、Prefix P-A、Logit feature开发 | issuer/period IDs公开；可反复使用 |
| calibration | Logit calibration和阈值 | issuer-disjoint from dev；不进入最终质量比较 |
| validation | 预演 manifest/quality gate | issuer-disjoint；最多一次调试版本，修改即新 dataset version |
| external test holdout | R1-R4/R7/R10-R12 formal | issuer-disjoint，roster在 runtime/policy freeze后由独立作者按 hash-seeded rule选择 |

`selection_seed = sha256(frozen_source_index_hash + contest_dataset_version)`；按 country/language/size strata 后排序选取，防止人工挑容易样本。任务 author 与 gold author 分离；至少一名 reviewer 不参与 Runtime/threshold开发。

## 6. Gold 隔离与可见性

### 6.1 独立 gold

Gold 文件记录：task ID、source record/hash、answer fields、Decimal值与 tolerance、单位、每个答案的 source locator、计算公式、author/reviewer、created_at、gold schema/version/hash。Gold 不包含 prompt 建议、route或 tool。

### 6.2 Runtime 可见/不可见

| Runtime/role 可见 | 仅 benchmark validator 可见 |
| --- | --- |
| request、CanonicalTaskSpec、公开 corpus、locator、allowed tools、prior verified refs | expected numeric/text labels、valid candidate set oracle、quality thresholds、split seed私有部分 |

runner 在调用 role path 前 materialize public payload；validator在角色完成后单独读取 gold。每个 run 保存 `gold_visibility_audit` 和 role request hashes，不保存完整 raw completion到公开报告。

## 7. 十轮链 A：公开财报跨期分析

Family：`public_financial_chain_v1`。输入为 issuer A 三个连续期间的 filing 与 issuer B 对照期间；所有具体 accession/source IDs 在 freeze manifest 中固定。

| 轮 | 输入与依赖 | 可消费对象 / 复用等级 | 不可跳过 | 新产物 | 质量门 |
| --- | --- | --- | --- | --- | --- |
| A1 | A 的 T-2/T-1/T raw canonical filings；无依赖 | none | source/hash/XBRL validation、period/unit检查 | `FilingIndexRef(A)`、schema/evidence catalog | 三期、source locator、无 gold可见 |
| A2 | A1；抽取 A T-2 revenue | index assist | 当前 source fact resolve与单位校验 | verified `RevenueFactRef(A,T-2)`、generic extraction recipe | Decimal/tolerance、concept/context/locator一致 |
| A3 | A1/A2；抽取 A T-1 revenue | strategy assist或 validated recipe，禁止 fact replay | 当前 period/source重新取值 | `RevenueFactRef(A,T-1)`、recipe receipt | 值/单位/locator；actual recipe receipt |
| A4 | A1/A2/A3；抽取 A T revenue | strategy assist/validated recipe | 同上；schema drift必须解析 | `RevenueFactRef(A,T)`、schema-resolution receipt | 值与 period；incompatible recipe则 recompute |
| A5 | A2-A4；计算三期 revenue growth | artifact assist | 三个输入hash/units、公式验证 | `RevenueTrendArtifactRef(A)` | values、YoY/period delta、lineage完整 |
| A6 | A1/A2；抽取 A T-2 operating profit | strategy assist，不能复用 revenue值 | current fact/概念校验 | `OperatingProfitFactRef(A,T-2)` | concept/单位/locator |
| A7 | A1/A6；抽取 A T-1/T operating profit series | validated recipe 可重用 | 两期当前 source resolve | two facts + series artifact | 两值、source/period、recipe receipt |
| A8 | A2-A7；计算 revenue/operating-margin trend | artifact assist | 每期 revenue/profit均存在；除零/单位门 | `MarginTrendArtifactRef(A)` | 三期 margin、趋势、公式和 citations |
| A9 | B T filing；依赖 A1/A8；抽取 B T revenue/profit | A 的 fact/memory 不兼容；generic strategy可降级 assist | issuer/source contract；必须记录 rejection/recompute | `ComparisonInputRef(B,T)`、rejection receipt | B值/locator；无 cross-issuer fact replay |
| A10 | A5/A8/A9；跨 issuer 结论 | verified artifacts assist | citations、conflict、quality floor | final `CitedFinancialAnalysisRef` + MemoryRef candidate | 所有结论可追溯；不得新造数值 |

该链区分：事实 Ref、generic strategy、validated recipe、artifact assist；没有把“同一道题重复十次”当连续任务。

## 8. 十轮链 B：经营 KPI 与风险核验

Family：`public_operating_chain_v1`。输入为 issuer C 三期披露中的 custom operating KPI/narrative，以及 issuer D 对照披露。

| 轮 | 输入与依赖 | 可消费对象 / 复用等级 | 不可跳过 | 新产物 | 质量门 |
| --- | --- | --- | --- | --- | --- |
| B1 | C 三期 filings；无依赖 | none | source/hash、extension taxonomy、narrative locator | `OperatingEvidenceIndexRef(C)` | KPI候选和section coverage完整 |
| B2 | B1；抽取 C T-2 KPI series point | index assist | custom concept/label/unit/context校验 | `KpiFactRef(C,T-2)`、KPI mapping | value/unit/locator |
| B3 | B1/B2；抽取 C T-1 同 KPI | strategy assist | current source resolve；不 fact replay | `KpiFactRef(C,T-1)` | schema mapping与值正确 |
| B4 | B1-B3；抽取 C T KPI，含 extension/schema drift | validated recipe或 recompute | alias由taxonomy/ledger，不由gold | `KpiFactRef(C,T)`、schema drift receipt | 值/period/alias provenance |
| B5 | B2-B4；检测 KPI change/anomaly | artifact assist | formula、missingness和threshold version | `KpiAnomalyArtifactRef` | delta/flag deterministic |
| B6 | B1/B5；检索 management narrative 中的候选原因 | semantic StateRef selection | 不得把 gold cause预筛入 corpus；locator必须保留 | `NarrativeEvidencePackRef` | semantic selected IDs、coverage、citations |
| B7 | B5/B6；验证“披露是否支持原因” | artifact + evidence assist | claim/evidence entailment和冲突门 | `VerifiedOperatingClaimRef` | claim只含已支持内容；unsupported显式拒绝 |
| B8 | D T filing；依赖 B1/B7；抽取同类 KPI/叙事 | C 的 fact/artifact不兼容；strategy可 assist | issuer/definition compatibility | D facts/evidence + rejection/recompute receipt | definition/unit可比性，不可比则拒绝比较 |
| B9 | B7/B8；跨 issuer 风险比较 | verified artifacts | definition/period/normalization/citation | `OperatingRiskComparisonRef` | 可比字段准确；不可比项不强算 |
| B10 | B1-B9；最终 cited operating report | verified artifacts + narrow memory assist | complete lineage、no unverified number、quality floor | final report + MemoryRef candidate | KPI、原因、风险、rejection全可追溯 |

B6 自然要求 semantic retrieval，B2-B5 自然要求 table retrieval；R12 只观察实际选择，不在 manifest 中写强制正确 route。`required_tools` 可给 capability 上界，但 gold/expected route不可进入 prompt。

## 9. Prefix/LogitState 与任务数据的关系

- Orion/Nova 继续用于 Prefix P-A/P-B mechanism development；P-C 必须在新公开 chains 上独立运行。
- 新公开数据的 shared prefix 只来自 semantic selection 后、参与角色授权交集，详见 [`02`](02_prefix_engine_local_reuse_design.md)。
- Logit calibration 使用 dev/calibration split的闭集 tool/recipe选择；formal holdout不用于选 alias/feature/threshold，详见 [`03`](03_logitstate_core_chain_design.md)。
- L0-L3 主矩阵中 Prefix/LogitState关闭；不得让新数据任务同时改变多个机制。

## 10. 数据 freeze 与验收

formal dataset freeze 必须产出：

```text
source_ledger.jsonl + sha256
terms_snapshots/ + checksums
raw_package_checksum_manifest.json
transform_manifest.json (code/config/container hashes)
canonical_corpus_manifest.json
task_manifest.json
gold_manifest_private.json
split_manifest.json
runtime_visibility_manifest.json
dataset_card.md
```

R11 通过条件：

- 所有 formal samples 具 source/terms/raw/transform/output/gold hashes；
- test issuer/period 与 dev/calibration/validation 不重叠，选择过程可重放；
- task author/gold author/reviewer记录齐全；
- role requests不含 gold/expected facts/route hint；
- 两 family 各恰好 10 个 dependency-closed rounds；
- parser/validator从 raw重建 canonical output hash；
- validation error、缺失 source、rights不清或 Runtime gold leakage 任一发生即阻断 formal；
- 数据冻结后修改任何 task/gold/transform须新 version、新 manifest、新 run root，旧失败保留。

## 11. 失败与降级

| 失败 | 降级 |
| --- | --- |
| filings terms/redistribution不明确 | link/derived-only或拒绝该 source；不假称开放许可 |
| source API/站点不可复取 | 使用已冻结且允许分发的 raw package；否则该数据不可复现，退出 formal |
| fatal XBRL validation/parser mismatch | 保留失败 ledger，按预注册规则拒绝；不人工修 test |
| custom KPI跨 issuer定义不可比 | 任务输出“不可比”并通过拒绝质量门，不硬算 |
| 公开 holdout规模不足 | 只称 public-source pilot，不称泛化 |
| natural semantic/table coverage不足 | R12 如实报告并缩窄 capability claim，不改 route gold |
| 任一 10轮依赖失败 | family不达成稳定性 gate；失败保留，不用其他 family轮次凑数 |

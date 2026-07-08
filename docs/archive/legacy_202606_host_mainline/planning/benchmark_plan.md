 # StateBus Benchmark/Prompt/Task Redesign 实施计划

  ## 摘要

  本轮按你刚才锁定的范围执行：不做 VM/Docker/openEuler，不碰 state_ref 性能优化；直接把当前 benchmark surface 改成干净的 lane packs，并同步做强去特化。

  默认入口改成 state_transfer carrier 主包。authenticity、natural support、communication、memory、internal regression、open validation 全部拆成独立 task packs。natural_handoff_text 改成 evidence-only free-text baseline，不再读取 decision_packet.route/
  tool_name；formal tasks 同时下调 summary_hint 与 doc-set shaping，避免继续把 route prior 塞回 benchmark。

  ## 关键改动

  ### 1. Task pack 与默认入口重组

  - 保留 tasks/sample_benchmark.yaml:1 路径，但内容改成 formal_state_transfer_carrier_pack：
      - 仅保留 text_packet_minimal vs state_packet_minimal
      - protocol only
      - memory_off
      - claim_lanes = [state_transfer]

  - 新增 5 个 pack：
      - tasks/state_transfer_authenticity_benchmark.yaml
      - tasks/state_transfer_natural_support_benchmark.yaml
      - tasks/communication_benchmark.yaml
      - tasks/memory_benchmark.yaml
      - tasks/internal_regression_benchmark.yaml

  - 继续保留 tasks/open_validation_benchmark.yaml:1 作为 support/diagnostic。
  - tasks/sample_tasks.py:13 扩展 TASK_PACK_TYPES 与 TASK_SET_ALIASES：
      - default / sample_benchmark / formal_controlled 都指向 carrier 主包
      - 新增 authenticity、natural_support、communication、memory、internal_regression alias

  - TaskSetMetadata.support_only 不再只认 open_validation；state_transfer_natural_support 也标为 support-only。
  - 不保留新的“混合 formal 总包”；避免重新把 headline 污染回 aggregate。

  ### 2. State-transfer 三条线彻底分开

  - authenticity pack：
      - 使用当前 text_brief vs rich state_ref
      - 只承载 typed handoff is real
      - README / report / manifest 一律写 authenticity，不再写 efficiency

  - carrier pack：
      - 使用当前 text_packet_minimal vs state_packet_minimal
      - 作为唯一 state_transfer efficiency headline
      - report 主表只保留 carrier comparison

  - natural_support pack：
      - 使用 natural_handoff_text vs state_packet_minimal
      - claim_lanes = [] 或 support-only 等价标记
      - report 明确标成 support，不参与 formal headline

  ### 3. Natural baseline 改成 evidence-only

  - runtime/executor_runtime.py:1434 的 _build_natural_handoff_text 改签名与实现：
      - 删除 decision_packet 入参
      - 只允许输入 query、受限 evidence_text、可选无标签化 evidence preview
      - 不得写入 route、tool_name、route_source、matched_signals、tool_candidates

  - agents/sample_agents.py:445 的 natural_handoff_text 生成路径同步改成 evidence-only。
  - 保留 runtime/executor_runtime.py:1451 _feature_bundle_from_natural_handoff 的“从自然文本重建 route/tool”职责，但它只能从 free text + evidence text 推断，不能再依赖任何结构化 side-channel。
  - 为防回归，加断言型测试：natural handoff 文本中不得出现 Route:、Tool:、route_source、tool_candidates 这类结构字段。

  ### 4. 强去特化：formal tasks 下调 prompt/task shaping

  - state_transfer 三个 pack 的 task 文案全部重写：
      - goal 不直接点名既定 diagnosis
      - summary_hint 改成 route-agnostic 输出约束，例如“总结最可能根因、列冲突证据、给首个动作”
      - evidence_text 只保留 benchmark contract，不携带 route/tool 暗示

  - carrier / authenticity / natural_support 三个 pack 的 corpus_doc_ids 从“2 文档紧配对”扩成“同 family 小 docset + 至少 1 个 false lead”，仍限制在 repo-local family 内。
  - communication / memory pack 保持机制目标不变，但同步移除不必要的 route-preserving summary_hint 文案，避免 formal packs 之间风格不一致。
  - internal_regression pack 保留当前 incident-chain 任务的主要语义与 replay contracts，用作工程回归，不承担新 benchmark headline。

  ### 5. Runner / report / README 同步收口

  - eval/runner.py:2485 的报告生成按 pack_type / 任务内容分支：
      - carrier pack 只出 Protocol-Only Carrier Efficiency
      - communication / memory pack 只出各自 lane 表
      - protocol-only packs 禁止再输出误导性的 text-vs-protocol aggregate headline

  - manifest 增补新的 pack_type 值与更准确的 task_set_description / reading_contract。
  - README.md:157 与 tasks/README.md:1 更新：
      - 默认 pack 变为 carrier 主包
      - 列出 6 个主要 pack 的用途
      - state_transfer 正式口径改成“authenticity 成立、carrier 另证、natural-text 仅 support”

  - 不改 runtime、statepool、memory 的底层接口语义；本轮是 benchmark surface 重构，不是机制重写。

  ## 测试与验收

  - tasks/sample_tasks.py 加载测试：
      - 默认 alias 指向 carrier 主包
      - 各新 alias 能正确解析
      - support_only 对 natural_support / open_validation 为真

  - tests/test_smoke.py 调整与新增：
      - carrier/authenticity/natural/communication/memory/regression pack 的 metadata、mode、strategy、lane 纯度测试
      - natural handoff 无结构字段泄漏测试
      - protocol-only 单包 report surface 测试
      - communication 与 memory pack 仍维持原有 claim contract

  - targeted benchmark smoke 只针对 pack 级别：
      - carrier pack 生成单一 carrier 主表
      - authenticity pack 不再混出 efficiency 表
      - natural_support pack 被标成 support-only，且不进入 formal claim

  - 文档验收：
      - README、tasks/README、当前 progress/planning 文档中的默认 pack 与命令入口不再引用旧混合总包作为 headline 入口

  ## 假设与默认

  - 本轮不新增开放域任务，不扩到 VM/Docker/openEuler。
  - sample_benchmark.yaml 的“默认入口”含义改成 state_transfer carrier，这是后续主 headline。
  - communication 与 memory 也一起拆成独立 formal packs，不再继续和 state-transfer 共包。
  - text_brief 保留为 structured-shadow baseline，但只活在 authenticity pack，不再拿去讨论 low-overhead。
  - internal_regression 与 open_validation 继续存在，但都从正式 headline 路径移开。

# Retrieval Replay Route Provenance Contract 2026-06-09

日期：`2026-06-09`

适用范围：这份短文档只记录当前
`/home/qcrs/statebus/project`
为 `P1 replay` 再补的一层
route-provenance contract evidence。
它不是新的 matched benchmark，
也不是新的 formal artifact；
它只把当前 replay gate 的一个剩余实现边界，
固定成可复查的 host-side regression。

## 1. 这轮为什么值得补

上一轮 route diagnostic artifact 已经证明：

1. `generic_triage / low_confidence_abstain`
   不会触发 exact replay
2. clear route /
   `hint_consensus`
   仍然会触发 exact replay

但这还没有把更细的一层边界单独钉死：

> 当前 replay gate 拒绝的是“generic route”，
> 还是更严格地拒绝
> “没有 lexical provenance 的 route”？

如果这层不单独补出来，
那 problem map 里剩下的
`route-evidence provenance`
就还只是推断，不是直接证据。

## 2. 这轮补的是什么

这轮没有新增 benchmark task set，
也没有新增 deterministic artifact。

只新增了三条 host-side regression：

1. `_route_is_replay_eligible`
   明确要求：
   - `route_confidence >= threshold`
   - `route_provenance` 含 `lexical`
2. `_matches_skip_retrieve_execute`
   在 exact replay gate 下：
   - 同样的 non-generic route
   - 如果 provenance 退成
     `corpus_metadata_unverified`
   - 仍然会被拒绝
3. `_matches_skip_execute`
   在 validated replay gate 下：
   - stored side 和 fresh side
     任一侧 provenance 丢掉 `lexical`
   - `skip_execute` 都会被拒绝

## 3. 这轮现在直接证明什么

当前 replay gate 的 route 约束，
并不只是：

1. route 名字不能是 `generic_triage`
2. route confidence 不能太低

它还额外要求：

1. route provenance 必须含 `lexical`
2. metadata-only route
   即使 confidence 看起来高、
   route 名也非 generic，
   仍然不算 replay eligible

这说明：

> 当前 replay gain 继续更像
> tight runtime evidence gate，
> 而不是“只要 route label 对齐就能复用”。

## 4. 当前最诚实的结论

这轮新增价值应记成：

> replay route-provenance contract closure

它现在支持的说法是：

1. route provenance
   不是 report wording，
   而是当前 replay gate 的真实实现条件
2. current replay gate
   会拒绝 metadata-only route memory
3. 这层证据当前只成立到
   contract / regression level

它仍然不支持的说法包括：

1. 这已经等价于新的 matched benchmark
2. 这已经足够替代更弱 theme /
   更宽 provenance 的 runtime diagnostic artifact
3. replay 已经摆脱
   route-evidence alignment 的受控条件

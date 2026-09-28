# Contest Memory Mechanism Results

这是 **Memory 机制单项证据包**，从 `contest-mechanisms-20260927_171109-3234416` 的混合 raw batch 中按 Memory 16 个 slot 独立投影而来；不是 Contest39 主链路结果，也不包含 State 8 个 slot。

- Raw root: `/home/qcrs/statebus/os/runs/contest-mechanisms-20260927_171109-3234416`
- Memory planned / started / passed: 16 / 16 / 16
- Families: `finance` (`F01/F02/F06/F07`) and `service_ops` (`O01/O02/O06/O07`)
- Variants: `off` and `on`
- Environment: `statebus-runtime`, `/workspace/statebus/os`, Qwen3-32B on physical GPU 2, Qwen3-Embedding-0.6B on physical GPU 1.

## 结果口径

- `F02`, `F07`, `O02`, `O07` 观察到 `validated_replay_consumed`：Memory candidate 命中、兼容性通过、当前输入重算门通过，Executor request 为 0。
- `F01`, `O01` 是 no-match；`F06`, `O06` 命中但 incompatible，继续当前输入执行。它们不是失败，而是 Memory 兼容性边界的负向证据。
- 8 个 Memory-on slot 中 4 个实际消费 validated replay；candidate hit rate 为 `6/8 = 75%`，actual validated replay consumption 为 `4/8 = 50%`。
- 所有 16 个 Memory slot 质量通过。Memory-on 相对 off 的 provider token / request 减少只在完整 matched pair 上解释，不把 lookup、兼容性检查或未消费 candidate 当作收益。

## 聚合结果

| Family | Variant | Started | Passed | Provider requests | Provider tokens | Task ms sum |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| finance | off | 4 | 4 | 9 | 16886 | 332444.389 |
| finance | on | 4 | 4 | 6 | 9527 | 236734.899 |
| service_ops | off | 4 | 4 | 9 | 14580 | 217736.112 |
| service_ops | on | 4 | 4 | 6 | 8054 | 164239.112 |

## 逐任务 Memory 行

详见同目录的 `task_results.jsonl` 和 `task_results.csv`。完整混合报告仍保留在 `docs/reports/contest-mechanisms-20260927_171109-3234416/`，原始 runs 未修改。

## 与主链路的关系

- 主链路报告：`docs/reports/contest39-mainchain-results-20260927/`
- Memory 机制报告：本目录
- State 机制报告：`docs/reports/contest-state-mechanism-formal-20260927_200832/`

三者必须分开引用：主链路证明同边界整链比较；Memory 机制报告证明 Memory query、compatibility、validated replay、当前输入重算和消费；State 机制报告证明 StateRef 发布、跨进程传递、Executor 消费和释放。

## 原始命令

```bash
bash scripts/run_contest_mechanisms.sh \
  --mechanism all \
  --mode live \
  --output /home/qcrs/statebus/os/runs/contest-mechanisms-20260927_171109-3234416
```

本目录是从上述混合批次派生的 Memory-only 报告，不是重新运行。

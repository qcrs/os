# Git 历史与变更审查

本轮审阅了以下命令结果：

- `git status -sb`
- `git log --oneline --decorate -n 50`
- `git log --oneline --decorate -- docs/improvement docs/reports docs/contracts v2 tests/v2 scripts | sed -n '1,200p'`
- `git show --stat --oneline HEAD`
- `git show --stat --oneline HEAD~1`
- `git show --stat --oneline HEAD~2`
- `git show --stat --oneline HEAD~3`
- `git diff --stat`
- `git diff --check`

## 当前分支和 tag

审计开始时的 `HEAD`：

```text
3738f34 (HEAD -> feat/statebus-v2-container-runtime, tag: v2-claim-upgrade-20260706) Fix state pool backend fallback observability
```

`v2-claim-upgrade-20260706` tag 指向本轮审计前的 state-pool observability fix commit。

## 近期关键提交

### `3738f34 Fix state pool backend fallback observability`

类型：真实代码修复 + 测试。

变更：

- `v2/state/store.py`
- `tests/v2/test_minimal_benchmark.py`
- `tests/v2/test_state_materialization.py`

结论：真实修复。`LayeredStateStore.backend_name` 现在会在 handle release 后报告 last 或 prior actual storage backend。fresh formal runs 确认 `state_pool_mode_used` 对 shared memory 和 memfd 是真实 backend。

限制：memfd unavailable fallback 仍未在真实 no-memfd 主机上证明。

### `5a44fea Update v2 claim upgrade documentation`

类型：文档和 safe-claim 更新。

变更：

- 历史 `docs/improvement/19_claim_upgrade_completion_report_20260706.md`
- 历史 `docs/improvement/artifacts/17_final_system_audit/17f_safe_claim_language.md`
- 部分 report guides。

结论：总体合适。它明确没有升级 formal external superiority。本轮审计进一步在 `docs/reports/v2_experiment_summary_20260703.md` 添加 CodeAct 历史警告。

限制：文档不能替代 formal external compare 证据。

### `e20b8e9 Implement v2 claim upgrade benchmark support`

类型：真实实现 + 测试 + sample assets。

变更：

- `scripts/run_v2_full_container_audit_suite.sh`
- `tasks/formal/*`
- `v2/benchmark/task_registry.py`
- benchmark runners 与 state store
- tests

结论：真实实现了 25-case、5-family formal registry 和 `--state-pool-mode` plumbing。

限制：`tasks/formal/*/validator.py` helper files 不是 primary runner validation path；实际 quality gate 使用 `v2/runtime/smoke.py` 的 `expected_facts`。

### `4692c93 Add execution prompt for claim upgrade plan`

类型：prompt/documentation only。

结论：只适合作为工作指令。不能证明实现。

## 审计开始时 worktree

预先存在的用户改动：

- `M docs/improvement/PROMPT_FOR_CLAIM_UPGRADE_EXECUTION.md`
- `?? docs/improvement/PROMPT_FOR_V2_COMPREHENSIVE_TRUTH_AUDIT.md`

本审计产生的改动：

- replay metric code/test fix。
- CodeAct historical-report wording fix。
- 新综合审计目录和 benchmark artifacts。

## 防止过度解读

不能从近期 commits 推断：

- formal external API comparison 已重跑。
- realtime LLM code generation 是当前 formal benchmark 的一部分。
- deterministic formal results 证明 API mode behavior。
- container activation 可用。
- 已执行 openEuler VM validation。

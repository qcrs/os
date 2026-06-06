# New Window Prompt

Use this when opening a new Codex window for implementation work:

```text
You are now working in `/home/qcrs/statebus/project`.

Read first:
- `AGENTS.md`
- `README.md`
- `docs/constraints/current_host_and_migration.md`
- `docs/planning/implementation_plan.md`
- `docs/reference/题目.md`

Environment rules:
1. Main development is on the current Linux host.
2. Use `source deploy/activate_statebus_host.sh`.
3. Do not depend on system Docker daemon access.
4. First `StatePool` implementation must use file-backed `mmap` and/or Python `shared_memory`.
5. Focus on `Phase 0` to `Phase 4` only.

Current goal:
- continue implementing the host-side runnable path
- keep `text` and `protocol` modes in scope
- wire `StateRef`, SQLite, FAISS, and benchmark scaffolding incrementally

Do not stop at planning; make code changes directly.
```

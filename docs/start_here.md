# Start Here

```bash
cd /path/to/statebus/project
git status --short
git rev-parse --short HEAD
source deploy/activate_statebus_host.sh
python -m pytest -q
python -m runtime.smoke
```

Optional LLM API config is split into:

- `deploy/statebus_llm.yaml.local` for provider/role/model behavior
- `deploy/statebus_llm.env.local` for secrets and temporary overrides

Use the corresponding `.example` files as templates. `Planner` and
`Summarizer` both read the shared config through `runtime/llm.py`.

For the normal StateBus host path, prefer GPU embeddings explicitly:

```bash
export STATEBUS_EMBED_DEVICE=cuda:0
```

If Codex or the host unexpectedly falls back to CPU, check:

```bash
nvidia-smi
```

If dependencies are missing:

```bash
bash scripts/setup_host_dev_env.sh
```

Full host environment notes:

- `docs/setup/host_environment.md`

Current branch audit and verification closure:

- `docs/progress/feat_realism_protocol_hardening_audit_20260607.md`
- `docs/progress/contest_requirement_host_audit_20260607.md`
- `docs/planning/host_mainline_authenticity_execution_plan_20260610.md`
- `docs/planning/host_goal_mainline_dependency_20260607.md`
- `runs/host_goal_eval_20260608_093111_planner_contract_refresh/SUMMARY.md`

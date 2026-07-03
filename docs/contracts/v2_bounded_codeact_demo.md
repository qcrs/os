# StateBus v2 Bounded CodeAct Demo

Date: 2026-07-03

Scope: optional CodeAct showcase for bounded generated Python execution.

The main v2 evidence still claims controlled CodeAct-style execution. This demo
adds a separate, bounded generated-code path with an AST policy audit. It must
not be reported as general-purpose CodeAct benchmark superiority.

Run in the openEuler container:

```bash
source /usr/local/bin/activate_statebus_container.sh
cd /workspace/statebus/project
python3 scripts/v2_diagnostics/bounded_llm_codeact_demo.py \
  --output-root /statebus/runs/v2-diagnostics \
  --role-path-mode deterministic \
  --sandbox-backend bwrap \
  --python-executable /usr/bin/python3
```

For an API-generated source demo, use:

```bash
python3 scripts/v2_diagnostics/bounded_llm_codeact_demo.py \
  --output-root /statebus/runs/v2-diagnostics \
  --role-path-mode api \
  --sandbox-backend bwrap \
  --python-executable /usr/bin/python3
```

Expected artifacts:

- `generated/llm_generated_action.py`
- `ast_audit.json`
- `sandbox_result.json`
- `outputs/bounded_codeact_result.json`
- `summary.json`
- `summary.md`

Claim boundary:

- allowed: bounded generated Python action passed AST policy and ran in the requested sandbox backend;
- not allowed: arbitrary LLM code execution is safe, production sandboxing, or CodeAct superiority over other systems.

# Start Here

```bash
cd /home/qcrs/statebus/project
source deploy/activate_statebus_host.sh
python -m pytest -q
python -m runtime.smoke
```

Optional LLM API config is split into:

- `deploy/statebus_llm.yaml.local` for provider/role/model behavior
- `deploy/statebus_llm.env.local` for secrets and temporary overrides

Use the corresponding `.example` files as templates. `Planner` and
`Summarizer` both read the shared config through `runtime/llm.py`.

If dependencies are missing:

```bash
bash scripts/setup_host_dev_env.sh
```

# 源码布局

当前 Python 和 Studio 源码都在 `src/`：

```text
src/statebus/   Runtime、contracts、control、state、memory、benchmark、Studio backend
src/studio-ui/  React/TypeScript Studio frontend
```

Python import 使用 `src` package root；Studio backend 从 `src/studio-ui/dist` 提供构建后的页面。任务输入和 validator 位于 `tasks/`。

常用检查：

```bash
source deploy/activate_statebus_host.sh
python -c 'import statebus; print(statebus.__file__)'
cd src/studio-ui && npm ci && npm run typecheck && npm run build
```

## 目录导航

```text
src/
├── README.md
├── statebus/
│   ├── benchmark/
│   │   ├── model_assist_utility/
│   │   └── samples/continuous_task_families/kv_prefix_reuse/
│   ├── contracts/
│   ├── control/
│   ├── integrations/vllm_kv/
│   ├── memory/
│   ├── provenance/
│   ├── refs/
│   ├── retrieval/
│   ├── runtime/
│   ├── state/
│   └── studio/data/
└── studio-ui/
    ├── src/
    ├── tests/
    └── dist/
```

目录入口：

| 目录 | 入口 |
| --- | --- |
| `statebus/` | [`statebus/`](statebus/) |
| `statebus/benchmark/` | [`statebus/benchmark/`](statebus/benchmark/) |
| `statebus/benchmark/model_assist_utility/` | [`statebus/benchmark/model_assist_utility/`](statebus/benchmark/model_assist_utility/) |
| `statebus/benchmark/samples/continuous_task_families/kv_prefix_reuse/` | [`README.md`](statebus/benchmark/samples/continuous_task_families/kv_prefix_reuse/README.md) |
| `statebus/contracts/` | [`statebus/contracts/`](statebus/contracts/) |
| `statebus/control/` | [`statebus/control/`](statebus/control/) |
| `statebus/integrations/vllm_kv/` | [`statebus/integrations/vllm_kv/`](statebus/integrations/vllm_kv/) |
| `statebus/memory/` | [`statebus/memory/`](statebus/memory/) |
| `statebus/provenance/` | [`statebus/provenance/`](statebus/provenance/) |
| `statebus/refs/` | [`statebus/refs/`](statebus/refs/) |
| `statebus/retrieval/` | [`statebus/retrieval/`](statebus/retrieval/) |
| `statebus/runtime/` | [`statebus/runtime/`](statebus/runtime/) |
| `statebus/state/` | [`statebus/state/`](statebus/state/) |
| `statebus/studio/` | [`statebus/studio/`](statebus/studio/) |
| `statebus/studio/data/` | [`statebus/studio/data/`](statebus/studio/data/) |
| `studio-ui/` | [`studio-ui/`](studio-ui/) |
| `studio-ui/src/` | [`studio-ui/src/`](studio-ui/src/) |
| `studio-ui/tests/` | [`studio-ui/tests/`](studio-ui/tests/) |
| `studio-ui/dist/` | [`studio-ui/dist/`](studio-ui/dist/) |

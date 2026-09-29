# Design Documents

Design contracts are grouped separately from implementation notes and recorded
experiment reports.

```text
docs/design/
├── mrr/           # MRR authority, lifecycle, replay, and compatibility
├── kv-apc-logit/  # Explicit KV, APC/prefix, and Logit contracts
└── architecture/  # Cross-cutting architecture decisions
```

The existing `docs/mrr/` and historical audit documents remain in place during
the first phase. `docs/architecture/directory-map.md` records the migration
mapping.

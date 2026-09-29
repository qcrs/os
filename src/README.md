# Source Layout Transition

The target source layout is:

```text
src/
├── statebus/   # Python runtime, contracts, memory, benchmark, Studio backend
└── studio-ui/  # React/TypeScript frontend
```

These directories are now the active source paths. Python packaging uses the
`src` package root, and Studio serves the frontend build from
`src/studio-ui/dist`.

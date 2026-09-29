# Evidence Index

Evidence is separated by protocol and denominator.

| Evidence class | Target directory | Meaning |
| --- | --- | --- |
| Complete mainline | `tests/evidence/mainline-24/` | The 24-round continuous mainline and its matched comparison |
| Mainline ablation | `tests/evidence/mainline-mechanisms/` | Mechanism comparisons on the mainline |
| APC | `tests/evidence/specialized/apc/` | APC or prefix utility phase |
| KV | `tests/evidence/specialized/kv/` | Explicit KV replay/continuation phase |
| Logit | `tests/evidence/specialized/logit/` | Logit gate phase |
| Long-text utility | `tests/evidence/utility/longtext-demo-v3/` | Independent 28-slot display chain |

Every published evidence set uses the longtext template: `README.md`,
`summary.md`, `metrics.json`, `commands.md`, `execution-manifest.env`,
`selected-slots/`, `failures/`, and `service/` when service switching occurs.

The complete raw run remains under its original report path or a separately
archived artifact. A curated evidence directory must record the source run ID,
revision, command, and checksum rather than silently copying an entire history.

## Current material

The target `tests/evidence/utility/longtext-demo-v3/` now contains the curated
utility package copied from
`docs/reports/contest-model-assist-utility/longtext-demo-v3-20260929_104844-2545919/`.
The original top-level curated files are retained during this first phase for
backward compatibility.

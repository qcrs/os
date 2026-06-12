# Tasks

Put reproducible sample tasks here.

The first runnable benchmark should prefer repo-local task samples rather than
real host service diagnostics.

Default benchmark input:

- `contest_release_regression_carrier_benchmark.yaml`
  - default `state_transfer_carrier` formal entry pack
  - protocol-only carrier headline for contest-style release-regression collaboration
  - formal `aggregate` interpretation is intentionally suppressed; read the lane-local carrier table only

Overview pack:

- `sample_benchmark.yaml`
  - `formal_controlled` frozen overview pack
  - keeps aggregate, replay-axis, and legacy dedicated-lane overview in one place

Formal dedicated packs:

- `communication_benchmark.yaml`
  - `communication` formal pack
- `memory_benchmark.yaml`
  - `memory` formal pack
- `state_transfer_authenticity_benchmark.yaml`
  - `state_transfer_authenticity` formal pack
  - use for protocol-only `text_brief` versus `state_ref` typed-handoff authenticity
- `state_transfer_pure_text_benchmark.yaml`
  - `state_transfer_pure_text` formal pack
  - use for protocol-only `natural_handoff_text` versus `state_ref` pure-text-versus-typed-state comparison
  - current contest-release object is `5 family x 4 case x 2 strategy = 40 tasks`
- `contest_release_regression_carrier_benchmark.yaml`
  - `state_transfer_carrier` formal pack
  - use for protocol-only carrier efficiency only
  - current contest-release object is `5 family x 4 case x 2 strategy = 40 tasks`
- `state_transfer_inline_text_support_benchmark.yaml`
  - `state_transfer_inline_text_support` support-only pack
  - use for strict inline message-body pure-text versus minimal state-packet support validation

Support-only packs:

- `open_validation_benchmark.yaml`
  - support-only open validation pack
  - use for retrieval / executor / replay / planner pre-pass boundary checks after controlled changes

Engineering packs:

- `internal_regression_benchmark.yaml`
  - `internal_regression` engineering pack
  - includes route-diagnostic `lexical_override` tasks

Additional contest-draft packs:

- `contest_release_regression_authenticity_benchmark.yaml`
  - draft contest-oriented `state_transfer_authenticity` pack
  - current contest-release object is `5 family x 4 case x 2 strategy = 40 tasks`
- `contest_release_regression_natural_support_benchmark.yaml`
  - legacy contest-oriented natural-text support draft
  - still accepted through the `state_transfer_inline_text_support` alias path for compatibility
  - current contest-release object is `5 family x 4 case x 2 strategy = 40 tasks`

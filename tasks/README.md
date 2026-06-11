# Tasks

Put reproducible sample tasks here.

The first runnable benchmark should prefer repo-local task samples rather than
real host service diagnostics.

Default benchmark input:

- `sample_benchmark.yaml`
  - unique frozen `formal_controlled` headline pack
  - contains only the controlled replay chains plus dedicated `communication` / `state_transfer` / `memory` headline lanes
  - does not carry planner-open validation or route-regression diagnostics

Formal headline pack:

- `sample_benchmark.yaml`
  - default `formal_controlled` headline object

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
- `contest_release_regression_carrier_benchmark.yaml`
  - `state_transfer_carrier` formal pack
  - use for protocol-only carrier efficiency only

Support-only packs:

- `state_transfer_natural_support_benchmark.yaml`
  - `state_transfer_natural_support` support-only pack
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
- `contest_release_regression_natural_support_benchmark.yaml`
  - draft contest-oriented `state_transfer_natural_support` support-only pack

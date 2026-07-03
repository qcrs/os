# StateBus v2 External Pure-Text Fairness Gate

Date: 2026-07-03

Scope: fixed-answer external pure-text comparator eligibility.

The external pure-text lane is now allowed to pass the hard fairness gate for
the dev fixed-answer comparator when all of these conditions are true:

- same task family;
- same role graph: `planner->retriever->executor->summarizer`;
- same fixed-answer quality-floor and scoring contracts;
- same cold-start history policy;
- no StateBus internal helper use;
- four role metrics are present;
- no contamination flag is raised.

This fixes the previous fail-closed state where the external lane could satisfy
the practical role/fairness contract but still reported
`formal_comparator_eligible=false`.

The external lane may normalize a role output that embeds the visible candidate
key, for example `route="worker_queue_starvation::semantic_retriever"`, into
the canonical pair `route="worker_queue_starvation"` and
`tool_name="semantic_retriever"`. This is a pure output-normalization step over
the public candidate list, not a scorer relaxation and not a StateBus helper.

## Claim Boundary

Allowed claim:

- external pure-text fixed-answer comparator passed the dev fairness gate;
- compare diagnostics may emit dev fixed-answer headline deltas when the gate
  passes.

Not allowed:

- formal financial benchmark superiority over pure text;
- open-ended external baseline superiority;
- replay/history-assisted StateBus versus cold-start pure-text comparison.

The suite metadata therefore keeps:

- `external_comparator_claim_scope=dev_fixed_answer_only`;
- `formal_superiority_claim_allowed=false` unless a future formal-tier
  comparator explicitly satisfies its own contract;
- `formal_headline_eligible=false` for the current dev fixed-answer run.

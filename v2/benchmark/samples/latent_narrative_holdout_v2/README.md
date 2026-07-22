# Latent Narrative Holdout v2

This frozen offline suite replaces the v1 default without modifying the v1
manifest or its historical artifacts.

The six cases cover three balanced task modes:

- long-document causal analysis;
- cross-document evidence synthesis;
- conditional operating-plan selection.

Each case declares `source_item_ids`. Only those sources enter its evidence
pack. Required-fact source lineage must be a subset of that authorization, and
cross-document facts must cite every listed source to pass post-generation
scoring.

The conditional plan cases test document-grounded branch selection. They are
not StateBus Runtime Controller replan evidence. Expected facts and term groups
remain post-generation scoring data and never enter model-visible prompts,
schemas, anchors, or artifacts.

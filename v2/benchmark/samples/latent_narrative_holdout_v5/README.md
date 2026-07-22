# Latent Narrative Holdout v5

V5 is the active preregistered suite. It preserves the v4 task and evidence
contract while freezing `statebus.required_fact_phrase.v2`, a deterministic
phrase matcher that handles ordinary inflection and equivalent negative
auxiliaries without semantic model scoring.

The v2, v3, and v4 C0 preflight artifacts remain immutable. No expected answer
or selected plan is added to model-visible task text. Conditional-plan results
remain document-grounded operating branch selection, not Runtime Controller
replan evidence.

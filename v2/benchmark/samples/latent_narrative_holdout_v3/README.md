# Latent Narrative Holdout v3

This is the active preregistered suite. It retains v2's six cases, three task
modes, case-scoped evidence authorization, and source documents. It does not
modify the frozen v2 manifest or the failed v2 C0 preflight artifact.

V3 narrows the task-to-score contract exposed before generation:

- long-document tasks name the requested analytical dimensions more precisely;
- cross-document tasks state which conclusion must combine both documents;
- conditional-plan tasks distinguish observed values, branch thresholds,
  transition timing, and fail-closed fallback.

No expected fact, scoring term, selected branch answer, or answer summary is
added to a model-visible surface. Conditional plans remain document-grounded
operating branch selection, not StateBus Runtime Controller replan evidence.

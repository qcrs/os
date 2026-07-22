# Latent Narrative Diagnostic v6

V6 is a post-remediation diagnostic over the already observed v5 cases. It is
not a fresh quality holdout and must not replace the frozen v5 result.

The task, evidence, expected facts, scorer, lane order, and quality thresholds
remain unchanged. V6 changes only the latent mechanism budget and prompt
contract: it restores the design-preregistered 40-step lower bound, disables
Qwen thinking for both text and latent producer templates, and renders the L1
consumer through the same structured system/user chat boundary as C0.

Conditional-plan results remain document-grounded operating branch selection,
not Runtime Controller replan evidence. Any quality claim still requires a new,
unseen holdout after the mechanism is frozen.

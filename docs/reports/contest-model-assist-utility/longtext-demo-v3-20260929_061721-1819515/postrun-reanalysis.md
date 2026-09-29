# Post-run Logit scoring reanalysis

This supplement preserves the live result and records an offline scoring correction. It does not replace `records.jsonl`, `summary.json`, or `run-status.env`.

The `MU-LOGIT-UNRESOLVED-ORION-EXCEPTIONS:logit_selective` record remains historically `failed`. Its stored trace shows Gold outcome `abstain`, selected candidate `insufficient_evidence`, runtime action `abstain`, no output artifacts, and dispatch errors ending in `need_more_evidence`. The earlier `model_assist_review_required` dispatch error was selected by the scorer because it searched errors in forward order. The scorer now checks the last non-empty dispatch error. Reapplying that predicate to the stored trace offline yields a correct abstention; no model request was made for this reanalysis.

The resume-03 live summary remains `incomplete`: 11 of 12 Logit positions completed and one is retained as a historical failure; APC and KV scored positions were not started after their calibration gates failed. The original standard service remained unchanged and healthy (`pid=1911578`, port `53334`).

Validation after the scoring fix: targeted utility tests passed (`38 passed`); `bash -n` and `git diff --check` passed. The completed `compact_once` orphan trace was recovered and skipped during resume-03, so its provider requests were not repeated.

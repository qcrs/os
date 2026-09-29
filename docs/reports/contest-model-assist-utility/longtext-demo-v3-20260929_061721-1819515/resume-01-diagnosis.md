# Resume 01 Diagnosis

Run status: `incomplete_gate`; `demo_completed=false`.

The latest summary has 0 APC scored positions, 12 Logit positions marked unavailable, and 0 KV scored positions. The other 16 scored positions did not start because the APC and KV calibration gates failed.

The saved Logit calibration responses were reanalyzed locally without another model request. Exact extraction returned `completion_token_bytes_mismatch` for both responses, so the Logit positions remain unavailable rather than receiving proxy probabilities.

The resumed executor responses used the required nested `arguments` shape and valid grouped-aggregate arrays. They still emitted `filter_in` with singular `value`; the StateBus DSL expects the array key `values`, so the Runtime quality gate rejected the empty filtered result. The prompt now spells out the exact `filter_in` key and example. No further live revalidation was run because the four-position retry allowance was used by the APC and KV calibration pairs.

The manager stopped the run-owned KV service and restored standard. Recovery verification passed for manager identity, `/health`, `/v1/models`, tokenize, and raw logprobs. The KV continuation handle was released and its post-run registry reported zero entries and bytes. The original failed slots and the `resume-01` attempts remain in the report archives.

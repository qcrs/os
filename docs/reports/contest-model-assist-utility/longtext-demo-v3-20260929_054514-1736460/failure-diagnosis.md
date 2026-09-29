# Initial live attempt diagnosis

- Run: `longtext-demo-v3-20260929_054514-1736460`.
- Outcome: failed before any generation request or scored position. `summary.json` records 0/8 APC, 0/12 Logit, 0/8 KV and 28 not started.
- Service: standard manager PID 631775 remained healthy and unchanged; see `service/standard-unchanged-verification.json`.
- Cause: the runner passed the OpenAI API base URL ending in `/v1` to `VllmTokenCodec`, which appends `/tokenize`; the server logged `POST /v1/tokenize` as 404. The unversioned `/tokenize` endpoint succeeded in the explicit readiness probe.
- Repair: route every utility tokenizer codec through the unversioned tokenizer base URL, and cover the resulting endpoint path with `test_tokenizer_codec_uses_unversioned_vllm_endpoint`.
- Verification after repair: 21 targeted tests passed, shell syntax/import checks passed, the real tokenizer endpoint returned 22 token IDs, and dry-run retained all 28 positions.
- Request accounting: this attempt made one failed tokenizer request and no model generation requests. The copied `service/standard-on-first-attempt.log` preserves the server-side 404 record.

# Orion Q3 Exception Audit: Proposed Exclusion Record

Document id: `doc-orion-q3-ex-044-exclusion-audit`
Section id: `source-record`
Record id: `ORI-Q3-EX-044`
Custodian: Orion controller audit desk
Frozen revision: 2026-09-18

## Audit entry

The audit desk reviewed the same Cedar Park carrier invoice after finding that the final controller disposition was not present in the period-end archive. The audit entry records a proposed `exclude` treatment until the approval chain is complete. It does not say that the underlying shipment did not occur. The receipt shows delivery on 2026-09-02 and the carrier invoice shows USD 3,840 for priority service. The audit question is authorization, not the physical delivery or the face value of the charge.

The entry links invoice `ORI-FRT-2026-9031`, purchase order `ORI-PO-77219`, receipt `ORI-RCV-88126`, and sample exception `ORI-Q3-EX-044`. These identifiers match the analyst submission. The audit desk classified the evidence state as `awaiting_final_disposition`, because its archive copy has no signed controller decision. Its exclusion proposal prevents an unreviewed amount from being included in the approved-sample total while the missing approval is investigated.

## Review fields

| field | recorded value |
| --- | --- |
| audit date | 2026-09-14 |
| quarter | 2026Q3 |
| review owner | controller audit desk |
| proposed treatment | exclude pending final disposition |
| matching sample program | approved_sample_cohort |
| invoice amount | USD 3,840 |
| approval queue status | preliminary_review |
| final controller signature | empty |
| later amendment reference | none recorded |

The audit status is not a final exclusion decision. It is a control hold applied while the final authorization is missing. The source therefore cannot support the permanent claim that the fee is ineligible. The analyst's proposed inclusion and the audit desk's proposed hold are both recorded as provisional statements. Neither document supersedes the other with a completed signed disposition.

## Archive and status semantics

The controller audit archive distinguishes `submitted`, `preliminary_review`, `approved`, `rejected`, and `superseded`. `submitted` and `preliminary_review` are workflow states; only `approved` or `rejected` with a signed disposition are terminal. An audit hold is used to keep a transaction out of a verified total until the terminal state exists. It is not evidence that the final reviewer chose rejection.

The export index covers the analyst submission, supporting carrier receipt, purchase-order reference, preliminary review, and audit hold. The final disposition column is empty in both the finance copy and audit copy. Neither archive contains a signed-by identity, a signature timestamp, or an amendment pointer. Search of the frozen Q3 register returns no later entry for this exception id. These facts explain why the audit desk did not mark the hold as final exclusion.

## Comparison with neighboring Q3 control records

Neighboring records in the same controlled queue show that an invoice may be physically valid while its sample eligibility remains undecided. Completed records contain an approval state and a separate signed disposition. A rejected record contains the same signed fields with a rejection value. Open records retain a proposed treatment and have no terminal status. The distinction prevents an operational recommendation from becoming an accounting decision merely because it agrees with a shipment record.

The archive uses one stable exception id across both proposals. The id proves that the analyst and auditor discuss the same charge; it does not resolve which proposed treatment is final. The audit desk has no authority to sign on behalf of the controller, and the analyst cannot approve their own submission. The missing signature must be treated as missing evidence, not reconstructed from either recommendation.

## Locator and authority

This record is authorized for the frozen utility corpus as an audit-side evidence item. It supports the claim that the fee was placed on hold while final review remained outstanding. It does not support a final exclusion. The paired inclusion record supports that an inclusion was proposed but also lacks final approval. Until a signed disposition or superseding amendment is supplied, neither candidate record establishes a verified include/exclude answer.

## Archive query and reconciliation receipt

The audit export was reconciled against the Q3 exception register using the stable exception id, invoice id, purchase-order id, and receipt id. The query returned one finance submission and one audit-side hold for `ORI-Q3-EX-044`. The join confirms that both entries refer to the same transaction; it does not merge their proposed treatments into a final status. The reconciler preserved the original source timestamps and did not promote a later import time into an approval time.

The archive query covered entries posted from 2026-07-01 through 2026-09-18, including records filed after the preliminary controller review. The result contains no disposition version after the audit hold, no signed controller identity, and no signature timestamp. The export includes an explicit empty value for the final-disposition field rather than omitting the field from the schema. This distinction was retained so that an absent value is not mistaken for a signed decision hidden in a different column.

The finance and audit copies have separate custody chains. The finance copy was exported by manufacturing finance control; the audit copy was exported by the controller audit desk. Both retain the same invoice and receipt references, but their recommendation fields have different owners. The audit desk can place a temporary control hold and request supporting evidence. Only the assigned finance controller can record the final approved or rejected state. Neither role may infer that state from the other's recommendation.

The reconciliation receipt is a completeness check for the frozen archive, not an authorization. It establishes the size and date boundary of the search and records that no superseding amendment was present at export time. A later signed decision would require a new archive revision and a new receipt. It cannot be backfilled into this immutable evidence bundle during a model run.

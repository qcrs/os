# Orion Q3 Exception Review: Proposed Inclusion Record

Document id: `doc-orion-q3-ex-044-inclusion-review`
Section id: `source-record`
Record id: `ORI-Q3-EX-044`
Custodian: Orion manufacturing finance control
Frozen revision: 2026-09-18

## Submitted record

The expedited-cost analyst opened this record on 2026-09-03 after Cedar Park received a replacement encoder shipment by priority carrier. The shipment relates to the Q3 approved-sample program, and the carrier invoice lists USD 3,840 in expedited fees. The supplier missed its original September delivery slot. The production schedule shows that the material was used for approved sample orders, but the carrier charge was posted before the controller completed the period-end review.

The analyst entered a proposed treatment of `include` so the invoice could be reconciled against the approved-sample cohort ledger. This is a proposal field, not the final disposition. The submitted record is attached to invoice `ORI-FRT-2026-9031`, purchase order `ORI-PO-77219`, and receipt `ORI-RCV-88126`. The invoice amount and row association can be checked independently; their presence does not by itself authorize cohort inclusion.

## Review fields

| field | recorded value |
| --- | --- |
| event date | 2026-09-02 |
| quarter | 2026Q3 |
| submitting cost center | Cedar Park assembly operations |
| proposed status | include |
| sample program | approved_sample_cohort |
| expedited fee | USD 3,840 |
| preliminary controller review | received 2026-09-08 |
| final controller signature | empty |
| superseding disposition id | none recorded |

The preliminary review note asks the submitter to attach the carrier exception receipt and confirm that the replacement shipment supports an approved sample order. The note does not contain approval language, a signed-by value, or an effective date. The attached receipt confirms priority service and delivery date; it does not confirm a cost-control exception. The purchase-order row links to the sample program but leaves the final eligibility decision to finance control.

## Applicable approval process

The approved-sample cost control uses a two-stage review. Operations may submit an inclusion proposal when an expedited shipment supports an approved sample order. A finance controller must then record a final signed disposition before the fee enters the controlled sample total. A preliminary review confirms that the item has entered the queue only. It must not be converted into an approved state by an analyst or by a matching purchase-order identifier.

For a final disposition, the record must contain the controller identity, signature timestamp, final status, and a disposition version that supersedes the submission. The frozen record has none of these fields. Its inclusion proposal is therefore not a final approval. The attached invoice and receipt are supporting transaction documents, not substitutes for the missing signature.

## Related control observations

The Q3 finance queue includes other expedited invoices with the same initial submission status. In completed records, the controller signature and final status are separate fields from the submitted recommendation. Records that remain in `preliminary_review` have not been included in the approved cohort. This field separation is maintained because shipment fact, invoice amount, sample-program association, and authorization are different claims with different evidence.

The document index lists the source attachments in order: analyst submission, carrier receipt, purchase-order association, preliminary controller note, and final-disposition field. The first four attachments are present. The fifth is blank. The archive export is complete through the frozen revision and records no superseding disposition identifier for `ORI-Q3-EX-044`.

## Locator and authority

The record is authorized for the frozen model-assist utility corpus as a sample cost-control record. It can support a statement that inclusion was proposed and that a preliminary review occurred. It cannot support a verified statement that the fee was finally approved. The question asks whether inclusion is permitted under the final-signature rule; a proposed status is not sufficient to answer yes.

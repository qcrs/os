# Nova Approved Sample Delivery Ledger

Document id: `doc-nova-approved-sample-delivery-ledger-2026`
Section id: `sample-ledger`
Corpus: controlled model-assist utility source bundle
Custodian: Nova network performance data office
Revision: 2026-09-18 frozen extract
Effective periods: 2026Q1 and 2026Q3

## Scope and field meanings

This extract contains controlled sample facts for the approved regional delivery cohort. It is separate from the company operating review and its aggregate on-time percentages. `committed_orders` is the denominator assigned to a regional delivery commitment; `on_time_orders` is the number fulfilled inside that commitment. The required cohort rate is the sum of on-time orders divided by the sum of committed orders for each quarter. An average of row percentages is not valid. Region, quarter, status, scope, rule id, and record id are retained so that the selected source can be checked rather than inferred from a report headline.

The 2026 approved-sample rule includes rows with status `APPROVED`, scope `approved_sample_cohort`, and rule id `R-NOV-SAMPLE-2026`. It excludes pending review, cancelled work, legacy-scope rows, and records outside Q1 or Q3. The original extract is ordered by posting date. The first, middle, and final rows below preserve that ordering; all values are distinct controlled records, not repeated filler.

## Q1 ledger rows

| record_id | region | committed_orders | on_time_orders | status | scope | rule |
| --- | --- | ---: | ---: | --- | --- | --- |
| NOV-LG-2601-001 | Central | 128 | 124 | APPROVED | approved_sample_cohort | R-NOV-SAMPLE-2026 |
| NOV-LG-2601-002 | Northeast | 146 | 140 | APPROVED | approved_sample_cohort | R-NOV-SAMPLE-2026 |
| NOV-LG-2601-003 | Southeast | 98 | 94 | APPROVED | approved_sample_cohort | R-NOV-SAMPLE-2026 |
| NOV-LG-2601-004 | Pacific | 161 | 155 | APPROVED | approved_sample_cohort | R-NOV-SAMPLE-2026 |
| NOV-LG-2601-005 | Mountain | 113 | 109 | APPROVED | approved_sample_cohort | R-NOV-SAMPLE-2026 |
| NOV-LG-2601-006 | Central | 176 | 169 | APPROVED | approved_sample_cohort | R-NOV-SAMPLE-2026 |
| NOV-LG-2601-007 | Northeast | 107 | 103 | APPROVED | approved_sample_cohort | R-NOV-SAMPLE-2026 |
| NOV-LG-2601-008 | Southeast | 143 | 137 | APPROVED | approved_sample_cohort | R-NOV-SAMPLE-2026 |
| NOV-LG-2601-009 | Pacific | 119 | 114 | APPROVED | approved_sample_cohort | R-NOV-SAMPLE-2026 |
| NOV-LG-2601-010 | Mountain | 152 | 146 | APPROVED | approved_sample_cohort | R-NOV-SAMPLE-2026 |
| NOV-LG-2601-011 | Central | 91 | 87 | APPROVED | approved_sample_cohort | R-NOV-SAMPLE-2026 |
| NOV-LG-2601-012 | Northeast | 184 | 176 | APPROVED | approved_sample_cohort | R-NOV-SAMPLE-2026 |

## Q3 ledger rows

| record_id | region | committed_orders | on_time_orders | status | scope | rule |
| --- | --- | ---: | ---: | --- | --- | --- |
| NOV-LG-2603-001 | Central | 137 | 128 | APPROVED | approved_sample_cohort | R-NOV-SAMPLE-2026 |
| NOV-LG-2603-002 | Northeast | 158 | 147 | APPROVED | approved_sample_cohort | R-NOV-SAMPLE-2026 |
| NOV-LG-2603-003 | Southeast | 104 | 97 | APPROVED | approved_sample_cohort | R-NOV-SAMPLE-2026 |
| NOV-LG-2603-004 | Pacific | 172 | 158 | APPROVED | approved_sample_cohort | R-NOV-SAMPLE-2026 |
| NOV-LG-2603-005 | Mountain | 121 | 112 | APPROVED | approved_sample_cohort | R-NOV-SAMPLE-2026 |
| NOV-LG-2603-006 | Central | 189 | 174 | APPROVED | approved_sample_cohort | R-NOV-SAMPLE-2026 |
| NOV-LG-2603-007 | Northeast | 116 | 108 | APPROVED | approved_sample_cohort | R-NOV-SAMPLE-2026 |
| NOV-LG-2603-008 | Southeast | 151 | 140 | APPROVED | approved_sample_cohort | R-NOV-SAMPLE-2026 |
| NOV-LG-2603-009 | Pacific | 127 | 117 | APPROVED | approved_sample_cohort | R-NOV-SAMPLE-2026 |
| NOV-LG-2603-010 | Mountain | 164 | 151 | APPROVED | approved_sample_cohort | R-NOV-SAMPLE-2026 |
| NOV-LG-2603-011 | Central | 99 | 91 | APPROVED | approved_sample_cohort | R-NOV-SAMPLE-2026 |
| NOV-LG-2603-012 | Northeast | 197 | 181 | APPROVED | approved_sample_cohort | R-NOV-SAMPLE-2026 |

## Excluded rows and locator checks

| record_id | period | committed_orders | on_time_orders | status | scope | reason |
| --- | --- | ---: | ---: | --- | --- | --- |
| NOV-LG-X-021 | 2026Q1 | 84 | 81 | CANCELLED | approved_sample_cohort | cancelled commitments are excluded |
| NOV-LG-X-044 | 2026Q3 | 136 | 126 | PENDING | approved_sample_cohort | not approved in the frozen extract |
| NOV-LG-X-053 | 2026Q3 | 143 | 139 | APPROVED | legacy_scope | outside the approved sample cohort |

The source register records 12 eligible regional rows in each quarter and three excluded examples. Row identifiers resolve within this document. The full company review is useful operating context but contains no matching regional numerator and denominator. This ledger is the only bundle in this pair with row-level committed/on-time counts and the effective sample rule needed to validate the requested weighted cohort calculation.

## Source custody

The frozen extract preserves the source office, revision, quarter boundary, and eligibility fields. No company-wide OTD value has been copied into the ledger. The region sequence is kept intact so that a consumer can compare records from more than one operating area and see that both quarters use the same field definitions. Corrections after the frozen revision require a new source revision and a new independent Gold calculation; they are not applied during a run.

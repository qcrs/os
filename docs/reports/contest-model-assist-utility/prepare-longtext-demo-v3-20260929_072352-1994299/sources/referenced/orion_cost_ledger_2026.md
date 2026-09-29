# Orion Approved Sample Expedited Cost Ledger

Document id: `doc-orion-approved-sample-expedited-cost-ledger-2026`
Section id: `sample-ledger`
Corpus: controlled model-assist utility source bundle
Custodian: Orion manufacturing finance control
Revision: 2026-09-18 frozen extract
Effective periods: 2026Q1 and 2026Q3

## Scope and field meanings

This is a row-level ledger for the approved expedited-cost sample, not the Orion company operating review. `expedited_fee_usd` is the fee posted to one approved sample record. `exception_count` is the number of exception events linked to that record; it is not a company-wide operational incident count. For each quarter, sum the fee and exception fields across eligible records and count those records. The requested change is Q3 total minus Q1 total. No quarterly total is stored in this extract.

The active 2026 control includes only rows whose status is `APPROVED`, scope is `approved_sample_cohort`, and rule id is `R-ORI-SAMPLE-2026`. The finance export also retains legacy-scope, pending, and cancelled rows because the analyst must apply the rule rather than trust a prefiltered total. The rule is effective from 2026-01-01 through 2026-12-31. Each row has a stable id and can be traced to its posting record.

## Q1 ledger rows

| record_id | region | expedited_fee_usd | exception_count | status | scope | rule |
| --- | --- | ---: | ---: | --- | --- | --- |
| ORI-FN-2601-001 | Cedar Park | 1487 | 1 | APPROVED | approved_sample_cohort | R-ORI-SAMPLE-2026 |
| ORI-FN-2601-002 | Northeast | 1561 | 2 | APPROVED | approved_sample_cohort | R-ORI-SAMPLE-2026 |
| ORI-FN-2601-003 | Pacific | 1635 | 3 | APPROVED | approved_sample_cohort | R-ORI-SAMPLE-2026 |
| ORI-FN-2601-004 | Midwest | 1709 | 4 | APPROVED | approved_sample_cohort | R-ORI-SAMPLE-2026 |
| ORI-FN-2601-005 | Southeast | 1783 | 1 | APPROVED | approved_sample_cohort | R-ORI-SAMPLE-2026 |
| ORI-FN-2601-006 | Cedar Park | 1857 | 2 | APPROVED | approved_sample_cohort | R-ORI-SAMPLE-2026 |
| ORI-FN-2601-007 | Northeast | 1931 | 3 | APPROVED | approved_sample_cohort | R-ORI-SAMPLE-2026 |
| ORI-FN-2601-008 | Pacific | 2005 | 4 | APPROVED | approved_sample_cohort | R-ORI-SAMPLE-2026 |
| ORI-FN-2601-009 | Midwest | 2079 | 1 | APPROVED | approved_sample_cohort | R-ORI-SAMPLE-2026 |
| ORI-FN-2601-010 | Southeast | 2153 | 2 | APPROVED | approved_sample_cohort | R-ORI-SAMPLE-2026 |
| ORI-FN-2601-011 | Cedar Park | 2227 | 3 | APPROVED | approved_sample_cohort | R-ORI-SAMPLE-2026 |
| ORI-FN-2601-012 | Northeast | 2301 | 4 | APPROVED | approved_sample_cohort | R-ORI-SAMPLE-2026 |

## Q3 ledger rows

| record_id | region | expedited_fee_usd | exception_count | status | scope | rule |
| --- | --- | ---: | ---: | --- | --- | --- |
| ORI-FN-2603-001 | Cedar Park | 1543 | 2 | APPROVED | approved_sample_cohort | R-ORI-SAMPLE-2026 |
| ORI-FN-2603-002 | Northeast | 1617 | 3 | APPROVED | approved_sample_cohort | R-ORI-SAMPLE-2026 |
| ORI-FN-2603-003 | Pacific | 1691 | 4 | APPROVED | approved_sample_cohort | R-ORI-SAMPLE-2026 |
| ORI-FN-2603-004 | Midwest | 1765 | 1 | APPROVED | approved_sample_cohort | R-ORI-SAMPLE-2026 |
| ORI-FN-2603-005 | Southeast | 1839 | 2 | APPROVED | approved_sample_cohort | R-ORI-SAMPLE-2026 |
| ORI-FN-2603-006 | Cedar Park | 1913 | 3 | APPROVED | approved_sample_cohort | R-ORI-SAMPLE-2026 |
| ORI-FN-2603-007 | Northeast | 1987 | 4 | APPROVED | approved_sample_cohort | R-ORI-SAMPLE-2026 |
| ORI-FN-2603-008 | Pacific | 2061 | 1 | APPROVED | approved_sample_cohort | R-ORI-SAMPLE-2026 |
| ORI-FN-2603-009 | Midwest | 2135 | 2 | APPROVED | approved_sample_cohort | R-ORI-SAMPLE-2026 |
| ORI-FN-2603-010 | Southeast | 2209 | 3 | APPROVED | approved_sample_cohort | R-ORI-SAMPLE-2026 |
| ORI-FN-2603-011 | Cedar Park | 2283 | 4 | APPROVED | approved_sample_cohort | R-ORI-SAMPLE-2026 |
| ORI-FN-2603-012 | Northeast | 2357 | 1 | APPROVED | approved_sample_cohort | R-ORI-SAMPLE-2026 |

## Excluded rows and control boundary

| record_id | period | fee_usd | exceptions | status | scope | treatment |
| --- | --- | ---: | ---: | --- | --- | --- |
| ORI-FN-X-019 | 2026Q1 | 2481 | 2 | CANCELLED | approved_sample_cohort | omit cancelled posting |
| ORI-FN-X-043 | 2026Q3 | 2719 | 3 | PENDING | approved_sample_cohort | omit pending approval |
| ORI-FN-X-058 | 2026Q3 | 3017 | 1 | APPROVED | legacy_scope | omit historical cohort |

The source register preserves the full row sequence and does not precompute quarter totals. The active rule and row-level fields are both part of the evidence needed to identify the correct bundle. The company operating review describes higher Q3 expedited freight in aggregate, but it is not this approved cohort and cannot supply the requested sample fee delta or exception counts.

## Source custody

The frozen extract was exported by Orion manufacturing finance control and checked for unique record ids, complete quarter labels, and stable locators. The rule id appears on each eligible row so a reviewer can detect a legacy or stale record without relying on file order. The exception field belongs to the row-level sample transaction, not to the narrative incident register. Updates after this revision require a separately reviewed extract and recomputed Gold; an operating-review revision cannot silently replace this ledger.

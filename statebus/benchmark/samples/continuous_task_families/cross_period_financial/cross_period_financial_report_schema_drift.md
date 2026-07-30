# Cross-Period Financial Review - Schema Drift Edition

Document id: `doc-cross-period-financial-schema-drift`

## Scope

This authorized report republishes the same ACME and BETA quarterly revenue series with reordered columns, an explicit currency column, and public header aliases. It is intended to validate schema-aware table extraction without changing the underlying business facts.

## ACME Revenue Table

| revenue_usd_millions | period | currency |
| ---: | --- | --- |
| 98 | 2025Q3 | USD |
| 109 | 2025Q4 | USD |
| 120 | 2026Q1 | USD |

## BETA Revenue Table

| revenue_usd_millions | period | currency |
| ---: | --- | --- |
| 72 | 2025Q3 | USD |
| 79 | 2025Q4 | USD |
| 87 | 2026Q1 | USD |

## Notes

The public aliases are `period -> quarter` and `revenue_usd_millions -> revenue_musd`. The currency column is informational and does not alter the values.

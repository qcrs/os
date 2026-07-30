# Orion Factory Systems 2026 Operating Review

Document id: `doc-orion-factory-ops-2026`

## Executive Overview

Orion Factory Systems supplies motion-control assemblies and predictive-maintenance software to industrial customers. The 2026 operating review covers the first three quarters after Orion consolidated two regional assembly lines into the Cedar Park manufacturing hub. Management expected the consolidation to raise throughput and improve revenue visibility, but the transition created a temporary training backlog in Q2 and higher expedited freight spend in Q3.

Revenue increased each quarter as the installed base expanded and renewal rates improved. Gross margin held above 39 percent, although margin declined in Q3 because expedited freight and supplier qualification work raised unit costs. Operating expense rose steadily as Orion hired reliability engineers and funded a new field diagnostics team. Churn stayed below five percent, but Q3 churn rose after several enterprise customers delayed maintenance-window approvals. On-time delivery weakened in Q3 when two high-volume encoder suppliers missed September slots.

The dataset is designed for repeated multi-agent metric extraction. The table below is the stable corpus prefix used by the KV prefix reuse probe. Subsequent tasks ask for different metrics from the same report so the content is realistic while still deterministic.

## Metric Table

| quarter | revenue_musd | gross_margin_pct | operating_expense_musd | churn_rate_pct | on_time_delivery_pct |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2026Q1 | 184 | 41.2 | 57 | 3.2 | 96.4 |
| 2026Q2 | 197 | 40.5 | 61 | 3.6 | 94.1 |
| 2026Q3 | 211 | 39.7 | 66 | 4.4 | 90.8 |

## Revenue Drivers

The revenue increase from Q1 to Q3 came from three sources. First, four automotive customers expanded orders for servo controller kits after validating Orion's new vibration-monitoring firmware. Second, the retrofit program for older assembly lines produced a larger mix of software-attached hardware sales. Third, the service team converted several one-time inspection projects into annual contracts. Finance attributed roughly half of the Q3 sequential gain to subscription attach and half to higher hardware volume.

## Margin And Cost Notes

Gross margin softened because expedited freight increased in late August and because the new Cedar Park line required extra inspection labor during supplier qualification. The finance controller flagged motor-driver boards and high-resolution encoders as the main pressure points. The procurement team expects relief in Q4 after a second encoder supplier completes reliability testing. No one-time restructuring charge is included in the operating expense line; the table reflects recurring operating expense only.

## Customer Retention Notes

Churn rose to 4.4 percent in Q3. The customer success team traced the increase to delayed deployment windows for three enterprise manufacturing accounts. None of the churned accounts were in the top ten by annual contract value, but two had high reference value in the automotive vertical. Management assigned a dedicated deployment coordinator to the affected segment.

## Delivery Notes

On-time delivery fell from 96.4 percent in Q1 to 90.8 percent in Q3. The operations team linked the decline to supplier misses and training delays on the consolidated line. A temporary night shift was approved for October, and logistics contracts were renegotiated to reduce emergency shipping cost.

## Management Actions

Management approved five actions: complete second-source qualification for encoders, move firmware validation earlier in the sales cycle, assign deployment coordinators to enterprise accounts, reduce Q4 emergency freight by reserving carrier capacity, and publish a weekly risk dashboard for high-volume purchase orders.

## Segment Detail

The motion-control hardware segment remained the largest revenue contributor. Orders for servo controller kits increased after two automotive customers completed line-trial acceptance. The predictive-maintenance software segment grew more slowly but improved revenue quality because subscription attach rates were higher on retrofit projects than on new assembly-line projects. Field services remained capacity constrained. Several customers requested installation support in shorter maintenance windows, which created scheduling conflicts for the reliability engineering team.

The Cedar Park hub consolidation changed the operating cadence. Before the consolidation, regional lines carried overlapping safety stock and used separate inspection routines. After consolidation, inventory visibility improved, but training requirements were concentrated in one location. The production manager reported that Q2 output recovered faster than expected, while Q3 reliability checks took longer because new supplier lots required additional inspection.

## Evidence Notes For Reuse

The same metric table supports multiple downstream questions. A revenue query, a margin query, and a delivery query all need the same stable report context: the business overview, the metric definitions, and the quarter table. Only the requested metric name changes. This makes the report suitable for cache-aware scheduling experiments because the shared prefix should remain identical while role-specific instructions and requested outputs vary.

The table values should be treated as authoritative. Narrative paragraphs are provided to make retrieval realistic and to give the summarizer enough context for non-numeric explanations. If a numeric value in a narrative sentence conflicts with the metric table, the metric table wins. No such conflict is intentionally present in this report.

## Metric Definitions

`revenue_musd` is recognized revenue in millions of US dollars for the quarter. `gross_margin_pct` is gross profit divided by revenue. `operating_expense_musd` includes recurring sales, support, engineering, and general administrative cost, but excludes one-time restructuring charges. `churn_rate_pct` is quarterly customer revenue churn. `on_time_delivery_pct` is the percentage of customer orders delivered within the committed delivery window.

## Risk Register

The highest operational risk is supplier concentration in high-resolution encoders. A second risk is the backlog of deployment windows for enterprise accounts. A third risk is emergency freight cost, which can reduce margin even when revenue grows. Management believes the risks are manageable because no single customer cancellation materially changes the revenue outlook, but the combination of supplier misses and deployment delays can affect customer confidence.

## Q4 Watch Items

The finance team will monitor whether Q4 revenue growth is supported by subscription attach rather than only hardware volume. Operations will monitor on-time delivery recovery after second-source qualification. Customer success will track whether deployment coordinators reduce churn risk among enterprise manufacturing accounts. The weekly risk dashboard will combine purchase-order status, deployment-window status, and freight-cost exceptions.

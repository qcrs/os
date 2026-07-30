# Nova Retail Logistics 2026 Operating Review

Document id: `doc-nova-retail-ops-2026`

## Executive Overview

Nova Retail Logistics operates regional fulfillment centers for specialty retailers. The 2026 operating review covers the first three quarters after Nova rolled out a new warehouse slotting system and expanded same-day delivery coverage in three metro areas. The program lifted order volume, but it also created pressure on delivery reliability while the new carrier mix stabilized.

Revenue grew through Q3 as Nova added two apparel customers and increased same-day delivery penetration. Gross margin improved in Q2 when route density increased, then eased in Q3 because temporary labor and cross-dock overflow charges rose during peak back-to-school demand. Operating expense increased as Nova staffed a network-planning team and paid for slotting-system support. Churn remained modest, but Q3 churn rose after one specialty retailer moved low-margin overflow work back in-house. On-time delivery declined in Q3 as two carrier partners missed weekend coverage commitments.

This report intentionally mirrors the Orion report structure while representing a different operational domain. It is realistic enough for retrieval and summarization tasks, but deterministic enough for metric validation. The KV prefix probe uses repeated questions over this report to test whether StateBus can keep same-corpus tasks adjacent when desired.

## Metric Table

| quarter | revenue_musd | gross_margin_pct | operating_expense_musd | churn_rate_pct | on_time_delivery_pct |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2026Q1 | 142 | 36.8 | 44 | 2.8 | 95.7 |
| 2026Q2 | 156 | 37.4 | 47 | 3.1 | 93.6 |
| 2026Q3 | 169 | 36.2 | 53 | 4.0 | 89.9 |

## Revenue Drivers

Nova's revenue increase was driven by customer additions and higher same-day order density. The apparel segment accounted for the largest contribution in Q2, while the specialty home segment contributed more in Q3. Management noted that same-day delivery volume is more profitable when routes are dense, but margin falls quickly when weekend coverage requires spot-market carrier capacity.

## Margin And Cost Notes

Gross margin reached 37.4 percent in Q2 before dropping to 36.2 percent in Q3. The Q3 decline came from overflow cross-dock charges, temporary labor, and carrier premiums. The network-planning team believes margin can recover if order cutoff times are moved forward by thirty minutes and if weekend demand is allocated to two additional regional carriers.

## Customer Retention Notes

Churn increased to 4.0 percent in Q3. The lost revenue came mostly from low-margin overflow work, but the churn event still matters because it reduced route density in one metro area. Account managers reported that the customer objected to missed weekend delivery windows rather than price.

## Delivery Notes

On-time delivery declined from 95.7 percent in Q1 to 89.9 percent in Q3. Two carrier partners missed coverage commitments during August and September. Nova created a carrier scorecard and moved the weakest weekend lanes to contingency carriers for the first month of Q4.

## Management Actions

Management approved five actions: renegotiate weekend carrier commitments, adjust order cutoff times, expand contingency carrier coverage, automate slotting exception review, and use daily route-density forecasts to decide when same-day orders should be capped.

## Segment Detail

The apparel fulfillment segment produced the highest order volume and benefited most from the new slotting system. Apparel orders were predictable during weekday demand peaks, so route density improved and picking paths shortened. The specialty home segment was more volatile. Large items required more cross-dock handling, and weekend delivery coverage depended on carrier availability in a smaller number of metro lanes.

Nova's same-day delivery expansion created a useful revenue tailwind, but the expansion also changed cost behavior. Dense routes improved gross margin in Q2. In Q3, temporary labor and overflow cross-dock charges offset the volume benefit. The network-planning team reported that margin pressure was concentrated in a limited number of weekend lanes, which makes the issue operationally addressable rather than structural.

## Evidence Notes For Reuse

The report is intended to support repeated questions over the same corpus. A revenue query, a margin query, an operating-expense query, and a delivery query all use the same business context and the same metric table. StateBus should be able to identify this shared corpus and group the tasks when running in a cache-friendly schedule. The requested metric changes, but the long report prefix should remain stable.

The metric table is the authoritative source for numeric validation. Narrative text exists to make the document realistic for semantic retrieval and summarization. If a narrative sentence is less precise than a table cell, the table cell should be used for deterministic validation. The report intentionally avoids hidden values or ambiguous aliases so that failures are attributable to retrieval, scheduling, or prompt construction rather than data quality.

## Metric Definitions

`revenue_musd` is recognized fulfillment and logistics revenue in millions of US dollars for the quarter. `gross_margin_pct` is gross profit divided by revenue after carrier and warehouse labor cost. `operating_expense_musd` includes recurring network planning, customer support, technology, and general administrative expense. `churn_rate_pct` is quarterly customer revenue churn. `on_time_delivery_pct` is the percentage of orders delivered inside the committed customer window.

## Risk Register

The highest operational risk is weekend carrier reliability. A second risk is route-density loss if low-margin overflow work exits a metro area. A third risk is temporary labor dependence during seasonal peaks. Management believes the risk profile is manageable because the same-day program still increases revenue quality when route density is high. The main control point is deciding when to cap same-day promises before the carrier network becomes unstable.

## Q4 Watch Items

The finance team will monitor whether Q4 margin recovers as weekend carrier contracts reset. Operations will track whether adjusted order cutoff times reduce late-route exceptions. Customer success will monitor whether the lost overflow customer affects adjacent retailers in the same metro area. The network-planning team will publish daily route-density forecasts to help decide when new orders should be accepted, delayed, or moved to contingency carriers.

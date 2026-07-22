# Cobalt Same-Day Network Control Review

Document id: `doc-cobalt-same-day-control-playbook`

## Review Purpose

Cobalt Commerce Logistics uses this playbook to select a bounded operating
branch for the Harbor East same-day network. The document is narrative by
design: current observations, branch thresholds, actions, and fail-closed rules
are separated so that a reviewer must combine them before making a decision.

## Current Network Observation

Weekend carrier acceptance in Harbor East has fallen to 78 percent. Written
offers from contingency carriers can cover 74 percent of the affected weekend
volume. Average route density remains 128 orders per route, so the region still
has enough density to preserve the economics of a bounded same-day service.

The service desk has not recorded a structural demand collapse. The immediate
problem is weekend carrier reliability, not weekday order creation. Operations
therefore must use the thresholds below instead of treating all same-day demand
as equally risky.

## Plan Green: Controlled Expansion

Plan Green permits additional same-day promises only when primary weekend
carrier acceptance is at least 90 percent for two consecutive weekends and
route density is at least 135 orders per route. Green is an expansion branch;
it is not authorized merely because one weekend improves.

## Plan Bridge: Stabilized Service

Plan Bridge applies when primary weekend carrier acceptance is below 85
percent, contingency written coverage is at least 70 percent, and route density
remains at or above 120 orders per route. The branch preserves a bounded service
while shifting the weakest lanes away from unreliable primary carriers.

On entering Plan Bridge, the control desk must cap same-day promises at the
current volume before 14:00 and move the weakest weekend lanes to contingency
carriers for the first month of the response. The cap is a control action, not
a cancellation of already accepted orders.

## Plan Hold: Fail-Closed Branch

Plan Hold applies immediately if contingency written coverage drops below 70
percent or route density falls below 120 orders per route. Under Hold, Cobalt
stops accepting new same-day promises for the affected weekend lanes and keeps
only already committed deliveries in the dispatch plan.

Plan Hold is also the mandatory fallback from Plan Bridge when either guardrail
fails. Managers may not remain in Bridge by averaging a weak weekend with a
strong weekday.

## Transition Discipline

The network may leave Bridge for Green only after both Green conditions have
been observed, including the two-consecutive-weekend requirement. Until then,
the current-volume cap and contingency allocation remain active.

These branches are operating decisions grounded in the review. They are not
evidence that the StateBus Runtime performed a controller-level replan.

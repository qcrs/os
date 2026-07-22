# Atlas Component Continuity Review And Playbook

Document id: `doc-atlas-component-continuity-playbook`

## Review Purpose

Atlas Motion Products uses this review when supply interruptions threaten the
optical encoder used in its precision actuator line. The review combines the
current signed observations with the approved operating branches. It is not a
forecast model and it does not permit managers to invent a fourth branch when
the stated conditions are inconvenient.

## Current Signed Observations

The primary encoder supplier missed two confirmed shipment slots during the
last ten days. Procurement has not received a replacement commitment that can
be treated as firm. Available encoder buffer covers five production days at the
current high-priority build rate.

An alternate supplier has delivered samples, but its reliability qualification
is still incomplete. The lab expects to finish the decisive reliability test
on Friday. Until that test passes, the alternate source must be treated as
unqualified even if its commercial terms are acceptable.

Customer commitments extend across the next three weeks. Some low-priority
demonstration builds can move without contractual penalty, while medical and
industrial safety orders retain their committed sequence.

## Branch Cedar: Normal Scheduling

Plan Cedar applies when the primary supplier has missed no more than one
confirmed slot and usable buffer covers at least twelve production days. Under
Cedar, planners keep the normal build sequence and do not reserve emergency
freight. A verbal warning from a supplier does not by itself leave this branch.

## Branch Copper: Containment

Plan Copper applies when the primary supplier has missed at least two confirmed
slots, usable buffer is below seven production days, and the alternate source
is not yet qualified. All three conditions must be evaluated from signed
observations.

Within 24 hours of entering Plan Copper, scheduling must freeze low-priority
builds and procurement must reserve emergency freight for the protected
high-priority sequence. Copper does not cancel customer commitments; it narrows
which builds consume the remaining qualified stock.

## Branch Silver: Qualified Recovery

Plan Silver begins only after the alternate supplier passes reliability
qualification. When the Friday test passes, Atlas switches to Plan Silver on
Monday, releases the alternate lot into the protected sequence, and phases out
emergency freight after receipt inspection.

Commercial agreement without a passed reliability test is insufficient. The
branch transition depends on technical qualification, not on a manager's
confidence that the test will probably pass.

## Fail-Closed Rule

If the alternate supplier fails the Friday reliability test, Atlas must
continue Plan Copper and cap new customer commitments until qualified buffer
again exceeds seven production days. The team may reschedule low-priority
demonstration builds, but it may not move to Plan Silver or consume the failed
alternate lot.

## Governance Note

These names describe operating-plan branches selected from document evidence.
They do not represent a StateBus Runtime Controller replan event. A later
observation may change the selected branch, but only the stated trigger and
guard conditions authorize that change.

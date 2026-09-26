# Sample Jobs

Browser-testing walkthroughs (RM, 2026-09-23). Six projects that together
exercise the September work: per-unit lines, Tasks-page bundling (all
states), un-stamp on removal, create-time money overrides, catalog
descriptions, flat-fee schemes, CO line-first + the CO lens, comment
lines, the outsourced-work port (task-linked POs, reconciliation, rate
prompt), and rule-2 invoice seeding.

## 1. Ten cabinets (the flagship per-unit + outsourced run)

Customer inquiry as follows (you can email this to minibini.test@gmail.com
and then find it in the Email section of the app):

"
Hi Neal's, I need 10 more of the same cabinets you are making for me on job #08157,
but these need to be made from MDF and painted blue, I'll send you a Pantone
color number in a bit.  Let me know what this will cost and when you can have
them ready.

Marshall Prather
Verkada
"

Make a job, plan ONE cabinet's work on the Tasks page — cut parts,
assemble, attach doors, plus a "Painting (subcontracted)" task with a
typed rate (create-time money override) — then one-click **Start Estimate
& Bundle** the set one-unit ×10 with **split materials on**. Accept, cut a
PO to the painter with its line **task-linked**, receive it, complete the
painting task (settle-up), then reconcile with a final price that differs
from ordered and **Accept the rate prompt** (works on the completed task —
the carve-out). Finish by starting an invoice: the line should arrive on
full actuals reflecting the accepted rate.

## 2. Custom desk with a mid-quote mistake (correction loop)

Customer inquiry:

"
Hi, please quote me to make a desk with an inlay on the top.  I'm attaching
the image I want to be inlaid in black and gold epoxy.  I want the desk to have
one small drawer on the right side, and two panels on each end instead of legs
or like the sides of a box?  And the back should have a panel across the top
about 1' long.  A partial box side, if that makes sense.  I know you'll have to
do some design work on this first.

What's the approximate price this would be from white oak, or from walnut?

Frenchy
"

One desk, three or four tasks bundled per-unit — then deliberately fumble:
hand-edit one task's est qty (drift badge → modal → **Revert**), and
remove another task from the line entirely, checking its values snap back
to one-unit (un-stamp) before re-bundling it. Add one catalog line via Add
Line and **edit its prefilled description** before saving. Good place to
also try appending to the per-unit line (should refuse with "remove and
bundle again" — now honest advice).

## 3. Sign package with a change order (CO lens + comments)

This job has two communications from the customer, the initial inquiry and
then, after the job has been accepted, a change.  Email one:

"
Hi, I need a sign for my shop, cutout letters saying 'Herb's Sandwiches and Salads'
plus the outline of the sandwich.  I've got someone to paint them, I just need
the shapes.  Material is 1" HDU foam.
"

After acceptance, the customer writes,

"
I forgot about the frame this sign will go on, which sits above the shop.
Can you come out and measure it to make sure it will fit up there?  And
how should I attach it?
"

Quote and accept a sign job, then while it's active add two unquoted tasks
(extra brackets, site survey). Put the job on hold, start a CO from the
estimate page (the hint link on the Tasks page should point you there),
and bundle the pre-hold tasks into the CO **from the Tasks page** — note
the "on est" chips on agreement work vs. real checkboxes on the unquoted
tasks. Add a comment ADD line ("Customer supplying artwork") and a
**comment REPLACE** on one estimate line (annotated removal), then accept
and check the amended agreement: replaced line gone, comments informational
only, its task descoped.

## 4. Flat-fee and preset day (money-at-add-time)

Customer email:

"
I need my logo engraved on a wooden plaque with the words, "on your side since
'75" going over and under it in a curve.  So "On Your Side" in an arch above
the logo, and "Since '75" in a smile-shape underneath.  I want a script font
but not too loopy.  Please deliver when done.
"

A small engraving job: an engraving preset task with modifiers, a delivery
task on the **flat-fee scheme with the price typed in the Add Task modal**,
and a comment line on the estimate ("2-week turnaround"). Send it — the
comment must not block the send gate — accept, complete only the engraving
task, then start an invoice: the fully-done line seeds on actuals while
the partially-backed one (if you bundled several tasks together) is
**skipped entirely**, its finished work waiting in the unbilled pool
(rule 2).

## 5. Waterjet brokerage (service-PO stress test)

Customer email:

"
I need 200 of the attached L shapes, with thru holes, cut from 1/2" brass,
and 100 of the circles with the center hole from 1/4" brass.
"

A mostly-outsourced job: one entered-qty "Waterjet cutting" task denominated
in parts, estimate, accept. Cut ONE PO with **two lines linked to that same
task** (two material thicknesses) — this deliberately shows the known
per-line rate-prompt naivety (two prompts, one task; it's in LATER).
Mid-job, cancel the task after the vendor partially delivered and billed:
reconcile with a final on its line and confirm the **prompt still offers
the cancelled task**, then stop-and-bill the job and pull the cancelled
task's actuals onto the invoice from the pool.

## 6. Quickie from nothing (state B and guardrails)

Customer email:

"
Please give me pricing for 200 squares, 10" x 10", from 1/4" MDF (I assume
you can make the drawing, i't just a square).  Please provide the material
as well. Can you give me a quote for how much each square costs overall?
I'll need more of these later and my boss wants the per-unit price.  Also
can you deliver?
"

Fresh job, three quick tasks, select them immediately (checkboxes live
before any estimate exists) and **"Start Estimate & Bundle 3 into a
line…"** in one click. Poke the guardrails: try creating a second estimate
(refused — one draft per job), add a line from the catalog with an edited
description, then discard the whole draft (atoms stay at stamped totals —
ruled acceptable, you're scrapping anyway) and start over. End by invoicing
with a comment line present and sending — the send link must render.

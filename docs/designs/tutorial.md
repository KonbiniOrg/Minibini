# Minibini: A Getting-Started Tutorial

Minibini is a job shop management system. It tracks a job from the first
customer email through quoting, work on the floor, time tracking,
materials, purchasing, and invoicing (with payments synced from
QuickBooks Online). This tutorial walks the life of one job, and provides
a brief introduction to the other features of the software. It assumes
you know how a job shop runs but have never seen Minibini.

## Finding your way around

Minibini runs in your browser. After you log in, the sidebar on the left
is the whole map: **Home** (your work, your shifts, your expenses),
**Jobs** (the board), **Schedule**, **Activity** (who's
working right now), **Contacts**, **Email**, **Purchasing**, **Catalog**
(inventory and service items), and — depending on your permissions —
**Invoices**, **Expenses**, **Users**, and **Settings**.  The
sidebar slides out from the hamburger menu on the top left of the screen.

The **Job Board** is the overview of all shop work. It's a four-column
kanban view of every current job: **Pipeline** (being quoted), **In
Progress** (released to the floor, with a column per worker for assigning
individual tasks), **Unpaid** (work done, money outstanding), and **Closed**.
Click any card to open the job detail.

## The main organizing concept

A **Job owns its work**. Everything billable on a job is one of three
kinds of *atom*, all listed on the job's task-list page:

- **Task** — a metered unit of work, like "CNC cut 12 rectangles" or "draw
  3d model of chair". Every task is priced by a **rate scheme**, either
  by elapsed time on the clock or by a quantity the worker enters (pieces,
  machine-minutes).  Common tasks are kept in the Service Items catalog.
- **Material** — a physical item, either picked from the Materials catalog
  (which reserves stock — see Materials below) or typed in freeform.
- **Fee** — a fixed charge, `quantity × unit rate`. No timer, no stock;
  just a price.

Estimates and invoices are *documents built from those same atoms*. The
estimate prices what you **expect** (a task's estimated quantity); the
invoice bills what **actually happened** (logged time, entered counts,
consumed materials). You don't maintain the estimate and the invoice
separately — they're both linked to the same work.

## Estimating

1. **Create the job.** Start a new job from the button on the board's
   header, or straight from a customer email on the Email page ("create
   job from email").  This also lets you create the contact and business
   if they're new. The job starts as a **draft**.
2. **Add the work.** On the job, add tasks, materials, and fees by hand,
   or pick from the **Service Items** or **Materials** catalogs. Give
   each task an estimated quantity and an estimated worker time (used for
   planning work). Also list the job's **Deliverables** — the customer-facing
   "what you get" list. These are considered part of the estimate, and are
   used to generate packing lists for completed work.
3. **Build the estimate.** Start an estimate and pull the job's atoms
   onto customer-facing line items (the estimate's **Reconcile** view
   shows the unclaimed atoms on one side and the line items on the
   other).  You can assign one line per atom, or combine several atoms into
   one line the customer will understand, as when they request a per-unit
   price for pieces that take multiple steps to make. You can also type
   hand lines and percentage adjustments (rush fee, discount) directly.
4. **Send it.** Email the customer a PDF plus a **portal link** where they
   can accept, reject, or request changes — no login required on their end.
   The job moves to the **submitted** state. Estimates expire automatically
   after a configurable number of days. If the customer wants changes, the
   estimate can be revised — the old estimate is kept and marked superseded,
   and the new one sent to the customer with an incremented version number.
5. **Acceptance.** When the estimate is accepted the job becomes
   **approved**: hand-written lines crystallize into real Fee and
   Material atoms, and stock is earmarked for the job.  A worker must review
   the job at this point and ensure the necessary materials and tasks are
   listed, and then release the job to the shop floor.  Now it is **in progress**,
   and displayed in the In Progress area of the Job Board.

After acceptance, any scope changes go through a **Change Order**: put the
job on hold (holding pauses new work but keeps history), draft the CO,
and send it to the customer through the same portal. Accepting it updates the
agreement and releases the hold automatically.

## Doing the work

Workers clock in from the top banner (a **shift**), then hit **Start**
on a task — theirs from the board or schedule, or any task they walk up
to. Each work session is recorded as a **timeslip** — who, which task,
start, and stop. One session at a time per person; starting a second task
closes the first. Starting the day's first task even clocks you in
automatically.

- The first Start on a task moves it to *in progress* and consumes its
  materials from stock.
- Two people can work the same task ("join"), or one can take it over.
- Tasks can be **blocked** with a reason, and completed from any state.
- On count-based tasks, stopping or completing prompts "how many?"
- Forgot to log time? Add a historical entry — your own, within the last
  30 hours; older or someone else's needs a time manager.
- You can work on a task assigned to someone else; workers can use their
  judgement on this

The **Job Board**'s in-progress tab is intended for reviewing work by
several workers at once, assigning work and prioritizing, with all current
jobs and tasks visible.  Drag tasks to a worker's queue to assign or reorder
them.  You can filter one or a few jobs' tasks by clicking on the job's
chip in the top row.

The **Schedule** page lays each worker's assigned tasks on a calendar: dark bars
are logged work, light bars are the forecast from estimated times, split
at a live "now" line. Drag bars to reorder a worker's queue.

When every task on a job is complete or cancelled, the job advances to
**work_complete** automatically.

## Catalog tasks, inventory, and purchasing

The **Catalog** is the shop's price list. It has three tabs: **Service
Items** (the reusable task definitions), **Inventory** (the items),
and **Earmarks** (every active stock reservation, shop-wide). Things
to know about inventory:

- Each Material item shows **on hand**, **earmarked** (reserved by jobs),
  **available** (the difference), and **on order** (outstanding PO
  quantity). Putting a catalog material on a job earmarks stock the
  moment it's approved; starting the associated task consumes it.
- Sell price defaults from cost via a configurable **markup percent**
  at creation; after that, the stored price is what you edit.
- Items are never auto-hidden or deleted — a zero-stock item stays
  findable as history ("what did we pay last time"). Retire one by
  deactivating it; **write off** spoiled or wasted stock; **merge**
  accidental duplicates.
- A one-off material typed freeform on a job gets its own `LOT-` item
  behind the scenes once it's costed and purchased, so even one-time
  buys are tracked stock — and next year's search can find and reuse
  the lot.

When there's not enough of a Material in inventory, a **Purchase Order**
button is shown in the job page.  You can also make one under Purchasing.
PO lines attributed to a job create that job's materials automatically.
Email the PO to the vendor as a PDF, and receive it when the materials
arrive to update QOH value.  The vendor's invoice is entered and paid in
QuickBooks Online; link the invoice email to the PO so the PO's Email
panel shows it arrived.

## Finalizing a Job

Once all Tasks are complete, the job moves into the **work complete** stage.
Now, or beforehand if it makes sense, create a **Shipment** based on the
Deliverables.  You can configure some or all of them as ready for pickup
or delivery.  Print a packing list for the customer or courier's signature
and mark the shipment picked up when it's been picked up.

## Getting paid

From a job that's work-complete (or anywhere along the way — deposits
and progress billing are fine), open an invoice and build it exactly the
way you built the estimate: its Reconcile view offers the job's billable
atoms — completed tasks at their actual quantities, consumed materials,
fees, loose expenses.  Each atom can only ever be claimed by one
invoice, so double-billing is structurally impossible.  The invoice is
fully editable by the user so if you don't want to charge according to the
actual work for whatever reason, you don't have to.  And you can always
see what work was billed and what wasn't. Send the invoice (PDF
email again), and it's pushed to QuickBooks Online; Minibini polls QBO
and flips the invoice to partly-paid/paid as payments land. When all
invoices are resolved and all deliverables picked up, the job closes itself
as **completed**.

## Shop configuration (Settings)

The **Settings** page (config permission required) is where the shop is
tuned, in six tabs:

- **Accounting** — the QuickBooks Online connection, accounting
  categories (every billable thing carries one; they drive taxability
  and QBO income mapping), which QBO payment accounts to poll, and any
  sync failures needing attention.
- **Setup** — document numbering patterns (job, invoice, PO numbers),
  estimate expiry days, how long closed jobs linger on the board, and
  the list of measurement units the whole system validates against.
- **Pricing** — the **service price list** (rate schemes: name, rate,
  billing algorithm, percent modifiers like "messy materials +10%") and
  the default material markup. One rule to internalize: once a service
  price has been used by real work it is **frozen** — changing the
  price means creating a new version, and existing work keeps billing
  at the rate it was sold at.
- **Schedule** — the shop's default work week (days, hours, breaks)
  that drives the schedule's forecasting.
- **Email** — subject/body templates for outbound estimates, invoices,
  and POs.
- **Business** — your notification email, public site URL, and email
  domain.

## Your own settings

Everyone has a **Profile** tab on Home (click your name at the bottom of
the sidebar) with account info and a password change. The **FULL / LITE**
toggle in the sidebar switches view modes — lite pares pages down to
the essentials. Your personal **work week** — if it differs from the
shop's — is set on Home → Shifts, and the schedule forecasts your queue
inside those hours.  You can review your recent Shifts and time slips,
make adjustments for recent errors or request adjustments for older
ones.  You also have a list of assigned tasks, and you can submit
**Expenses** if you bought something for the shop on your own dime.

Admins manage accounts, permissions, and other people's schedules on the
**Users** page.  Non-admins can see who's here now, what they're working
on, and what their schedules are.

## A few more things worth knowing

- **Everything is logged.** Jobs, estimates, and invoices keep a full
  history — status changes, edits, and freeform notes anyone can add.
  Look for the History panel on a record's page.
- **Email is a workspace, not just an inbox.** The Email page shows the
  shop's mailbox; from a message you can create a job (with the contact
  and business created along the way), or link it to an existing job
  or PO. Documents Minibini sends are recorded too and show up on
  the job's own Email panel.
- **Search** (the box at the bottom of the sidebar) finds jobs,
  contacts, businesses, documents, and catalog items in one query.
- **Expenses** — workers submit expenses from Home → Expenses (tied to
  a job or standalone), managers approve reimbursements, and job-tied
  expenses show up as billable atoms in invoicing.
- **Activity** shows who's clocked in and working on what right now,
  plus recent sessions and document events — the shop's live pulse.
- **Deliverables and shipments.** The deliverables list you wrote at
  quoting time becomes the fulfillment checklist: prepare shipments,
  print packing lists, and record pick-ups. A job only closes when
  everything is picked up.

## Who can do what

Everyone logged in can see nearly everything, work tasks, and track
their own time and expenses. Four permission atoms gate the rest:
**jobs** (create estimates and contacts, job admin), **financials**
(create invoices, POs), **time** (editing others' time), and
**config** (settings, templates, users). A job's **project manager**
gets job-level powers on that one job without the global permission.

That's the loop: quote it, win it, work it, buy for it, bill it — one
job, one set of atoms, start to finish.

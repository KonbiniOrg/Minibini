# Minibini: A Getting-Started Tutorial

Minibini is a job shop management system. It tracks a job from the first
customer email through quoting, work on the floor, time tracking,
materials, purchasing, and invoicing (with payments synced from
QuickBooks Online). This tutorial walks the life of one job. It assumes
you know how a job shop runs but have never seen Minibini.

## Finding your way around

Minibini runs in your browser. After you log in, the sidebar on the left
is the whole map: **Home** (your clock-in band, your work, your time,
your expenses), **Jobs** (the board), **Schedule**, **Activity** (who's
working right now), **Contacts**, **Email**, **Purchasing**, **Catalog**
(inventory and service items), and — depending on your permissions —
**Invoices**, **Bills**, **Expenses**, **Users**, and **Settings**.

The **Job Board** is the place most people live. It's a four-column
kanban view of every current job: **Pipeline** (being quoted), **In
Progress** (released to the floor, with a column per worker), **Unpaid**
(work done, money outstanding), and **Closed**. Click any card to open
the job.

## The one idea to understand

A **Job owns its work**. Everything billable on a job is one of three
kinds of *atom*, all listed on the job's task-list page:

- **Task** — a metered unit of work. Every task is priced by a **rate
  scheme** (an entry in the shop's service price list — "Hourly Labor,"
  "CNC Router"), either by elapsed time on the clock or by a quantity
  the worker enters (pieces, machine-minutes).
- **Material** — a physical commitment, either picked from the Catalog
  (which reserves stock — see Materials below) or typed in freeform.
- **Fee** — a fixed charge, `quantity × unit rate`. No timer, no stock;
  just a price.

Estimates and invoices are *documents built from those same atoms*. The
estimate prices what you **expect** (a task's estimated quantity); the
invoice bills what **actually happened** (logged time, entered counts,
consumed materials). You don't maintain the quote and the bill
separately — they're two views of the same work.

## Quoting a job

1. **Create the job.** From the board's Pipeline column, or straight
   from a customer email on the Email page ("create job from email,"
   which also creates the contact and business if they're new). The job
   starts in **draft**.
2. **Add the work.** On the job, add tasks, materials, and fees by hand,
   or pick from **Service Items** — reusable, pre-priced task
   definitions kept in the Catalog. Give each task an estimated
   quantity and an estimated worker time (the schedule uses the
   latter). Also list the job's **Deliverables** — the customer-facing
   "what you get" list — since an estimate can't be sent without at
   least one.
3. **Build the estimate.** Start an estimate and pull the job's atoms
   onto customer-facing line items (the estimate's **Reconcile** view
   shows the unclaimed atoms on one side and the line items on the
   other) — one line per atom, or several atoms bundled into one line
   the customer will understand. You can also type hand lines and
   percentage adjustments (rush fee, discount) directly.
4. **Send it.** Sending emails the customer a PDF plus a **portal
   link** where they can accept, reject, or request changes — no login
   required on their end. The job moves to **submitted**. Estimates
   expire automatically after a configurable number of days. If the
   customer wants changes, the estimate revises — the old version is
   kept and marked superseded, and the customer sees one estimate
   number throughout.
5. **Acceptance.** When the estimate is accepted the job becomes
   **approved**: hand-written lines crystallize into real Fee and
   Material atoms, and stock is earmarked for the job.

After acceptance, scope changes go through a **Change Order**: put the
job on hold (holding pauses new work but keeps history), draft the CO,
and send it through the same portal. Accepting it updates the agreement
and releases the hold automatically.

## Doing the work

Workers clock in from the Home page (a **shift**), then hit **Start**
on a task — theirs from the board or schedule, or any task they walk up
to. Each work session is recorded as a **timeslip** — who, which task,
start, and stop. One session at a time per person; starting a second task
settles the first. Starting the day's first task even clocks you in
automatically.

- The first Start on a task moves it to *in progress* and consumes its
  materials from stock.
- Two people can work the same task ("join"), or one can take it over.
- Tasks can be **blocked** with a reason, and completed from any state.
- On count-based tasks, stopping or completing prompts "how many?"
- Forgot to log time? Add a historical entry — your own, within the last
  30 hours; older or someone else's needs a time manager.

The **Schedule** page lays each worker's queue on a calendar: dark bars
are logged work, light bars are the forecast from estimated times, split
at a live "now" line. Drag bars to reorder a queue. When every task on a
job is complete or cancelled, the job advances to **work_complete** by
itself.

## Materials, inventory, and purchasing

The **Catalog** is the shop's item list — every physical thing, one row
per item, with a code, cost, sell price, and quantity on hand. It has
three tabs: **Inventory** (the items), **Service Items** (the reusable
task definitions), and **Earmarks** (every active stock reservation,
shop-wide). Things worth knowing about inventory:

- Each item shows **on hand**, **earmarked** (reserved by jobs),
  **available** (the difference), and **on order** (outstanding PO
  quantity). Putting a catalog material on a job earmarks stock the
  moment it's added; starting the task consumes it.
- Sell price defaults from cost via a configurable **markup percent**
  at creation; after that, the stored price is what you edit.
- Items are never auto-hidden or deleted — a zero-stock item stays
  findable as history ("what did we pay last time"). Retire one by
  deactivating it; **write off** spoiled stock; **merge** accidental
  duplicates.
- A one-off material typed freeform on a job gets its own `LOT-` item
  behind the scenes once it's costed and purchased, so even one-time
  buys are tracked stock — and next year's search can find and reuse
  the lot.

Need to buy? Raise a **Purchase Order** under Purchasing — PO lines
attributed to a job create that job's materials automatically — email
it to the vendor as a PDF, receive it to bump stock, then record the
vendor's **Bill** against it and log payments on the bill.

## Getting paid

From a job that's work-complete (or anywhere along the way — deposits
and progress billing are fine), open an invoice and build it exactly the
way you built the estimate: its Reconcile view offers the job's billable
atoms — completed tasks at their actual quantities, consumed materials,
fees, loose expenses — and each atom can only ever be claimed by one
invoice, so double-billing is structurally impossible. Send it (PDF
email again), and it's pushed to QuickBooks Online; Minibini polls QBO
and flips the
invoice to partly-paid/paid as payments land. When all invoices are
resolved and all deliverables picked up, the job closes itself:
**completed**.

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

Everyone has a **Profile** page (click your name at the bottom of the
sidebar) with account info and a password change. The **FULL / LITE**
toggle in the sidebar switches view modes — lite pares pages down to
the essentials. Your personal **work week** — if it differs from the
shop's — is set on Home → Time, and the schedule forecasts your queue
inside those hours. Admins manage accounts, permissions, and other
people's schedules on the **Users** page.

## A few more things worth knowing

- **Everything is logged.** Jobs, estimates, and invoices keep a full
  history — status changes, edits, and freeform notes anyone can add.
  Look for the History panel on a record's page.
- **Email is a workspace, not just an inbox.** The Email page shows the
  shop's mailbox; from a message you can create a job (with the contact
  and business created along the way), or link it to an existing job,
  PO, or bill. Documents Minibini sends are recorded too and show up on
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
**jobs** (quoting, contacts, job admin), **financials** (invoices, POs,
bills), **time** (editing others' time), and **config** (settings,
templates, users). A job's **project manager** gets job-level powers on
that one job without the global permission.

That's the loop: quote it, win it, work it, buy for it, bill it — one
job, one set of atoms, start to finish.

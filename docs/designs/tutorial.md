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
   pick single services from the catalog, or apply a **work template** —
   a saved bundle of tasks and materials for work you do repeatedly.
   Give each task an estimated quantity and an estimated worker time
   (the schedule uses the latter).
3. **Build the estimate.** Start an estimate and pull the job's atoms
   onto customer-facing line items (the estimate's **Reconcile** view
   shows the unclaimed atoms on one side and the line items on the
   other) — one line per atom, or several atoms bundled into one line
   the customer will understand. You can also type hand lines and
   percentage adjustments (rush fee, discount) directly.
4. **Send it.** Sending emails the customer a PDF and moves the job to
   **submitted**. Estimates expire automatically after a configurable
   number of days. If the customer wants changes, revise the estimate —
   the old version is kept and marked superseded, and the customer sees
   one estimate number throughout.
5. **Acceptance.** When the estimate is accepted the job becomes
   **approved**: hand-written lines crystallize into real Fee and
   Material atoms, and stock is earmarked for the job.

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

## Materials and purchasing

The **Catalog** is the shop's item list — every physical thing, with
cost, sell price, and quantity on hand. Putting a catalog material on a
job **earmarks** stock (visible as "available" vs. "on hand"); starting
the task consumes it. Need to buy? Raise a **Purchase Order** under
Purchasing — PO lines attributed to a job create that job's materials
automatically — email it to the vendor as a PDF, receive it to bump
stock, then record the vendor's **Bill** against it.

## Getting paid

From a job that's work-complete (or anywhere along the way — deposits
and progress billing are fine), open an invoice and build it exactly the
way you built the estimate: its Reconcile view offers the job's billable
atoms — completed tasks at their actual quantities, consumed materials,
fees, loose expenses — and each atom can only ever be claimed by one
invoice, so double-billing is structurally impossible. Send it (PDF email
again),
and it's pushed to QuickBooks Online; Minibini polls QBO and flips the
invoice to partly-paid/paid as payments land. When all invoices are
resolved and all deliverables picked up, the job closes itself:
**completed**.

## Who can do what

Everyone logged in can see nearly everything, work tasks, and track
their own time and expenses. Four permission atoms gate the rest:
**jobs** (quoting, contacts, job admin), **financials** (invoices, POs,
bills), **time** (editing others' time), and **config** (settings,
templates, users). A job's **project manager** gets job-level powers on
that one job without the global permission.

That's the loop: quote it, win it, work it, buy for it, bill it — one
job, one set of atoms, start to finish.

# Activity Page — Design

**Date:** 2026-06-16
**Branch:** `feature/activity`
**Status:** Design agreed; ready for implementation planning.

## Goal

Expand the existing `/activity` page (currently a 2-day rolling Blep log) into a
single-glance dashboard of "what's happening right now and what changed
recently." It answers two questions at once:

1. **Who is here right now,** and what each person is actively working on.
2. **Which documents changed recently** — the status transitions worth noticing
   across estimates/jobs, purchase orders, and invoices.

Everything on the page is governed by one configurable look-back window.

## The "recent" window

A single new Configuration key controls the whole page:

- **Key:** `activity_recent_days`
- **Type:** integer ≥ 1
- **Default:** `5` (clamped/defaulted when the key is missing)
- The cutoff is computed server-side: `cutoff = now() - timedelta(days=N)`.

This is a **look-back** window and is deliberately distinct from
`schedule_horizon_days`, which is a **forward** forecast window. They are
different rhythms and must not be yoked to one number. The config UI for the two
nonetheless sits side by side (see Config UI below).

## Page layout

Four regions in fixed positions, so the eye always knows where to look. Light
CSS differentiation (borders/tints) to start — to be tuned live once on screen.
Sections render an empty-state line rather than vanishing, so the layout stays
stable.

```
┌───────────────────────────────────────────────────────────┐
│  ON SHIFT   [card] [card] [card] …  (wraps as window narrows)│
├───────────────────────────────────────────────────────────┤
│  JOBS & ESTIMATES        │  PURCHASE ORDERS                 │
│  (transition rows)       │  (transition rows)               │
├──────────────────────────┴───────────────────────────────── │
│  INVOICES                                                    │
│  (transition rows)                                           │
├───────────────────────────────────────────────────────────┤
│  RECENTLY COMPLETED WORK   (BlepLogTable, closed bleps only) │
└───────────────────────────────────────────────────────────┘
```

(Exact 2D arrangement of the blobs is cosmetic and will be tuned in-browser; the
contract is "fixed location per section, expands/contracts with the page.")

### On-shift cards (top)

One card per person currently clocked in — driven by open `Shift`
(`end_time IS NULL`). Each card shows:

- Person's name
- "since &lt;clock-in time&gt;" (the open shift's `start_time`)
- Their **current Blep**, if any (open Blep, `end_time IS NULL`):
  - the **task** being worked (link → task detail)
  - the task's **job** (link → job detail)
- If clocked in with no open Blep: a quiet **"idle"** marker instead.

This is the only place open Bleps appear. The completed-work list below never
shows open Bleps.

### Transition sections (event feeds)

Each is a list of **status-change events that occurred within the look-back
window**, newest-first. These are events (a moment something happened), not
"things currently in state X." Each row links to the underlying document.

**Jobs & Estimates** — job-centric, two event kinds:

| Event | Source | Row reads |
|---|---|---|
| Estimate sent | `Estimate.sent_date >= cutoff` | "JOB-… — estimate sent · &lt;date&gt;" |
| Job approved | `Job.start_date >= cutoff` | "JOB-… — approved · &lt;date&gt;" |

- An estimate's acceptance triggers the job's approval; `Job.start_date` is set
  on approval, so it is the clean timestamp for "approved." (The estimate's
  `closed_date` is an equivalent fallback but `start_date` lives right on the
  Job.)
- **No rejections** are surfaced in this section.
- Same-job events are **separate rows** (a job whose estimate was sent and which
  was approved in-window appears twice).
- Each estimate version with a `sent_date` in-window produces its own "sent" row.

**Purchase Orders** — two event kinds:

| Event | Source |
|---|---|
| Sent | `PurchaseOrder.issued_date >= cutoff` |
| Received | `PurchaseOrder.received_date >= cutoff` |

**Invoices** — two event kinds:

| Event | Source |
|---|---|
| Sent | `Invoice.sent_date >= cutoff` |
| Paid | `Invoice.closed_date >= cutoff` AND status PAID |

**Full completion only.** "Received" = received in full; "Paid" = paid in full.
Partial states (PO partly received, invoice partly paid) are **out of scope for
v1** — their timestamps aren't stamped on the model, and surfacing them would
require leaning on the history log. Add later if missed.

**No Bills.** Bills were considered and dropped — "due" is a date passing rather
than an action someone took, which didn't fit the event-feed model.

### Recently completed work (bottom)

The existing `BlepLogTable`, fed **only closed Bleps** with `end_time >= cutoff`.
Open Bleps have moved up into the on-shift cards.

### Granularity

Day-granularity for displayed dates to start; revisit if finer is wanted.

## Backend

### New app: `apps/activity`

Model-less service app, mirroring `apps/schedule`. Contains `ActivityService`,
which computes the whole payload from existing models + the config window.

### Endpoint: `GET /api/activity/`

- **Permission:** `IsAuthenticated` (read-only dashboard; PO/invoice reads are
  already open to any authenticated user).
- One fetch returns the whole page. The cutoff lives in exactly one place
  (the service), computed from `activity_recent_days`.

### Payload shape

```jsonc
{
  "recent_days": 5,
  "on_shift": [
    {
      "user_id": 7,
      "user_name": "Jane Doe",
      "shift_start": "2026-06-16T08:01:00Z",
      "current_blep": {              // null if clocked in but idle
        "task_id": 42,
        "task_name": "Cut panels",
        "job_id": 13,
        "job_number": "JOB-2026-0007",
        "job_name": "Acme cabinets",
        "blep_start": "2026-06-16T08:05:00Z"
      }
    }
  ],
  "completed_bleps": [ /* closed Bleps, end_time >= cutoff, newest-first */ ],
  "job_events": [
    { "kind": "estimate_sent", "job_id": 13, "job_number": "JOB-…",
      "job_name": "…", "estimate_id": 88, "date": "2026-06-14" },
    { "kind": "job_approved", "job_id": 13, "job_number": "JOB-…",
      "job_name": "…", "date": "2026-06-15" }
  ],
  "po_events": [
    { "kind": "sent",     "po_id": 5, "po_number": "PO-…", "date": "…" },
    { "kind": "received", "po_id": 5, "po_number": "PO-…", "date": "…" }
  ],
  "invoice_events": [
    { "kind": "sent", "invoice_id": 9, "invoice_number": "INV-…", "date": "…" },
    { "kind": "paid", "invoice_id": 9, "invoice_number": "INV-…", "date": "…" }
  ]
}
```

Each event list is newest-first by its event date.

### Queries (summary)

- `on_shift`: `Shift.objects.filter(end_time__isnull=True)`; for each, attach the
  user's open `Blep` (`end_time__isnull=True`) if present.
- `completed_bleps`: closed Bleps with `end_time >= cutoff`, newest-first.
- `estimate_sent`: `Estimate.sent_date >= cutoff`.
- `job_approved`: `Job.start_date >= cutoff`.
- `po sent/received`: `issued_date >= cutoff` / `received_date >= cutoff`.
- `invoice sent/paid`: `sent_date >= cutoff` / (`closed_date >= cutoff` AND
  status PAID).

## Config UI

In `frontend/src/components/settings/ScheduleSettings.svelte`, add a
"Recent activity (days)" number input directly beside the existing
"Default horizon (days)" control. Reuses the existing load/save plumbing
(`GET`/`PATCH /api/settings/`).

Backend validation lives in `apps/api/templates_config/views.py` (the settings
PATCH handler): `activity_recent_days` must parse as an integer ≥ 1; reject
blanks/garbage with a field error, matching the `schedule_horizon_days` pattern.

## Testing (TDD — write first)

**Service (`apps/activity`):**
- Open shift surfaces with an open Blep (task/job populated) and without (idle).
- Closed Blep just inside vs. just outside the cutoff.
- Estimate sent in-window appears; one outside doesn't.
- Job approved in-window (via `start_date`).
- PO sent/received; invoice sent/paid (full only; partly-paid invoice excluded).
- Cutoff honors the config value; defaults to 5 when the key is absent.

**API (`/api/activity/`):**
- 200 shape for an authenticated user; 403 for anonymous.
- Payload section keys/fields match the frontend contract.

**Settings validation:**
- `activity_recent_days` accepts a valid int; rejects non-int and < 1.

**Frontend (Vitest):**
- Card renders name + clock-in + linked task/job.
- Idle card (open shift, no open Blep).
- Each transition section renders rows and its empty-state line.

## Out of scope (v1)

- Bills.
- Rejections in the Jobs & Estimates section.
- Partial states (PO partly received, invoice partly paid).
- Sub-minute / finer-than-day date granularity.
- A mixed chronological feed (sections stay separate and fixed).

# Job History Page — Design (v1)

**Date:** 2026-06-08
**Branch:** `feature/history-display`
**Status:** Approved for implementation (expected to take 2–3 revision passes against a working build)

## 1. Purpose

Build a dedicated **Job History** page: a deep-dive, top-to-bottom **narrative worklog** of a single job's life, for the shop owner to analyze a completed/in-flight job and shape future business decisions (quoting, sourcing, scheduling). It doubles as an audit/debug tool ("who changed this status, when"), but the *primary* design target is readability as a narrative — not a raw audit dump.

This is **not** overview material. It is a separate page reached from the Job, not a panel or accordion section on the Job detail.

### Explicitly iterative

The value of this feature is "does it read well to the owner," which is not knowable from a spec. v1 is deliberately a **lean-but-real cut** meant to be looked at and revised. The granularity questions (curated action phrasing, grouping, filtering) are the **revision surface**, called out in §6 — not upfront guesses.

## 2. Current state (summary)

Full mechanism is documented in `docs/designs/architecture-and-conventions.md` §7. In brief:

- `@history(exclude=[...])` (`apps/core/history.py`) wires signals to capture field-level changes into one `HistoryEntry` table (`db_table='history'`), linked generically by `object_type` (lowercased class name) + `object_id`.
- Three entry types: **audit** (auto field diffs), **action** (curated system lines written explicitly by signals/services), **note** (user free text).
- `GET /api/jobs/{id}/history/` already aggregates Job + Estimate + EstWorksheet + Invoice into one paginated feed.
- `HistoryPanel.svelte` renders the timeline + add-note box; still live on Contact, Business, and PO detail pages. It was removed from the Job overview (the slot now holds `EmailPanel.svelte`).

**Currently decorated (12):** `Job`, `BlepChangeRequest`, `Estimate`, `ChangeOrder`, `EstWorksheet`, `Contact`, `Business`, `Invoice`, `PurchaseOrder`, `Bill`, `Shift`, `ShiftChangeRequest`.
(Doc §7.2 currently omits `ChangeOrder` — fix when updating docs.)

## 3. Decisions & rationale

**Primary purpose = narrative worklog** (owner analysis), audit/debug secondary. → Lean toward curated, human-readable lines; keep raw machine-exhaust off the feed where it adds no story.

**Bleps are NOT tracked and NOT collated.** A Blep's churning fields are clock timestamps (noise) and its entire value collapses to a summary (hours logged) — it is container-summary data, "almost history in itself," like a line item. Decorating it would flood the feed with punch boundaries.

**Line items are NOT tracked at field level.** The sent artifact is preserved by explicit container versioning; the container's lifecycle (created / sent / accepted / rejected / revised) is the narrative beat. Per-line wording churn ("set of three parts" → "three parts to a set") is noise.

**EstWorksheet tracking is dropped.** Worksheets are internal planning scratch with little narrative value. Removing the decorator stops new entries; old `estworksheet` rows remain harmlessly and simply fall out of the Job collation. No data migration.

**Material is Task-style, not Blep-style.** What makes a Blep blep-style is that its churn fields are noise and its value is one summary number. Material is the inverse: its churn fields (`quantity`, `unit_cost`) *are* the value the owner cares about, and "under-ordered plywood, reordered 8 more at higher unit cost" is exactly a per-material story that informs the next quote. So it gets field audit. The one blep-like risk — a burst of "created" rows on estimate carry-over — is a creation burst, not ongoing churn, and Job-page grouping absorbs it.

**Granularity starting point = raw field audit for all newly-tracked models.** Cheapest path to something real. The existing curated **action** entries (estimate sent/accepted, invoice lifecycle, job status) already give the narrative a spine; the new operational objects ride in as raw diffs. After looking at v1, the owner points at the streams that read like machine exhaust and we promote *only those* to curated action entries — instead of guessing now.

## 4. v1 Scope

### 4.1 Decorator changes (data layer)

| Model | File | Change | `exclude` |
|---|---|---|---|
| `Task` | `apps/jobs/models.py` | **Add** `@history` | `['task_id']` (+ auto-managed timestamps if any surface as noise) |
| `Material` | `apps/inventory/models.py` | **Add** `@history` | `['material_id']` |
| `Deliverable` | `apps/deliverables/models.py` | **Add** `@history` | `['id', 'created_at', 'updated_at']` |
| `Shipment` | `apps/deliverables/models.py` | **Add** `@history` | `['id', 'created_at', 'updated_at']` |
| `EstWorksheet` | `apps/estimates/models.py` | **Remove** `@history` | — |

- `updated_at` (`auto_now=True`) is excluded so every save doesn't log a timestamp diff. `created_at` excluded as redundant with the `_created` marker.
- **Blep:** left untracked (no change).
- **ShipmentItem:** held out of v1. Track the Shipment, not its per-line quantities. Revisit if "shipped 3 of 5" reads as missing (§6).
- No curated action emitters are added in v1; newly-tracked models contribute raw audit + `_created` only.

### 4.2 Collation (endpoint)

Extend `GET /api/jobs/{id}/history/` (`apps/api/jobs/views.py`) to aggregate these object types, all reachable from the job in ≤2 hops:

| Object | `object_type` | Reachability |
|---|---|---|
| Job | `job` | self |
| Estimate | `estimate` | `Estimate.objects.filter(job=job)` |
| ChangeOrder | `changeorder` | `ChangeOrder.objects.filter(job=job)` — **new**, not collated today |
| Invoice | `invoice` | `Invoice.objects.filter(job=job)` |
| Task | `task` | `Task.objects.filter(job=job)` |
| Deliverable | `deliverable` | `Deliverable.objects.filter(job=job)` |
| Shipment | `shipment` | `Shipment.objects.filter(job=job)` |
| Material | `material` | `Material.objects.filter(job=job)` |

- **Drop** the `estworksheet` branch.
- The change is widening the existing `Q()` OR-filter and gathering the related ids; pagination (newest-first) is unchanged.

**Source labels (v1 requirement).** Each entry must carry a human **source label** so the feed has an anchor — without it the page is a soup of "audit / job / task". The endpoint annotates each serialized entry with:

- `source_label` — e.g. `"Job JOB-2025-0001"`, `"Estimate EST-2025-0001"`, `"Change Order CO-…"`, `"Invoice INV-…"`, `"Task: Fabrication"`, `"Deliverable: …"`, `"Shipment #2"`, `"Material: Plywood"`.
- `source_link` (optional, best-effort) — a frontend route target for the source object where one exists.

Implementation note: `HistoryEntry` has no FK to the source (generic `object_type`+`object_id`), so labels are resolved by batch-loading the referenced objects per type and mapping `(object_type, object_id) → label`. Keep this in the viewset/serializer-context layer, not N+1 per row.

### 4.3 The page (frontend)

- **New route:** `#/jobs/:id/history` (full page).
- **Entry point:** a "History" link in the job header (`JobHeader.svelte`). Links navigate (`<a>`/`use:link`) per UI conventions.
- **Rendering:** seeded from `HistoryPanel.svelte`'s entry-rendering logic, but as its own page component with full-width real estate. v1 = a clean reverse-chron narrative list showing, per entry: source label, timestamp, user, and the humanized change/action/note text. Note-adding (`POST /api/jobs/{id}/notes/`) is included.
- v1 deliberately ships a **flat** list. Grouping, type filters, and lite/full behavior are revision-1 territory (§6).
- New component(s) get Vitest coverage per `docs/designs/frontend-testing.md`.

### 4.4 Docs

Update `docs/designs/architecture-and-conventions.md`:
- §7.2 tracked-model list: add `Task`, `Material`, `Deliverable`, `Shipment`; remove `EstWorksheet`; add the missing `ChangeOrder`.
- §7.4 endpoints: new Job collation set; note the new `#/jobs/:id/history` route and `source_label`/`source_link` fields.
- §7.5: note the dedicated Job History page in addition to the panel.

## 5. Testing approach (TDD)

Per CLAUDE.md, write failing tests first, in `/tests/` (backend) and `frontend/tests/` (SPA).

- **Decorator additions:** for each newly-tracked model, a test that a create logs a `_created` audit entry and a field edit logs the expected diff; that `EstWorksheet` no longer logs. (Tests use the separate test DB — never the dev DB.)
- **Collation endpoint:** seed a job with an estimate, change order, invoice, task, deliverable, shipment, material; assert the feed includes entries from all eight types and excludes worksheet entries; assert each entry carries a correct `source_label`; assert pagination/ordering.
- **Frontend:** component test for the page rendering a mixed feed with source labels and for the add-note path.
- **Never run `manage.py test` from parallel agents** (shared MySQL test DB).

## 6. Deferred / revision surface (expected 2–3 passes)

These are intentionally **not** decided upfront; they are what we tune against the working build:

1. **Curated action entries** — promote noisy raw-audit streams (likely Material and/or Task transitions: consumed, restocked, status→complete) to human-phrased action lines written into the relevant service. Decide per-stream after seeing v1.
2. **Grouping** — by day, by source object, or by job phase, for top-to-bottom readability.
3. **Filtering** — by entry type and/or source object; lite vs full mode behavior on this page.
4. **ShipmentItem** — per-line shipped quantities ("3 of 5") if Shipment-level reads as too coarse.
5. **Volume/paging** — larger pages or infinite scroll for long-lived jobs.
6. **`source_link` coverage** — which source objects get clickable deep links.

## 7. Out of scope

- History pages for objects other than Job (Expenses, Config, etc. deferred by the owner).
- Decorating `Blep`, line items, `ShipmentItem`, `PlanTask`, `PlanMaterial`, `RateScheme`.
- Any change to the existing Contact/Business/PO history panels.
- Backfilling history for pre-existing records.

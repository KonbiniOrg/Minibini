# Estimate ↔ Worksheet Linking & Revision — Design Exploration

**Status:** Open design discussion (started 2026-06-02). Not yet a build plan. Decisions are being made piece by piece; this doc is the running record.

**Owner context:** Rachel (service@nealscnc.com), a job-shop operator. Use cases below are described in her own workflow terms.

**Why this exists / scope boundary:** The `feature/direct-create-line-items` branch added the ability to create an estimate (or invoice) directly from a job, by hand. That exposed a seam: an estimate and a worksheet created independently on the same job are **not linked**, so the estimate's "Show Worksheet" affordance never appears, and the worksheet's "generate estimate" path would mint a *second* estimate. Fixing that well means rethinking how estimates and worksheets link, supersede, and revise together — which is too big to tack onto the current feature. **This redesign is explicitly out of scope for `feature/direct-create-line-items`; that branch stays "direct create + catalog line items" only.**

---

## 1. The problem in one breath

Estimates and worksheets are two parallel version chains joined by a single loose foreign key (`EstWorksheet.estimate`). The join is created only at the original "generate estimate from worksheet" moment and is **severed by a revision on either side**. With direct estimate creation now possible, you can also start with an orphan estimate that can never get a worksheet attached. There's "too much stuff happening" in the supersession machinery, and the status/linkage vocabulary can't cleanly express the workflow below where you want to keep an estimate but mark it clearly "not the one to use" while you rework the worksheet.

---

## 2. How it works today (verified 2026-06-02)

Two independent version chains plus a status coupling.

**Estimate chain** — `EstimateService.revise_estimate(pk)` (`apps/estimates/services.py:124`):
- Requires the parent to be non-draft (drafts edit in place).
- Creates a new `Estimate`: same `estimate_number`, `version+1`, `status=draft`, `parent=old`; copies line items field-by-field (no source/atom rows).
- Flips the parent to `superseded`.
- An estimate "tree" = rows sharing an `estimate_number`, linked by `parent`, with one non-superseded head. `unique_together = ['estimate_number', 'version']`.

**Worksheet chain** — `EstWorksheet.create_new_version()` (`apps/estimates/models.py`, via `EstimateService.revise_worksheet`):
- Marks the current worksheet `superseded`.
- Creates a new worksheet: `version+1`, `parent=self`, **`estimate=None`** ("new version starts without an estimate").
- Deep-copies all `PlanTask`s and their `PlanMaterial`s.
- A worksheet "tree" is its own parallel `parent`-linked chain.

**The link + status coupling:**
- The only structural connection is `EstWorksheet.estimate` (FK, nullable, `on_delete=SET_NULL`, `related_name='worksheets'`, `apps/estimates/models.py:325`).
- The estimate detail page's "Show Worksheet" link is driven by `EstimateSerializer.get_worksheet` = `obj.worksheets.first()` (`apps/api/estimates/serializers.py:69`). No link → no button. Sharing a `job` is **not** sufficient.
- An estimate **drives its linked worksheet's status**: on any estimate status change, `Estimate._maybe_update_worksheet_statuses` maps it via `_get_worksheet_status` and fires the `estimate_status_changed_for_worksheet` signal, whose receiver (`apps/estimates/signals.py:update_estworksheet_status`) does `EstWorksheet.objects.filter(estimate=this).update(status=…)`. Mapping:
  - estimate **draft → worksheet draft**
  - estimate **open / accepted / rejected → worksheet final**
  - estimate **superseded → worksheet superseded**
- `EstWorksheet.save()` also seeds a new worksheet's status from its estimate's status at creation time.

**Generate-estimate-from-worksheet** — `EstimateWizardService.open_for_worksheet(worksheet)` (`apps/estimates/services.py:~711`):
- If `worksheet.estimate` is a draft → returns it.
- If `worksheet.estimate` is set but non-draft → raises "inconsistent state."
- If `worksheet.estimate` is **null → unconditionally creates a NEW estimate** and links it. **It does not look at whether the job already has a draft estimate elsewhere** — this is the duplicate-minting hazard under one-tree. Reached from the worksheet detail page via "Send all atoms to estimate" and "Open estimate".

**Net behavior on a revision (the tangle):**
- **Revise the estimate** → parent becomes `superseded` → the signal marks its linked worksheet `superseded` too. The new draft estimate is created with **no worksheet**. So the worksheet doesn't "follow" — it's *killed* as a side effect, and the new estimate starts bare.
- **Revise the worksheet** → old worksheet `superseded`, new worksheet `estimate=None`. The estimate it was attached to now has no live worksheet.
- Re-joining after a revision tends to spawn duplicates because `open_for_worksheet` mints rather than adopts.

---

## 3. The real workflows this has to serve (operator's words)

When making an estimate for a customer:

1. **The common path.** Build a worksheet → estimate from it → send the estimate. Customer says "OK, close but not quite, do something slightly different." **Very often** the change is small enough to **just revise the estimate** — no new worksheet needed.

2. **The occasional path.** Sometimes the requested change is different enough that a **new worksheet is genuinely useful**. In that case the operator wants to:
   - Mark the existing estimate clearly as **"not the one to use,"** and
   - Revise the **worksheet** first (rework the plan), then produce the updated estimate from it.
   - It's unclear how to represent this with the current status options + linkage.

3. **Open musing on history.** Maybe there's just **one worksheet ever** (a single mutable worksheet per job) and we accept losing the worksheet version history — which could in principle be reconstructed from the `HistoryEntry` audit trail. Undecided; raised as a possible simplification.

---

## 4. The decided model

The shape is settled. Estimate and worksheet are **decoupled** — no direct relationship — and find each other only through the shared **Job**. The worksheet has no lifecycle of its own; everything about it is derived from the job's estimate.

**Structure:**
- **Drop `EstWorksheet.estimate`** (the FK) entirely. A worksheet relates to a job; an estimate relates to a job; that's the only structural tie. ("Does this estimate have a worksheet?" becomes "does the job have a worksheet?"; "is this line worksheet-backed?" stays answerable via its `EstimateLineItemSource`.)
- **One worksheet per job, mutable. Drop the worksheet `parent`/`version` chain** and `create_new_version`. No worksheet history as a first-class thing — the `HistoryEntry` audit trail covers "what did the plan look like before," and no operator scenario needs to pull up a prior worksheet *version* as an object.
- **Drop `EstWorksheet.status` entirely** — no `draft`/`final`/`superseded` on the worksheet.
- **Delete the `estimate_status_changed_for_worksheet` signal and `_get_worksheet_status`** — there is no worksheet status to drive.
- **One estimate tree per job** (unlike invoices, which allow many). Estimates keep their `parent`/`version` chain — sent estimates are customer-facing documents with real external history.

**Worksheet editability (derived, not stored):** the worksheet is editable **iff the job's live estimate is a draft, or the job has no estimate yet.** Sent / accepted / rejected / expired / superseded → frozen. **Freeze on send.** Revising any non-draft estimate produces a fresh draft, so **revise is always the unlock** — freezing is never a dead end. Rationale: no real-world case requires editing the plan while a quote is out with the customer (speculative prep belongs on the Job post-accept; cost drift or errors are a re-quote → revise, or an offline phone call), and freezing guarantees the worksheet that backs a sent quote stays stable, so carry-over on accept matches what was sent.

**Revision MOVES its sources (does not copy).** `revise_estimate` reassigns each `EstimateLineItemSource` from the old line item to the corresponding copied line item on the revision, rather than duplicating the rows. This is simpler (one update per source, no extra rows) and — more importantly — keeps each atom claimed by exactly **one** estimate. An `EstimateLineItemSource` is also the atom *claim* the wizard reads to show "claimed by another estimate"; copying would make the superseded estimate and the revision both claim the same atoms (forcing the claim query to start excluding superseded estimates), whereas moving leaves one live claim and lets the superseded estimate keep its frozen display values without any atom links. A source is lost **only** when the user deletes that line in the revision.

**Carry-over stays worksheet-driven.** On accept, `carry_over_for_estimate` finds **the job's single worksheet** (by `job`, not the old FK) and carries its PlanTasks/PlanMaterials onto the Job. It is explicitly a *starting point*: the **`accepted` job state is the prep buffer** — it exists so the shop can reconcile the prepped work before flipping to `in_progress`. The estimate's dollars are the customer agreement; the worksheet is the work plan; they need not be identical. (Whether a *worksheet-less* accepted estimate also materializes its own catalog/template line items — the existing `carry_over.py` "Phase B" — is a decision under review; see §5.)

**Estimate numbering derives from the Job.** Because one job has exactly one estimate tree, the estimate's identity *is* the job's. The estimate number is taken from the **job number**, with the **revision** (the existing `version`) disambiguating — the customer tracks **one** number ("estimate on JOB-2025-0042, rev 2") instead of an unrelated `EST-…` number plus a separate version. This lets us **delete the `estimate_number_sequence` / `estimate_counter` Configuration keys** and the independent estimate counter. Open detail: exact display format (`JOB-2025-0042 rev 2` vs `JOB-2025-0042-r2`) and migration of existing estimates that already carry standalone numbers — see §5.

**Converge, don't duplicate.** Every create/link path lands on the job's single estimate tree + single worksheet, adopting an existing piece rather than minting a second. In particular, `open_for_worksheet` (the worksheet's "generate estimate"/"Open estimate") must **adopt the job's live draft estimate** when one exists, and only create when none does — never mint a second estimate.

**"Not the one to use" = revise.** The big-change workflow (§3.2) needs no new status: revising the estimate supersedes the old version (that's "not the one") and produces a draft, which unlocks the worksheet so the operator reworks the plan and re-pulls. Resolved.

---

## 5. Open questions (resume here)

1. **Button gating on the job overview.** Under the Create/View model from `feature/direct-create-line-items`: when is **Create Worksheet** shown vs. hidden (hide once the job has a worksheet?), and how do Create Estimate / Create Worksheet / the worksheet's "generate estimate" coexist so the operator is never offered an action that creates a duplicate or an orphan? Also: does the estimate page's **"Show Worksheet"** simply key off "job has a worksheet," and what does it do when the worksheet is frozen (view-only)?

2. **Migration.** Existing data carries `EstWorksheet.estimate`, worksheet `status`, and worksheet `version`/`parent` chains. Need a migration story: drop the columns; collapse any existing multi-version worksheet chains to a single worksheet per job (which version wins?); and confirm nothing else reads the dropped fields (`mark_open`'s worksheet-finalize step, `open_for_worksheet`, the serializer's `get_worksheet`, the signal, tests).

3. **Does the worksheet need *any* persisted flag?** Editability is derived, but confirm there's no case that needs a stored bit (e.g. an explicitly "archived" worksheet on a dead job). Default assumption: no — fully derived.

4. **Interplay with change orders.** Change orders are their own flow on an approved job; confirm this redesign doesn't disturb them (they reference `Estimate`, not the worksheet FK being dropped — verify).

5. **Keep or drop carry-over "Phase B" (worksheet-less estimates).** Existing `carry_over.py` Phase B materializes a Job Task/Material from each accepted line item that has a `source_template` or `price_list_item` and no worksheet source. This is what lets a hand-built, worksheet-less estimate (the direct-create path) seed the Job on accept. **Keep it** (worksheet-less accepted estimates still produce starter atoms from their catalog/template lines) or **drop it** (carry-over is worksheet-only; a worksheet-less estimate lands an empty job and the shop builds tasks by hand during the `accepted` prep state)? Mild lean: keep — it's already built and avoids a totally empty job for hand-built estimates.

6. **Estimate-numbering format + migration.** Decided that the estimate number derives from the job number + revision (§4). Open: the exact customer-facing format (`JOB-2025-0042 rev 2` vs `JOB-2025-0042-r2` vs reusing the job number verbatim with `version` shown separately on the PDF/email); how `unique_together` changes (effectively `(job, version)`); and the migration for existing estimates that already carry standalone `EST-…` numbers (leave legacy numbers as-is on old rows, or backfill). Removing the `estimate_number_sequence`/`estimate_counter` Configuration keys is part of this.

---

## 6. Relationship to other work / notes

- Depends on / follows `feature/direct-create-line-items` (direct estimate & invoice creation + catalog line items), which introduced the orphan-pair seam. That branch should ship as-is; this redesign builds on it.
- Invoices intentionally do **not** get one-tree (multiple invoices per job is correct). This doc is estimate/worksheet-only.
- Related background: `[[project_single_live_estimate_invariant]]` (the deferred "one live estimate" concern) — this redesign effectively decides to enforce one estimate tree per job at the UI/service layer.
- When decisions in §5 are settled, this graduates into an implementation plan (or a set of them) under `docs/plans/`, and the durable behavior gets folded into `docs/designs/estimates-and-prices.md` and `docs/designs/jobs-tasks-and-worksheets.md`.

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

## 4. Decisions locked so far

- **Simplify.** There is "too much stuff happening" in the current supersession machinery; the redesign should reduce moving parts, not add them.
- **One worksheet tree and one estimate tree per job** (unlike invoices, where multiple are allowed). This is the organizing constraint.
- **Converge, don't duplicate.** Every create/link path should land on a *single linked pair* (the job's one live estimate + its one worksheet), adopting an existing half rather than minting a second. Concretely this means: Create Estimate adopts an orphan worksheet; Create Worksheet adopts the orphan draft estimate; the worksheet's generate-estimate adopts the job's existing draft estimate instead of creating a new one. (Agreed in principle; this is the "auto-link on create" the operator green-lit. It now lives in this redesign's scope, not the current branch.)
- **A worksheet does NOT automatically follow to a new estimate revision.** Revising an estimate should not silently drag the worksheet onto the new version. (How exactly the worksheet *should* behave on estimate revision is still open — see §5.)

---

## 5. Open questions (resume here, piece by piece)

1. **On estimate revision, what happens to the worksheet?** Three honest options, none chosen yet:
   - leave the worksheet **alive but unlinked** (a free worksheet you can re-attach),
   - **supersede** it (today's behavior — worksheet dies with the estimate version),
   - **auto-revise** the worksheet in lockstep (new worksheet draft, linked to the new estimate draft).
   The operator: *"I don't know."* Leaning toward: small changes → revise the estimate alone (worksheet untouched/irrelevant); big changes → revise the *worksheet* first and mark the old estimate "not the one."

2. **How do we represent "this estimate is not the one to use" without it being `superseded`-by-a-newer-version?** The current `superseded` status is produced *by* creating a newer version in the same chain. The workflow in §3.2 wants to retire an estimate while reworking the worksheet — possibly *before* the replacement estimate exists. Do we need a new status / an explicit "shelve" action, or does revising-the-worksheet-then-the-estimate produce the right states naturally?

3. **Do we keep worksheet version history at all?** Option: collapse to a **single mutable worksheet per job**, drop the worksheet `parent`/`version` chain, and rely on `HistoryEntry` for "what did the plan look like before." Trade-off: simpler model + simpler linkage vs. losing easy point-in-time worksheet snapshots. (Estimates likely still need their version chain because sent estimates are customer-facing documents.)

4. **`open_for_worksheet` under one-tree.** It must stop minting a second estimate when the job already has a draft. Redefine it to adopt the job's live draft estimate (link the worksheet to it) and only create when none exists.

5. **Button gating on the job overview given one-tree.** With the current branch's Create/View model: when is **Create Worksheet** shown vs. hidden (e.g., hide once a live worksheet exists)? How do Create Estimate / Create Worksheet / "generate estimate from worksheet" coexist so the operator is never offered an action that would create a duplicate or an orphan?

6. **Status coupling simplification.** The estimate→worksheet status-driving signal (`estimate_status_changed_for_worksheet`) is part of "too much stuff." Does a single-mutable-worksheet model (Q3) let us delete it, or does the worksheet still need a status that mirrors its estimate?

---

## 6. Relationship to other work / notes

- Depends on / follows `feature/direct-create-line-items` (direct estimate & invoice creation + catalog line items), which introduced the orphan-pair seam. That branch should ship as-is; this redesign builds on it.
- Invoices intentionally do **not** get one-tree (multiple invoices per job is correct). This doc is estimate/worksheet-only.
- Related background: `[[project_single_live_estimate_invariant]]` (the deferred "one live estimate" concern) — this redesign effectively decides to enforce one estimate tree per job at the UI/service layer.
- When decisions in §5 are settled, this graduates into an implementation plan (or a set of them) under `docs/plans/`, and the durable behavior gets folded into `docs/designs/estimates-and-prices.md` and `docs/designs/jobs-tasks-and-worksheets.md`.

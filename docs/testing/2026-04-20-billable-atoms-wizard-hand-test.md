# Billable Atoms & Wizard — Browser Hand-Test Plan

**Date:** 2026-04-20
**Scope:** Verify the wizard, catalog picker, automatic atom carry-over, Job state machine (`in_progress`), and Job Board reshuffle shipped in Plans A/B/C (design doc: `docs/designs/2026-04-19-billable-atoms-and-estimate-wizard-design.md`).

Hand-test rather than automated — the frontend has no Svelte test framework, and some behaviors (drag-and-click wizard UX, Job Board color) are only meaningfully verified in the browser.

---

## 0. Setup

### Load the seed

```bash
python manage.py loaddata fixtures/large_datasets/nealseed.json
```

**CAVEAT:** If your dev DB already has data you care about, dump it first:

```bash
python manage.py dumpdata --indent=2 > backup.json
```

The seed includes ~2,600 jobs, 117 price list items, 9 task templates, 12 worksheets, 29 draft estimates. Sections below cite specific records to use so you don't get lost.

### Start servers

```bash
# Terminal 1
python manage.py runserver

# Terminal 2
cd frontend && npm run dev
```

### Log in

Open `http://localhost:9000/?autologin` to log in as `dev_user` (superuser, all permissions).

If `?autologin` fails, hand-log at `http://localhost:9000/` with username `dev_user` / password `dev_password`.

---

## 1. Landmarks in the seed data

Pin these in your head or a scratchpad — they're referenced throughout.

| Landmark | Detail |
|---|---|
| **Worksheet 12 (draft)** | On Job **J2026-0341 "Taproom menu board with changeable panels"** (pk 2629). Has 5 plan tasks (SITE VISIT, CAD, CUT, FINISH, Assemble) + 1 plan material (3/4" Apple plywood). Two associated draft estimates: **EST-2026-0012** (pk 2633) and **EST-2026-0013** (pk 2634). This is your main wizard playground. |
| **Worksheet 4 (draft)** | On Job **J2026-0342 "Storage rack system"** (pk 2630). 4 plan tasks (Design, Cut lumber, Assemble racks, Delivery), 0 materials. Use for a simpler second pass. |
| **Task templates (9)** | RESEARCH, CAD, CUT, ASSEMBLE, FINISH, etc. — all priced hourly or per-unit. Use any for catalog picker tests. |
| **PriceListItems (117)** | Code "5 CAD" at $132/hour, "ABS.125" etc. — 117 rows, wide variety. |
| **Approved jobs (16)** | e.g., J2026-0003 Engraved Benches, J2026-0012 Stacking children's desks. These exist BEFORE the new `in_progress` state, so they sit in `approved`. Use them to test "Release to floor" button and confirm they show in the Pipeline tab (not In Progress). |
| **Accounting categories** | Service (SVC), Material (MTL), Product (PRD), Delivery (DLV). |

---

## 2. CatalogPicker component

**Where it appears:** estimate detail page when adding a line item directly.

**Test 2.1 — Unified search**

1. Navigate to `#/estimates/2633/` (EST-2026-0012, draft, on J2026-0341).
2. Scroll to the "Add line item" section. A search box labeled "Search catalogs…" is visible.
3. Click the search box. A dropdown appears listing both task templates (tagged `[task]`) and price list items (tagged `[material]`) interleaved alphabetically. A "Manual" row appears at the bottom.
4. Type `CAD`. Results filter to include CAD task template and any PLI with "CAD" in code or description.
5. Type `steel` (or another material word). Results filter to materials matching.
6. Clear the search. The full list returns.

**Test 2.2 — Picking a task template**

1. In the dropdown, click the `[task] CAD` row.
2. The inline form appears below, pre-filled:
   - Description = "CAD"
   - Units = "hours"
   - Price = "150.00"
   - Accounting category = whatever CAD is assigned (likely Service)
3. Edit the Qty to `2`.
4. Click **Save**.
5. The form closes and the line item appears in the table above. Description, units, price all match.

**Test 2.3 — Picking a price list item**

1. Re-open the picker. Click any `[material]` row (e.g., "7 DELIVERY").
2. Form pre-fills from the PLI: description, units, price, category.
3. Edit qty, click Save, confirm it shows up.

**Test 2.4 — Manual entry**

1. Re-open the picker. Click the "Manual" row at the bottom.
2. The form opens blank.
3. Type a description, qty, units, price, pick a category.
4. Save. Line item appears.

**Expected result:** three line items added to EST-2026-0012. Estimate total reflects them.

---

## 3. Worksheet: Send-all and Open-wizard

**Where it appears:** worksheet detail page, when the worksheet is in draft.

**Test 3.1 — Send all atoms (bulk 1:1)**

1. Navigate to `#/worksheets/12/` (our Worksheet 12 on J2026-0341).
2. Confirm the worksheet displays 5 plan tasks and 1 plan material.
3. Locate the action bar at the top or bottom with two new buttons: **Send all atoms to estimate** and **Open wizard to group atoms**.
4. Click **Send all atoms to estimate**. Confirm dialog: "Send all unclaimed atoms to the estimate as 1:1 line items?" Click OK.
5. Navigation automatically redirects to `#/estimates/2633/` (or whichever draft estimate is linked).
6. Confirm **6 line items** appear (5 tasks + 1 material), each with its own row. Prices match: CAD 3×$150=$450, CUT 14×$22=$308, etc.

**Test 3.2 — Idempotent bulk send**

1. Go back to `#/worksheets/12/`. Click **Send all atoms to estimate** again.
2. Dialog appears; confirm. Navigation happens.
3. Count line items on the estimate — should still be **6**. No duplicates created.

**Test 3.3 — Open wizard path**

1. Delete any line item on the estimate (click Delete on one row in the table).
2. Back to `#/worksheets/12/`. Click **Open wizard to group atoms**.
3. Routes to `#/estimates/2633/wizard`.
4. The wizard page shows:
   - Left column: source pool with all 6 atoms. 5 atoms show as **claimed_by_current** (grayed, checked, disabled, with → line ref). 1 atom (the one you deleted) shows as **available** (checkable).
   - Right column: 5 line item cards, each with a **Sources (1)** list and **Remove** button.

---

## 4. Wizard: grouping atoms

**Continues from Test 3.3.**

**Test 4.1 — Create a new grouped line item**

1. The deleted atom should be available in the source pool. Tick its checkbox.
2. Click **Create new line item from selected** in the sticky footer.
3. A new line item card appears on the right with that atom as its sole source.
4. The source pool atom moves from `available` → `claimed_by_current`.

**Test 4.2 — Add to existing line item**

1. Find an `available` atom (if none, delete one from the estimate first to free it up).
2. Tick it.
3. In the right column, click **Add selected atoms here** on one of the existing line item cards.
4. That card's Sources count goes from 1 → 2.
5. The card's displayed price recomputes (sum of both atoms' compute_amount).
6. The source pool atom shows as claimed_by_current and references the target line.

**Test 4.3 — Remove a source**

1. On a line item card with multiple sources, click **Remove** next to one source.
2. The source disappears from the card.
3. Card price recomputes to the remaining sum.
4. Source pool atom returns to `available`.

**Test 4.4 — Remove last source (line item disappears)**

1. On a line item with only 1 source, click **Remove**.
2. The card disappears entirely.
3. The released atom shows as `available` in the pool.

**Test 4.5 — Override preservation**

1. Create a new line item from one atom. Note its price.
2. Go back to `#/estimates/2633/` (estimate detail, not wizard).
3. In the line items table, manually edit that line item's price to something clearly different (e.g., change `$150.00` to `$999.00`).
4. Save.
5. Return to the wizard (`#/estimates/2633/wizard`).
6. Add another atom to that same line item via "Add selected atoms here."
7. **Expected:** price stays at $999.00 (override preserved). **NOT** recomputed.

**Test 4.6 — Multi-select and bulk-create**

1. Tick 3 available atoms.
2. Click **Create new line item from selected**.
3. A new line item card appears with 3 sources. Price = sum of all three.

---

## 5. Direct estimate (no worksheet)

**Test 5.1 — Add line items via catalog picker on a worksheet-less estimate**

The seed has draft estimates where this is meaningful. Use **EST-2026-0012** after you finish wizard tests, or pick one of the other 28 draft estimates.

1. Navigate to `#/estimates/2537/` (or any draft estimate with few/no line items).
2. Add line items via picker (covered in section 2).
3. Confirm each line item has **zero source rows** (the wizard page will show them all with empty Sources lists).

---

## 6. Atom carry-over on Estimate acceptance

This is the automatic behavior shipped in Plan C.

**Test 6.1 — Accept an estimate with a worksheet**

1. Pick a draft estimate with a linked draft worksheet. Use **EST-2026-0012** (pk 2633) on J2026-0341.
2. Make sure it has at least one line item (from earlier tests). If not, use "Send all" from the worksheet first.
3. Note the job's current tasks count (navigate to `#/jobs/2629/` briefly and glance).
4. Return to the estimate detail.
5. Move the estimate through status:
   - Click "Mark Open" (or whatever the existing button is labeled) to go draft → open.
   - Click whatever button accepts the estimate to go open → accepted.
6. Job should now have:
   - 5 new Tasks (from the worksheet's 5 PlanCharges): SITE VISIT, CAD, CUT, FINISH, Assemble. Each with a TaskCharge.
   - 1 new Material (from the PlanMaterial): 3/4" Apple plywood.
7. Job status: **approved** (not `in_progress` yet — that's the whole point of the new state).
8. Worksheet status: **final** (locked).

**Test 6.2 — Accept a direct-estimate line item with template ref**

1. Create a new draft estimate on a job that has no worksheet (pick any approved/submitted job without a worksheet, or create a new job).
2. Add line items via catalog picker — specifically, pick **task templates** (so `source_template` gets set).
3. Walk the estimate through draft → open → accepted.
4. Confirm the job now has Tasks matching those templates (Task's `source_template` FK will point to the template).

**Test 6.3 — Purely manual line items don't carry over**

1. Same as 6.2 but add only **manual** line items (no template ref).
2. Accept the estimate.
3. Confirm: **no** Tasks or Materials created automatically. Manual line items don't auto-create atoms.

**Test 6.4 — Idempotent re-acceptance**

1. Pick an already-accepted estimate.
2. Force another carry-over somehow (would require a code or admin-level manipulation; probably skip unless you have a way to trigger it).
3. Expected (if triggered): no duplicate Tasks/Materials. The service skips atoms whose `source_plan_charge` / `source_plan_material` already exists.

---

## 7. Job state machine: `in_progress`

**Test 7.1 — Approved → In Progress transition**

1. After Test 6.1, Job 2629 is in status `approved`.
2. Navigate to `#/jobs/2629/`.
3. A **"Release to floor"** button is visible (only while status is `approved`, and only for users with `can_manage_jobs`).
4. Click it. Confirm dialog: "Release this job to the floor? Workers will see it in In Progress."
5. Click OK.
6. Job status updates to `in_progress`. The button disappears.

**Test 7.2 — Invalid direct transitions blocked**

Using the admin (or the status dropdown on JobDetail if visible):

1. Try to move an approved job directly to `work_complete`. Should fail validation.
2. Try to move an `in_progress` job back to `approved`. Should fail (no reverse transition).

**Test 7.3 — Work complete flow**

1. For an `in_progress` job, go to its task list.
2. Mark all tasks complete (or cancel them).
3. On completing the last one, the job auto-advances to `work_complete`.

---

## 8. Job Board reshuffle

**Test 8.1 — Approved jobs now appear in Pipeline tab**

1. Navigate to `#/jobs/board`.
2. Click the **Pipeline** tab.
3. Approved jobs from the seed (J2026-0003, J2026-0012, J2026-0023, etc.) appear in this column — NOT under "In Progress."
4. Approved jobs have a **distinct gold/amber accent color** distinguishing them from draft/submitted jobs.
5. Within the Pipeline column, approved jobs are grouped under an "Awaiting Prep" divider.

**Test 8.2 — In Progress tab shows only `in_progress` jobs**

1. Click the **In Progress** tab.
2. Only jobs in status `in_progress` are listed. (After Test 7.1, Job 2629 should be here.)
3. Before running Test 7.1, the "In Progress" column may be empty or have only the 7 pre-existing `work_complete` jobs — depending on what the column shows.

**Test 8.3 — Release-to-floor moves job between tabs**

1. On the Pipeline tab, find an approved job.
2. Click into its detail page. Click **Release to floor**.
3. Back to the Job Board. The job has disappeared from Pipeline and appears in In Progress.

---

## 9. Invoicing: in-progress jobs are billable

**Test 9.1 — Open invoice wizard on an in-progress job**

1. Pick an in-progress job (J2026-0006 Polycarb parts, status `work_complete` in the seed — or any job you've promoted via Test 7.1).
2. Navigate to `#/jobs/<id>/` and click **Create Invoice** (or whatever the button is).
3. The invoice opens, the wizard works as before.

**Test 9.2 — Invoice wizard NOT available for draft/submitted jobs**

1. Pick a draft or submitted job.
2. Attempt to create an invoice.
3. Expect 400 error: "Cannot start invoice wizard for job in status…"

---

## 10. Regression sweeps

Quick checks that nothing obvious broke.

**Test 10.1 — Old HTML views still work** (for things we didn't touch)

- `/` home page loads
- `/admin/` loads
- `/contacts/` list renders

**Test 10.2 — Removed URLs return 404**

- `/worksheet/<id>/generate-estimate/` (old HTML view) → 404
- `POST /api/est-worksheets/<id>/generate-estimate/` (old API) → 404
- `POST /api/jobs/<id>/populate-from-estimate/` (old API) → 404

**Test 10.3 — Worksheet detail shows tasks flat (no bundle UI)**

Navigate to `#/worksheets/12/`. The task table should be flat — no "Bundle" group headers, no "Add Bundle" button. The removed `PlanBundleModal.svelte` should never appear.

**Test 10.4 — Existing estimates render correctly after back-fill**

1. Open a completed estimate on an old job (e.g., any estimate on a `completed` job from 2015-2024 in the seed).
2. Line items still show with their original descriptions/prices.
3. If you open its wizard (for non-finalized estimates, draft only): line items that had `task` FKs pre-Plan-C now show source rows after the `0013_backfill_estimate_line_item_source` migration ran.

**Test 10.5 — InvoiceLineItem wizard still works**

1. Pick an unpaid invoice (the seed has plenty of historical invoices).
2. Open its wizard.
3. Confirm source pool, add-to-line-item, remove all still work. The invoice side wasn't touched directly by Plan A/B/C but should continue to function.

---

## 11. Exit checklist

Before considering the branch ready to merge:

- [ ] All sections above pass (mark failing tests with a note).
- [ ] Full backend suite: `python manage.py test` — 2583 passing, 6 skipped (QBO).
- [ ] Frontend builds: `cd frontend && npm run build` — clean.
- [ ] `grep -rn 'generate-estimate\|populate-from-estimate\|EstimateGenerationService\|PlanBundle\|TemplateBundle\|mapping_strategy' apps/ frontend/ templates/ --include='*.py' --include='*.svelte' --include='*.html'` — no hits outside migration files.

## 12. Known limitations (not bugs)

- **Bundled-line-item backfill gap:** `0013_backfill_estimate_line_item_source` only creates source rows for line items with a single task or material FK. Line items that were generated by the old `EstimateGenerationService` bundling (task=None, aggregated price) are NOT back-filled. Affected line items survive and render but show 0 sources in the wizard. If you find any in the seed data, that's expected, not broken.
- **Multi-worksheet-per-estimate races:** `source_pool` endpoint uses `estimate.worksheets.first()` with no ordering. In practice this hasn't bitten anything, but if an estimate has a revision chain with multiple worksheets, the atom pool could pick the wrong one. (Noted in Plan C deferred list.)
- **Conflict-response atom shape:** the 409 response `atom_ids` field contains a list of `{type, id}` dicts, not integers. The frontend wizard doesn't parse this deeply (just alerts), so it's cosmetic. (Noted in Plan C deferred list.)

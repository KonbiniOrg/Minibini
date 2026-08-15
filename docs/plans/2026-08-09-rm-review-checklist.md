# RM browser-review checklist — feature/better-fees (delete when done)

## Make Deliverable button (added 2026-08-12)

One new migration (deliverables/0003) — `python manage.py migrate` on dev.

- [ ] Draft estimate, any line: "Make Deliverable" in Actions copies
      description/qty/units into a job deliverable; the button then
      disappears on that line (comes back if you delete the deliverable).
- [ ] Drift the line's qty after making one → passive amber
      "deliverable: N units" caption on the line (nothing syncs).
- [ ] Remove a linked line → three-way dialog: remove both / keep
      deliverable (unlinks) / cancel.
- [ ] Edit a linked line's qty/description/units → dialog asks "Update it
      to match these changes?" (update both / keep / back); price-only
      edits don't ask. Choosing update refreshes the band's row live.
- [ ] Revise the estimate → the deliverable follows the revision (Make
      Deliverable stays suppressed on the copied line).

## Expiry keeps estimate claims (added 2026-08-13)

- [ ] Expire an estimate (or find one expired): its lines KEEP their
      backing; the atoms show "claimed by estimate N" in other docs'
      pools until you reject/supersede it. Unexpire brings it back with
      backing intact.
- [ ] Rejecting still releases (atoms free again). CO expiry unchanged
      (still releases).

## CO start-new dialog + converter invoice refs (added 2026-08-12)

- [ ] On a rejected (or any terminal) CO with lines: "Start new change
      order" asks — start from this CO's lines/adjustments, or start
      empty. Cancel backs out.
- [ ] Replace… without touching the category: the replacement inherits
      the original line's AC (no more null-AC agreement lines from COs).
- [ ] Converter now emits agreement refs on invoice lines (description-
      matched to the accepted estimate) — after your next reseed, a job
      with an open legacy invoice should NOT re-offer its billed lines on
      Start Invoice. (Existing dev rows stay ref-less until reseeded.)

## Invoice remove-line rework (added 2026-08-12)

- [ ] Removing a seeded invoice line now just drops it — no struck
      in-table row; "Add from agreement" appears immediately and is the
      one restore path.

## Phase 3 — nullable task AC + fallback stamping (added 2026-08-12)

No new migrations — no dev migrate step needed for this phase.

- [ ] Settings → accounting tab: new "Fallback Accounting Category" block —
      designate a category (create an "Uncategorized income" AC first if you
      want a dedicated one; taxable recommended), Save. Deposit-flagged
      categories are refused.
- [ ] The designated fallback disappears from every authoring category
      dropdown (line modals, add-line forms, task edit, material, expense,
      PO line, adjustment targets) but still shows in Settings and still
      renders as a name on any line carrying it.
- [ ] Edit-task modal: Accounting Category now offers
      "— none (categorize at invoicing) —"; clearing it works (money-writer
      only); task detail shows a muted "uncategorized" chip.
- [ ] An estimate line built from that uncategorized task keeps NO category
      (estimates don't stamp) — accept the estimate, start the invoice: the
      seeded line arrives stamped with the fallback and shows the amber
      "uncategorized → {name} · taxable" chip. Fixing the line's AC via
      Edit clears the chip.
- [ ] A percentage adjustment on the agreement seeds through with its REAL
      category (this was the final-review catch — seeded adjustments were
      briefly stripped to null and blocked send).
- [ ] Targeted adjustment + uncategorized lines on one invoice → amber
      warning banner above the table.
- [ ] Send an invoice with a fallback-stamped line: NOT blocked (it has a
      real category). A hand line with no AC at all still blocks send, with
      a message that now mentions the fallback setting.

Covers everything landed since your last review (the deposit path sign-off):
the Fee removal phase and the CO amend-in-place phase. Branch is at
`0c3824a2`, all suites green (backend 4566, Vitest 1478, e2e 81+1 catalogued
flake). Nothing merged/pushed.

## Before you start

- [ ] Run `python manage.py migrate` on dev (6 new migrations: fee purge ×3,
      CO adjustment fields, descoped_by ×2 + backfill estimates/0047).
- [ ] After migrating, sanity check (read-only):
      `SELECT COUNT(*) FROM estimate_line_item_sources WHERE source_type='fee';`
      — expect 0 (same for `co_li_sources`, `invoice_line_item_sources`).
      Your two legacy accepted COs' atoms (jobs 07946, 07724) should now
      carry `descoped_by` stamps.

## Earlier phases — before the CO work (very high level)

The two phases that landed before fee removal: the task-owned-money
transplant (presets) and the skeleton / three-mode surface. Added
2026-08-11 in case the deposit-path sign-off didn't cover all of it.

**Task money & presets**

- [ ] A task carries its own money (rate / per-unit / algorithm shown on
      task detail); editing a rate-scheme preset afterward does NOT change
      existing tasks — only newly stamped ones.
- [ ] Rate schemes are presets now: freely editable, Retire/Reactivate
      (supersession is gone), a default preset picker in settings — and the
      default can't be retired or deleted out from under it.
- [ ] Edit-task modal: Rate Scheme is changeable (restamps the task), Unit
      is a dropdown; money fields only editable with the right permission.
- [ ] Task tables read right: units inline, hour-unit tasks show both Est
      Time and Est Qty.

**Subtasks removed**

- [ ] No subtask affordances anywhere; jobs that had subtasks render flat
      without errors.

**Skeleton / three-mode surface (estimates & invoices)**

- [ ] Both docs have the Views band: Edit / Customer / Reorder (Edit
      relabels to Detail once read-only); mode remembered per document.
- [ ] Estimate Edit is one merged table — lines with nested atoms + backing
      chips, Uncovered-work pool below. The old two-column reconcile
      surface is gone.
- [ ] A new invoice auto-seeds from the accepted agreement; removing a
      seeded line defers it (struck row + Restore, and an "Add to this
      invoice" picker for remaining agreement lines); backing chips show
      actuals vs estimate ("actuals = estimate ✓" when in sync).
- [ ] One live (non-terminal) invoice per job — creating a second is
      refused.
- [ ] Deposit invoices: creation modal opts out of seeding, deposit drafts
      withhold agreement offerings, and the seeded-draw button reads
      "progress invoice".
- [ ] Doc chrome: date chips inline on the title row, no zebra striping on
      the doc edit tables.

## Fee removal (still unreviewed in browser)

- [ ] An estimate with a plain hand line: accept it — no atom appears, the
      line just rides the document; send-time AC guard still blocks a
      category-less hand line.
- [ ] Work-surface picker (task pages) is Add Task / Add Material only — no
      fee entry anywhere; estimate-surface material checkbox unchanged.
- [ ] Job detail of a job that had legacy fees (08008) renders without
      errors; totals look right.
- [ ] Design glance you flagged earlier: a hand line on a deposit-flagged AC
      makes its seeded draft all-deposit (uncovered work hidden) — confirm
      you can live with that.

## CO amend-in-place — the main event

Setup: accepted estimate, hold the job, Create Change Order from the
estimate page (button only appears held + no existing CO).

- [ ] **Edit view is one table — the agreement as amended.** Untouched lines
      show backing chips + "Remove via CO" / "Replace…".
- [ ] Remove via CO: row strikes in place (amount parenthesized, revised
      total drops); Undo restores. No confirm dialogs anywhere.
- [ ] Replace…: modal prefilled from the original; result is a tinted "CO 1"
      row above the struck original, with "inherited from line N" atom rows.
      Footer: original / this CO / revised.
- [ ] Add line (picker: service / inventory / freeform) and add-from-pool
      ("Uncovered work" section → tick atoms → "New line from selected" /
      "Add selected here" on CO add rows).
- [ ] Adjustment amendment: Replace… on a rush-fee/discount line opens the
      percent variant; price recomputes as you change other CO lines;
      untouched stale adjustments show "recomputes to $X if replaced".
- [ ] A line billed on a live invoice: both gestures disabled, "billed on
      INV-NNNN" shown.
- [ ] Views bar: Edit / Customer (delta doc: changed lines only, negated
      removals, Change total + Revised agreement total) / Reorder (CO's own
      lines); mode remembered per CO. Date chips in the toolbar.
- [ ] Send: PDF/email unchanged (still the classic diff document) — verify
      it still looks right.
- [ ] Deleting a CO line works at all (this 500'd before — pre-existing bug
      found and fixed in review).

## CO acceptance outcomes

- [ ] Record Accepted: job un-holds; estimate badge reads "amended".
- [ ] **Replaced line's task is NOT cancelled** — work continues; the claims
      moved to the CO line (this is the big semantic change).
- [ ] Removed line: pending task cancelled / pending material released;
      completed work survives and shows **"descoped by CO-1"** in the next
      invoice's pool.
- [ ] New invoice seeds the replacement/added lines with provenance
      "CO-1 line N"; amounts match the revised agreement.
- [ ] Known accepted consequence: the original estimate's replaced line now
      shows a hand-line chip (its claims genuinely moved) — estimate is
      historical record only.
- [ ] Customer "request changes" from the portal: the seeded revision keeps
      adjustment amendments and its add-lines keep their claimed atoms.

## Known deferred (logged in LATER.md — don't re-report)

Multi-CO chain guards (billed-on guard, duplicate targets, target-ownership
check), per-row billed-on query perf, cross-lens claim race (estimate vs CO
double-claim under race), PDF/portal still baseline on the flat estimate
(single-CO fine), "→ Deliverable" button next cycle.

## Vocab + orientation pass (2026-08-14 — colorways, "Based on", pool renames)

- [ ] **Colorways**: estimate/CO pages tinted indigo, task list + task detail
      amber, invoice pages sage; PO/shipments/history/email pages the muted
      near-grey; non-Job pages (contacts, catalog, settings…) unchanged teal.
      Check the tint reaches: subnav band, view-mode bar, table header bands,
      zebra stripes (palest tint), grand-total rows, date/stat chip headers,
      pool heading, and modal titles + grab bar (open Edit Line Item on an
      estimate vs an invoice — headers should differ).
- [ ] **View labels**: the standalone "Views" caption is gone; chips read
      "Edit view / Customer view / Reorder view" ("Detail view" when locked).
- [ ] **Pool renames**: "Unquoted work" on estimates and COs (CO subtitle:
      "…not in the current agreement"), "Unbilled work" on invoices; the word
      "covered" appears nowhere.
- [ ] **"Based on" column** (was "Backing"), with a caption row above each
      line's grey atom rows: "based on 2 tasks:" / "based on 1 material:" /
      mixed → "items".
- [ ] **Job overview accents realigned**: Scope indigo, Work bright-amber,
      Materials deep-amber, Spend pink (unchanged), Invoicing sage, Delivery
      teal.
- [ ] Task page: materials tables ride the amber band; the in-table
      "Materials (no task)" divider is the lighter 60% tier (deliberate).

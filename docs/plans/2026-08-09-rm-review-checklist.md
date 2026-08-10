# RM browser-review checklist — feature/better-fees (delete when done)

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

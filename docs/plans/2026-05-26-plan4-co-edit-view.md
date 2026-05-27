# Plan 4 — Wire up the change-order edit view (Option B) — Implementation Plan

> Executed via subagent-driven development. The approved **visual spec** is the mockup at
> `.superpowers/brainstorm/62081-1779859915/content/co-edit-view-v3.html` (plus two footer
> tweaks below).

**Goal:** Rebuild the Change Order detail page as the approved "edit-the-estimate, see-the-diff" view (Option B): one merged list where the user edits in place and each edit persists immediately as a CO delta; deliverables on top, line items below, both showing the diff.

**Scope of THIS plan:** the CO detail page itself. Related vision pieces — moving deliverables *editing* onto the draft Estimate page, removing it from the Job, dropping the standalone CO pillar / folding CO into the Estimate bar display — are **follow-ups**, not in this plan.

**Repo:** `/Users/drshiny/Documents/konbini/Minibini`, branch `feature/change-orders`.

**Key behaviors (from the design conversation):**
- **Per-edit persistence** (like the wizard): Change on a clean estimate line → POST a `replace` CO line item (target = that estimate line, new content); Delete → POST a `remove` (target); New → POST an `add`; Undo → DELETE that CO line item. After each call, re-derive the merged view. No client-side batching.
- **Merged/diff view** is computed client-side from the estimate's line items ⊕ the CO's delta line items (the page already fetches both): unchanged · changed (new value, struck original beneath at the same #) · removed (struck, alone) · added. One strikethrough style for any dropped estimate line; position + line number disambiguate changed vs removed.
- **Styling:** plain unstyled buttons; all rows uniform full-width (full-row tints, no shifting borders); amber = changed value, green = added, muted strikethrough = dropped.
- **Footer tweak:** proposed total aligns under the **Total** column; the previous/estimate total stays to its left on the same line; the **± diff** sits under the **actions** column.

---

### Task 1 — Line-items merged-diff editor (frontend)
Rebuild the line-items section of `frontend/src/routes/change-orders/ChangeOrderDetailPage.svelte` to the Option-B merged-diff editor per the mockup + behaviors above. Reuse/repurpose `COLineItemModal` for the Change/New edit form. Build the merged rows from `estimateLines` ⊕ the CO's `line_items`. Wire Change/Delete/New/Undo to the existing CO line-item endpoints with per-edit persistence; reload after each. Footer totals per the tweak. Plain buttons, uniform rows. Verify `npm run build`.

### Task 2 — Deliverables baseline endpoint (backend, TDD)
The deliverables diff needs the prior agreed scope to diff the (editable) live deliverables against. That's the `DeliverableSnapshot` set captured on this CO's creation (Trigger 1), attached to the document the CO amends (the accepted estimate, or the prior accepted CO). Add `GET /api/change-orders/{id}/deliverables-baseline/` returning those snapshot rows (description, qty_ordered, units, sort_order, source_deliverable). TDD.

### Task 3 — Deliverables diff editor on the CO page (frontend)
Add the editable deliverables section at the top of the CO page. Live deliverables come from the job's deliverables endpoint (editable while the CO is draft); diff them against the Task-2 baseline (match by `source_deliverable`): unchanged · changed (new over struck) · removed (struck) · added. Same styling rules as line items (plain buttons, uniform rows). `+ New deliverable`. Verify build.

---

## Self-review
- Spec coverage: line-items editor (T1), deliverables editor+diff (T2 baseline + T3), footer tweaks (T1), plain/uniform styling (T1, T3). Mockup is the visual reference. ✓
- Out of scope (tracked as follow-ups): estimate-page deliverables editor, remove Job deliverables editor, drop CO pillar / Estimate-bar display.
- Order: T1 (visible core, no backend dep) → T2 (baseline endpoint) → T3 (deliverables diff, needs T2).

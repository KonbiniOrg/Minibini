# Job History — Summary tab as milestone log

## Goal

Replace the Job History page's Summary tab (the per-object rollup in
`JobHistorySection.svelte`) with a readable, newest-first event log of the
job's milestones: one row per creation or status change, in the shape
`time | actor | action`. The Timeline tab is untouched — it remains the
forensic layer (field diffs, notes, popovers).

## What gets deleted

All of the current Summary implementation in
`frontend/src/components/jobs/JobHistorySection.svelte`:

- the `summary` `$derived.by` rollup, `milestones()`, `taskExtra()`, `dateStr()`
- the `.summary` / `.sum-sec` markup and styles

## New Summary tab

A single table, newest-first (same order the history feed already arrives in),
built from the same already-fetched `entries` — **no backend changes**.

### Layout

- Columns: `time | actor | action`.
- Full-width day-break rows separate days, labelled like "Wednesday, July 8"
  (include the year when not the current year).
- Within a day, each row shows time only (e.g. "2:47 pm").
- No per-type background tints. Uniform rows.
- The object label in the action text is a link (`source_link`), same as the
  Timeline uses.

### Row derivation (the filter)

For each history entry, in priority order:

1. `changes._created` → row: "**{Type} {label}** created" for documents and
   the job itself (`job`, `estimate`, `changeorder`, `invoice`); "**{Type}
   {label}** added" for everything else (tasks, materials, deliverables,
   shipments). E.g. "Estimate *EST-2025-0012* created", "Task *Bevel edges*
   added".
2. `changes.status` or `changes.consumption_state` diff → a status-transition
   row. Action text:
   - If the entry also carries `changes._action`, show that string (it is
     richer: "Auto-expired (valid 30 days)", "Change order accepted", ...).
   - Otherwise: "**{label}** {verb}" where *verb* = exceptions map lookup on
     the new status, falling back to the humanized raw status
     (underscores → spaces).
3. Anything else (plain field edits, notes, standalone `_action` entries with
   no status diff) → **no row**. Excluded for now; widening this filter later
   is the designed extension point.

Live backend flows sometimes record one status transition as two entries: an
automatic audit entry (status diff, no `_action`) plus a service-written
action entry for the same object carrying the same status diff and
`changes._action`. After the per-entry mapping above, a status-transition row
derived from an audit entry (no `_action`) is dropped when an action-flavored
row exists for the same `object_type` + `object_id` and the same new status,
timestamped within 60 seconds — the action row wins.

### Verb mapping

A **full** verb table keyed by `object_type:status` — every status explicitly
mapped even when the humanized status already reads fine, so either side can
be changed independently later. Change orders duplicate the estimate rows.

| object_type | status | verb |
|---|---|---|
| job | draft | reverted to draft |
| job | submitted | submitted |
| job | approved | approved |
| job | in_progress | started |
| job | work_complete | work completed |
| job | rejected | rejected |
| job | completed | completed |
| job | cancelled | cancelled |
| task | pending | reopened |
| task | in_progress | started |
| task | blocked | blocked |
| task | complete | completed |
| task | cancelled | cancelled |
| estimate / changeorder | draft | reverted to draft |
| estimate / changeorder | open | sent |
| estimate / changeorder | accepted | accepted |
| estimate / changeorder | rejected | rejected |
| estimate / changeorder | expired | expired |
| estimate / changeorder | superseded | superseded |
| invoice | draft | reverted to draft |
| invoice | open | sent |
| invoice | partly-paid | partly paid |
| invoice | paid | paid |
| invoice | defaulted | defaulted |
| invoice | cancelled | cancelled |
| invoice | superseded | superseded |
| material | pending | reset to pending |
| material | consumed | consumed |
| material | released | released |
| shipment | prepared | prepared |
| shipment | picked_up | picked up |

(Deliverables have no status field — they only produce creation rows.)

A status **not** in the table must never drop the row — fall back to the
humanized raw value (underscores → spaces) so new statuses degrade gracefully
instead of vanishing.

### Actor column

`entry.username`; em-dash (—) when null (system / customer-link events — the
`_action` text already says "via customer link" where that matters).

## Testing

TDD, Vitest, `frontend/tests/`. Cover the row-derivation logic:

- created entry → "added" row
- status diff → verb row; exceptions map hit ("sent"); humanize fallback
  ("work complete"); `_action` text preferred when present alongside a status
  diff
- field-edit-only and note entries produce no row
- day-break grouping boundaries
- null username → em-dash

## Out of scope

- Timeline tab, note box, backend, serializers, history recording.
- Notes / receipts / payment actions in the log (possible later widening).

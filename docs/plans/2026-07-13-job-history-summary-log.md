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

### Verb mapping

No per-type spec lists. One small exceptions map keyed by
`object_type:status` (fall back to a status-only key, then to humanized raw):

| key | verb |
|---|---|
| `estimate:open` | sent |
| `invoice:open` | sent |
| `task:in_progress` | started |

Everything else humanizes cleanly (`accepted`, `paid`, `work_complete` →
"work complete", `picked_up` → "picked up", ...). Unknown statuses must never
drop the row — always fall back to the humanized raw value.

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

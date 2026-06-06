# Plan — `appstate` table + settings-UI coverage

_2026-06-06. Implements the decisions from the settings-UI coverage audit
(`docs/plans/2026-06-06-settings-ui-coverage-audit.md`). **Not yet implemented —
for review.** No migrations have been run._

## Goals (from the user)

1. Split machine-managed state out of `Configuration` into a new **`appstate`**
   table, "for safety" — so the settings UI (which edits `Configuration`) can
   never touch counters/cursors that the app writes itself.
2. Remove `estimate_number_sequence` entirely — it's dead (estimates derive
   their number as `{job}-{ver}`, not via `NumberGenerationService`).
3. Give every remaining **UI-less but user-settable** Configuration key an editor,
   on the **Email**, **Business**, or **Setup** tab (Setup may get long — fine).

## Part A — the `appstate` table

New key-value model alongside `Configuration` in `apps/core/models.py`, mirroring
its accessor shape but semantically "written by code, never by a human":

```python
class AppState(models.Model):
    key = models.CharField(max_length=100, unique=True)
    value = models.TextField(blank=True, default='')
    class Meta:
        db_table = 'appstate'
```

(Confirm `db_table='appstate'` is what's wanted — per the user's instruction.)

**Keys to MOVE from `Configuration` → `appstate`** (the auto-managed set from the
audit — self-incrementing counters + the IMAP fetch cursor):

| key | written by | notes |
|---|---|---|
| `job_counter` | `NumberGenerationService` (`apps/core/services.py:155-179`) | self-increments under `select_for_update` |
| `invoice_counter` | same | |
| `po_counter` | same | |
| `latest_email_date` | `EmailService` (`apps/core/services.py:448-456,530`) | IMAP fetch cursor |

**Keys to DELETE outright** (dead — estimates no longer number via the service):
- `estimate_number_sequence`
- `estimate_counter`
- …and the `'estimate'` entries in `NumberGenerationService.SEQUENCE_KEYS` /
  `COUNTER_KEYS` (`apps/core/services.py:81,88`) plus the `'estimate'` row in its
  `MODEL_FIELD_MAP` (`:99`). _Verify_ `generate_next_number('estimate')` has no
  callers before deleting (audit says estimates derive `{job}-{ver}`; grep to confirm).

**Code changes:**
- `NumberGenerationService` reads/writes the three live counters from `AppState`
  (patterns — `*_number_sequence` — stay in `Configuration`, since those ARE
  user-settable; see Part C). Keep the `select_for_update()` thread-safety.
- `EmailService` reads/writes `latest_email_date` from `AppState`.
- Add a tiny `AppState` accessor helper (`get`/`set`/`update_or_create`) so call
  sites read cleanly; keep it out of `__init__.py` (own module or on the model).

**Data migration** (the user runs it — agent never runs `migrate`): a Django data
migration that, for each moved key, creates the `AppState` row from the existing
`Configuration` row then deletes the `Configuration` row; and deletes the two dead
`estimate_*` Configuration rows. Make it idempotent / guard missing rows.

**Fixtures + tests:** update `fixtures/*` and any test `setUp` that seed these keys
into `Configuration` to seed `AppState` instead (the counters especially). Grep
`fixtures/` and tests for the moved key names.

## Part B — durable doc update

Update `docs/designs/data-constraints.md` §1.1 (the Configuration-keys reference):
- Note the **`Configuration` vs `appstate`** split: `Configuration` = user-settable
  settings (has or should have a Settings editor); `appstate` = machine-written
  state (counters, cursors), never edited by hand.
- Move the counter/cursor rows into an `appstate` subsection; drop the `estimate_*`
  numbering rows.

## Part C — settings-UI editors for the UI-less user-settable keys

From the audit's "Gaps" — five keys (well, the three live sequence patterns count
as one fieldset) with no editor today. Proposed homes:

| key | what it controls | tab |
|---|---|---|
| `our_domain` | outgoing email Message-ID domain; silently falls back to `example.com` (`apps/core/services.py:1263`) | **Business** (next to the other shop-identity fields) |
| `email_display_limit` | inbox display count (`services.py:469`, `email/views.py:44`) | **Email** (beside the existing Retention field) |
| `est_expire_days` | default estimate expiry window (`estimates/models.py:137,270`) | **Setup** |
| `board_closed_retention_days` | how long closed jobs linger on the Job Board (`jobs/services.py:1274,1486`) | **Setup** |
| `job_number_sequence`, `invoice_number_sequence`, `po_number_sequence` | document-number **format patterns** (`{year}`/`{counter:04d}` etc.) | **Setup** — a new "Document numbering" fieldset |

Notes:
- The document-number **patterns** stay user-settable in `Configuration`; only the
  **counters** move to `appstate`. The numbering fieldset edits patterns only — do
  NOT expose counters in the UI.
- `default_tax_rate` / `org_tax_multiplier` are still on the legacy Django tax form
  (audit) — out of scope here, but worth a follow-up to port to the Svelte
  Accounting tab.
- Follow the existing settings-tab conventions (the `/api/settings/` PATCH endpoint
  already writes arbitrary keys; each new field just needs a labelled input + save).
- Add/extend the settings component tests for each new editor.

## Suggested order

1. `AppState` model + accessor + data migration + service rewrites (Part A) — behind
   no UI; verify counters/email-cursor still work via tests.
2. Delete the dead `estimate_*` keys + service entries.
3. Durable-doc update (Part B).
4. Settings-UI editors (Part C), one tab at a time, with tests.

_Done when:_ machine state lives in `appstate`, `estimate_number_sequence`/`_counter`
are gone, every user-settable Configuration key has a Settings editor, and
`data-constraints.md` §1.1 reflects the split.

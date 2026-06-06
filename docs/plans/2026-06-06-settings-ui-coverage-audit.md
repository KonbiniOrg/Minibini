# Settings-UI Coverage Audit — Configuration keys

Every **user-settable** `Configuration` key should be editable somewhere in the Settings
UI. **Auto-managed** keys (counters that self-increment, IMAP cursor state) are excluded
from needing an editor — exposing them would invite corruption. This audit addresses the
LATER item "Audit Configuration keys for settings-UI coverage" (`docs/designs/LATER.md`,
added 2026-05-31): review every key the backend reads/writes and confirm each
user-settable one is editable, nothing silently un-editable.

All claims below are verified against code (grep/Read), not the design doc alone. The
generic settings PATCH (`apps/api/templates_config/views.py:216-243`, `settings_view`)
will write *any* key, so a key being writable through the API does **not** mean a user can
discover/edit it — only a dedicated editor component/field counts as "has editor."

## Summary

- **Total distinct keys found:** 27
- **User-settable keys:** 22
- **User-settable keys WITH an editor:** 17
- **User-settable keys with NO editor (gaps):** 5
- **Auto-managed / excluded keys:** 5
  (4 document-number counters + `latest_email_date`)

Note on the 8 document-numbering keys: the 4 `*_counter` keys are auto-managed
(excluded). The 4 `*_number_sequence` pattern keys are user-settable in principle but
have no editor — counted among the 5 gaps as a single grouped gap line plus the others.
(Counted individually below; the headline "5 gaps" groups the 4 sequence patterns as one
gap area + 1 other = the distinct gap *areas*; the table lists each key.)

## Key-by-key

| key | backend usage (file:line) | user-settable? | has editor? (where) | verdict |
|---|---|---|---|---|
| `job_number_sequence` | `apps/core/services.py:80,139` (NumberGenerationService) | Yes | **No** | GAP |
| `invoice_number_sequence` | `apps/core/services.py:82,139` | Yes | **No** | GAP |
| `po_number_sequence` | `apps/core/services.py:83,139` | Yes | **No** | GAP |
| `estimate_number_sequence` | `apps/core/services.py:81,139` (legacy; estimates now derive `{job}-{ver}`) | Marginal | **No** | GAP (low priority — may be retired) |
| `job_counter` | `apps/core/services.py:87,155-179` (self-increment) | No (auto) | n/a | EXCLUDED |
| `invoice_counter` | `apps/core/services.py:89,155-179` | No (auto) | n/a | EXCLUDED |
| `po_counter` | `apps/core/services.py:90,155-179` | No (auto) | n/a | EXCLUDED |
| `estimate_counter` | `apps/core/services.py:88,155-179` | No (auto) | n/a | EXCLUDED |
| `units_list` | `apps/core/units.py:22`; `apps/api/templates_config/views.py:247-270` (units_view) | Yes | Yes — Setup tab → `UnitsManager.svelte` (`/api/settings/units/`) | OK |
| `default_tax_rate` | `apps/core/services.py:1147`, `views.py:316,337`; `services.py:1215` (write) | Yes | Yes — legacy Django form `templates/core/tax_config_form.html`, linked from Accounting tab as "Edit tax settings (legacy)" | OK (legacy) |
| `org_tax_multiplier` | `apps/core/services.py:1176`, `views.py:321,343`; `services.py:1220` (write) | Yes | Yes — same legacy tax form | OK (legacy) |
| `qbo_payment_accounts` | `apps/qbo/services.py:529`; `frontend/.../paymentAccounts.js:17,47` (write) | Yes | Yes — Accounting tab → Payment accounts table (`SettingsPage.svelte:71-103`) | OK |
| `email_retention_days` | `apps/core/services.py:463-465,568` | Yes | Yes — Email tab → `EmailTemplates.svelte` (Retention fieldset) | OK |
| `email_display_limit` | `apps/core/services.py:469-471`; `apps/core/views.py:44` | Yes | **No** | GAP |
| `latest_email_date` | `apps/core/services.py:448-456,530` (IMAP fetch cursor, code-written) | No (auto) | n/a | EXCLUDED |
| `est_expire_days` | `apps/estimates/models.py:137,270` | Yes | **No** | GAP |
| `business_email` | `apps/estimates/services.py:404` | Yes | Yes — Business tab → `BusinessSettings.svelte` ("Notification email") | OK |
| `our_public_url` | `apps/core/email_templates.py:55` | Yes | Yes — Business tab → `BusinessSettings.svelte` ("Public site URL") | OK |
| `our_domain` | `apps/core/services.py:1263` (Message-ID domain; falls back to `example.com`) | Yes | **No** | GAP |
| `board_closed_retention_days` | `apps/jobs/services.py:1274,1486` | Yes | **No** | GAP |
| `blep_minimum_minutes` | `apps/jobs/services.py:72-76`; validated at `templates_config/views.py:228` | Yes | Yes — Schedule tab → `ScheduleSettings.svelte` (Time tracking) | OK |
| `schedule_workday_start` | `apps/schedule/services.py:27,51` | Yes | Yes — Schedule tab → `ScheduleSettings.svelte` | OK |
| `schedule_workday_end` | `apps/schedule/services.py:28,52` | Yes | Yes — Schedule tab → `ScheduleSettings.svelte` | OK |
| `schedule_task_buffer_minutes` | `apps/schedule/services.py:29,53` | Yes | Yes — Schedule tab → `ScheduleSettings.svelte` | OK |
| `schedule_horizon_days` | `apps/schedule/services.py:30,71` | Yes | Yes — Schedule tab → `ScheduleSettings.svelte` | OK |
| `estimate_email_subject_template` / `estimate_email_body_template` | `apps/estimates/services.py:345,351` | Yes | Yes — Email tab → `EmailTemplates.svelte` | OK |
| `po_email_subject_template` / `po_email_body_template` | `apps/purchasing/services.py:597,604` | Yes | Yes — Email tab → `EmailTemplates.svelte` | OK |
| `invoice_email_subject_template` / `invoice_email_body_template` | `apps/invoicing/services.py:158,164` | Yes | Yes — Email tab → `EmailTemplates.svelte` | OK |

(The six email-template keys are listed as three rows above for brevity; each of the six
has its own editor field in `EmailTemplates.svelte`.)

### Not Configuration keys (confirmed, for completeness)

IMAP connection settings (`imap_server`, `email`, `password`, `mailbox_folder`) are **not**
Configuration rows — they come from Django settings/env
(`apps/core/services.py:237-240`, `EMAIL_IMAP_SERVER` / `EMAIL_HOST_USER` /
`EMAIL_HOST_PASSWORD` / `EMAIL_IMAP_FOLDER`). Out of scope for a Settings-UI editor.

## Gaps — user-settable keys with NO editor

1. **`our_domain`** — used to build outgoing email Message-IDs
   (`apps/core/services.py:1263`); falls back to `example.com` when unset, so unconfigured
   shops send mail with a bogus domain. **Recommendation:** add a field to the **Business
   tab** (`BusinessSettings.svelte`), next to `business_email` / `our_public_url` — it is
   the same "who are we" identity group.

2. **`board_closed_retention_days`** — controls how long closed jobs stay on the Job Board
   (`apps/jobs/services.py:1274,1486`). **Recommendation:** no obvious home today; add a
   small "Job Board" fieldset, most naturally on a **Setup tab** (or a new "Jobs" tab),
   editable as a number-of-days input.

3. **`est_expire_days`** — default estimate expiry window
   (`apps/estimates/models.py:137,270`). **Recommendation:** add to the **Setup tab**
   (it's an estimating default), or co-locate with a future "Estimates" settings group.

4. **`email_display_limit`** — how many emails the inbox shows
   (`apps/core/services.py:469`, `apps/core/views.py:44`). **Recommendation:** add to the
   **Email tab** (`EmailTemplates.svelte`), next to the existing Retention field — both are
   inbox-behavior knobs.

5. **Document-number sequence patterns** —
   `job_number_sequence`, `invoice_number_sequence`, `po_number_sequence`
   (and the legacy `estimate_number_sequence`). No editor anywhere
   (`apps/core/services.py:80-83,139`). These define the human-facing numbering format
   (e.g. `JOB-{year}-{counter:04d}`). **Recommendation:** add a "Document numbering"
   fieldset on the **Setup tab** with one text input per sequence pattern and inline help
   for the `{year}/{month:02d}/{day:02d}/{counter:04d}` placeholders. Do **not** expose the
   `*_counter` rows. `estimate_number_sequence` can be omitted/marked deprecated since
   estimate numbers now derive from the job number.

## Excluded (auto-managed) keys

These are written/incremented by code and must not get a user editor:

- `job_counter`, `invoice_counter`, `po_counter`, `estimate_counter` — incremented under
  `select_for_update()` by `NumberGenerationService` (`apps/core/services.py:155-179`).
- `latest_email_date` — IMAP fetch cursor, advanced after each fetch
  (`apps/core/services.py:530`).

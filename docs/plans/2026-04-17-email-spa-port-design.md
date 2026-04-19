# Email area: port from Django HTML to Svelte SPA

## Goal

Move the email inbox, detail, link/unlink, and create-job-from-email flows out of Django HTML views and into the Svelte SPA. The `/email` sidebar link currently points to an unmounted route; this work wires it up. Compose is out of scope — its backend (`POST /api/emails/send/`) is still a 501 stub.

## Current state

**Django HTML views (`apps/core/views.py`)**

- `email_inbox` — on page load, triggers IMAP fetch (30 days back), then renders up to `email_display_limit` TempEmail rows. Blocks on fetch.
- `email_detail` — fetches full content from IMAP on-demand (only `message_id` is stored locally).
- `create_job_from_email` — session-driven multi-step flow: parses sender, finds-or-creates contact, matches Business by name, bounces through three views via redirects with `email_record_id_for_job` / `contact_name` / `suggested_business_id` in the session.
- `associate_email_with_job` — GET form with full-jobs dropdown, POST links.

**API already in place (`apps/api/email/`)**

- `GET /api/emails/` (paginated, optional `?job=` filter)
- `GET /api/emails/{id}/` — includes `content` fetched on-demand from IMAP
- `POST /api/emails/{id}/link-to-job/` / `unlink-from-job/` / `create-job/`
- `POST /api/emails/send/` — 501 stub (out of scope)

**SPA state**

- Sidebar link to `/email` exists, route is unmounted, no components.

## Backend additions

Two small endpoints — both thin wrappers around functions that already exist in `apps/core/services.py` and `apps/core/email_utils.py`.

### `POST /api/emails/refresh/`

Wraps `EmailService().fetch_emails_by_date_range(days_back=30)`. Returns `{new, existing, errors}`. Permission: `IsAuthenticated`.

Replaces the implicit fetch-on-page-load in `email_inbox`. The SPA calls it explicitly so the inbox list can render immediately from cached data while the fetch runs in the background.

### `GET /api/emails/{id}/sender-info/`

Runs `parse_email_address` + `extract_company_from_signature` + `extract_email_body` on the fetched content, plus contact/business lookups. Returns:

```json
{
  "sender_name": "Jane Doe",
  "sender_email": "jane@acme.com",
  "suggested_body": "...first 200 chars of email body...",
  "matching_contacts": [{"id": 1, "name": "...", "email": "...", "business": {...}}],
  "extracted_company": "Acme Corp",
  "matching_businesses": [{"id": 1, "business_name": "Acme Corp"}]
}
```

Permission: `IsAuthenticated` + `CanManageJobs` (first step of a job-creation flow).

Replaces the server-session plumbing that the Django `create_job_from_email` view uses to thread state across redirects. The SPA page fetches this once and drives the whole flow from one component.

## Frontend structure

```
frontend/src/routes/email/
  EmailInboxPage.svelte
  EmailDetailPage.svelte
  EmailCreateJobPage.svelte
  EmailAssociatePage.svelte
frontend/src/components/email/
  EmailList.svelte       (table)
  EmailContent.svelte    (headers + body + attachments)
frontend/src/lib/api/email.js   (list, get, refresh, senderInfo, link, unlink, createJob)
```

Plus four route entries in `App.svelte`:

```
/email                    EmailInboxPage
/email/:id                EmailDetailPage
/email/:id/create-job     EmailCreateJobPage
/email/:id/associate      EmailAssociatePage
```

Four routes, no modals. Matches how jobs/contacts are already organized, supports deep-linking, and lets the associate / create-job pages be reached from other places later (e.g. a "recent unlinked emails" widget).

Email context is always identified by the URL `:id` param. No cross-page state or stores — every page fetches what it needs. This replaces Django's session flow (`email_record_id_for_job`, `contact_name`, `suggested_business_id`) and makes browser-back behave correctly.

## Page designs

### EmailInboxPage

On mount: parallel `GET /api/emails/?page=1` and `POST /api/emails/refresh/`. List renders from the first call immediately; when refresh resolves, re-fetch page 1 if `new > 0`. A small banner reports refresh status (`3 new, 27 existing` / `checking server...` / error).

Manual Refresh button re-runs the same sequence. No auto-polling.

Table columns (parity with Django): Date, From, Subject, Job (link or "None"), Attachments (yes/no). Subject links to `/email/:id`. `StandardPagination` at 25/page. No filters in this pass.

### EmailDetailPage

On mount: `GET /api/emails/{id}/` (includes `content`, or `content: null` on IMAP fetch failure).

Three render states, matching Django:

1. **Content present** — headers table (From/To/CC/Date/Subject/Job), body (HTML via `{@html}` or text in `<pre>`), attachments list (filename + type + size, no download — Django doesn't expose one either).
2. **Content null, temp_data present** — "Full content unavailable, showing cached metadata" + smaller headers table.
3. **Neither** — "Email not found or could not be retrieved" + message_id.

Action buttons at top, conditional on `email.job`:

- Unlinked: `Create Job from this Email` → `/email/:id/create-job`; `Associate with Existing Job` → `/email/:id/associate`.
- Linked: job number link + `Disassociate` button (calls `POST /api/emails/{id}/unlink-from-job/`).

**XSS note:** rendering raw email HTML via `{@html}` is the same trust-the-bytes behavior as Django's `|safe`. Ported as-is for parity. Sanitization (DOMPurify) is a follow-up, not part of this port.

### EmailCreateJobPage

On mount: `GET /api/emails/{id}/sender-info/`. Page branches on what it gets back.

- **Single contact match** — "Create job for Jane Doe at Acme?" with job-name field + Create button. One click → `POST /api/emails/{id}/create-job/` with `contact` + `name`, navigate to new job.
- **Multiple contact matches** — radio list of matches + "none of these, create new" option. Django today silently picks the first match; the SPA fixes this by asking.
- **No contact match** — inline contact form pre-filled with parsed name + email, plus a business picker that shows `matching_businesses` as suggestions alongside "create new business" and "no business". Submit creates contact (and business if needed) via existing `/api/contacts/` + `/api/businesses/`, then calls create-job.

All branches end with `POST /api/emails/{id}/create-job/`, which already links the email atomically server-side.

The whole flow lives in one component. The user never leaves until the job exists. This collapses the Django three-redirect chain into a single stateful page.

### EmailAssociatePage

On mount: parallel `GET /api/emails/{id}/` (for the summary header) and `GET /api/jobs/` for the dropdown.

Form: job `<select>` of non-terminal jobs + Associate + Cancel. Submit → `POST /api/emails/{id}/link-to-job/` with `{job_id}`, then navigate back to `/email/:id`.

Full dropdown (matching Django), not typeahead. Fine at current volume; upgrade later if needed.

## Out of scope

- Compose email (backend is 501).
- Attachment downloads (Django doesn't expose this either).
- HTML email sanitization (parity with current `|safe` behavior).
- Deleting the Django HTML templates/views. Keep them live through this PR; remove in a follow-up once the SPA version is in use.

## Risks

- **Sender-info endpoint has to fetch email content from IMAP** — same latency as the detail page. Acceptable since create-job is user-initiated and infrequent.
- **Refresh-on-mount races first page load** — mitigated by rendering cached list first and only re-fetching if `new > 0`.
- **The existing create-job API takes `contact` + `name` and already links the email** — means the new frontend flow is just UI over existing primitives. No transaction/ordering concerns beyond what's already tested.

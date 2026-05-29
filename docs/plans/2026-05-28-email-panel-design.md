# Email panel on the job overview — design spec

**Status:** Draft, ready for review.
**Date:** 2026-05-28
**Scope of this spec:** replace the History pane on the job overview with an
Email pane, factor reply-quote stripping into a reusable utility, and start
caching IMAP bodies on `TempEmail` so list-style consumers can render a snippet
without re-hitting IMAP. Out of scope: outgoing-email tracking (stubbed in the
data shape only), older-job email re-hydration after retention purge, the
History pane's eventual replacement.

---

## 1. Problem

The Job overview today renders a single bottom-right pane labelled "History",
implemented by `frontend/src/components/HistoryPanel.svelte`. The panel mixes
two streams: `HistoryEntry` rows and `EmailRecord` rows linked to the job. The
email rows are minimal — subject, sender address, an expand toggle, and a
"View full email" link — because no body is available client-side without an
extra IMAP round-trip per email.

The user wants the email stream pulled out into a dedicated pane and given a
proper compact rendering (sender or recipient, subject, a one-line snippet of
the actual body with reply-chains stripped). The History stream stays in the
codebase as a component for a later round of work, but stops being mounted on
the job overview for now.

## 2. Component layout

Three existing components change; one new component appears.

- **`frontend/src/components/HistoryPanel.svelte` (kept)** — left in the tree
  as a still-functional component. No consumer mounts it after this work. The
  "later" History redesign will pick it up. The mixed history+email logic
  inside today's `HistoryPanel.svelte` is split: the email branch moves out
  (see below); the history branch (note entry textarea + history-entry
  rendering) stays.
- **`frontend/src/components/EmailPanel.svelte` (new)** — renders the email
  list. Takes one prop, `emails`, the paginated response from
  `/api/emails/?job=<id>`. No "Add Note" textarea. Density: each email is a
  two-line card — row 1 is `<date> <direction-glyph> <display_address>
  <subject>`, row 2 is the snippet, one line, ellipsis on overflow. The whole
  card is a link to `#/email/<email_record_id>`. Outbound rows get a tinted
  background so direction is readable at a glance.
- **`frontend/src/components/jobs/JobDetail.svelte`** — swap the
  `<HistoryPanel … />` mount in the bottom-right panel for
  `<EmailPanel emails={emails} />`. The surrounding `.panel.history-panel`
  container, scroll host, and CSS scope stay the same so the layout doesn't
  shift; only the inner component changes.
- **`frontend/src/routes/jobs/JobDetailPage.svelte`** — drop the
  `/api/jobs/<id>/history/` fetch, the `history` state binding, and the
  `handleAddNote` handler. The history endpoint itself stays on the API; the
  later History work will re-wire it.

## 3. Reply-quote stripping (server-side, reusable)

New function in `apps/core/email_utils.py`:

```python
def strip_quoted_reply(text: str) -> str:
    """Trim a plain-text email body at the first reply or forward marker.

    Recognizes:
      - lines starting with '>' (Gmail, most clients)
      - "On <date>, <person> wrote:"
      - "-----Original Message-----" (Outlook classic)
      - Outlook forward header block "From: ...\\nSent: ...\\nTo: ..."
      - "Begin forwarded message:" (Apple Mail forward)

    Normalizes CRLF -> LF before matching so IMAP bodies behave. Returns the
    body up to (not including) the first marker, rstrip'd. If no marker
    matches, returns the input unchanged.
    """
```

`extract_email_body` is refactored so its `>`-line stripping calls into
`strip_quoted_reply` instead of inlining the logic. That keeps the existing
deprecated-HTML-view caller (`apps/core/views.py`) working without change while
making the function reusable by anything else that wants a clean body.

The function operates on plain text only. For HTML-only emails, callers that
need a text representation strip tags first (the snippet path in §5.1 does
this with a regex; a richer HTML→text helper is a deferred follow-up,
§10.4).

## 4. IMAP body caching on `TempEmail`

Today `TempEmail` (`apps/core/models.py:108`) stores only metadata. Body
fetches happen on demand via `EmailService.get_email_content()` and re-hit
IMAP every call (`apps/core/services.py:278`). For the Email pane to show a
per-email snippet we need the body available at list time, not detail time.

### 4.1 Model change

Add two fields to `TempEmail`:

```python
text_body = models.TextField(blank=True, default='')
html_body = models.TextField(blank=True, default='')
```

One migration. Existing rows backfill empty; they'll re-cache on the next
`refresh` cycle for any UID still present on the server.

### 4.2 Population

`EmailService.fetch_emails_by_date_range` (`apps/core/services.py:240`)
already has `msg.text` and `msg.html` in scope at the
`TempEmail.objects.create(...)` call site. Add them to the call:

```python
TempEmail.objects.create(
    ...,
    text_body=msg.text or '',
    html_body=msg.html or '',
)
```

### 4.3 Read path

`EmailService.get_email_content()` (`apps/core/services.py:278`) prefers the
cached body when `email_record.temp_data` is present and has a non-empty
`text_body` or `html_body`. The existing IMAP UID fetch becomes the fallback
when the cache is missing or empty (e.g., backfilled rows, or rows whose temp
data has been purged). This also speeds up `sender_info` and the email-detail
page as a side benefit.

### 4.4 Retention

Cached bodies are deleted alongside the rest of `TempEmail` per the existing
retention policy (`email_retention_days` Configuration key). No new retention
knob needed.

### 4.5 Older-job emails (noted, deferred)

After retention purge, a job's emails lose their `temp_data` and therefore
their cached body. The pane will list those emails without a snippet (see
§5.3); the dedicated email-detail page already re-fetches by UID when it can,
falling back to a "details no longer cached" placeholder when not. Re-hydration
on demand (re-fetching by `Message-ID` to rebuild a snippet for an older job's
list view) is **out of scope here** and tracked as a follow-up. The cleanest
shape will be a service-level method like `EmailService.rehydrate(email_id)`
plus a UI trigger; we'll design that when we revisit older-job display.

## 5. API + serializer changes

### 5.1 `EmailRecordSerializer` (`apps/api/email/serializers.py`)

Three new computed read-only fields:

- `direction` — `'inbound' | 'outbound'`. Hard-coded to `'inbound'` today
  because every `EmailRecord` is IMAP-fetched. The field exists now so future
  outgoing-email tracking can drop in without a serializer/API contract
  change.
- `display_address` — for `'inbound'`, `temp_email.from_email`; for
  `'outbound'` (when that lands), the first address parsed out of
  `temp_email.to_email`. Single field, computed server-side, so the pane
  doesn't branch on direction client-side.
- `snippet` — derived from the cached body. Pipeline:

  ```
  if temp_email.text_body:
      source = temp_email.text_body
  elif temp_email.html_body:
      source = re.sub(r'<[^>]+>', '', temp_email.html_body)  # tag-strip
  else:
      source = ''
  cleaned = strip_quoted_reply(source)
  collapse runs of whitespace (including newlines) to a single space
  truncate to 80 chars with ellipsis
  ```

  **When `temp_data` is missing entirely (purged), `snippet` is `''`** — the
  pane treats an empty snippet as "no preview available" and renders the row
  without the second line.

For HTML-only emails the regex tag-strip is sufficient for 80-char snippet
purposes; we don't add an HTML parser dependency. The dedicated email-detail
page's richer HTML rendering is a deferred follow-up (§10.4).

### 5.2 List endpoint behavior

`/api/emails/?job=<id>` already filters to the job. The new fields ship on
both the list and detail responses (the serializer is the same). Pagination
unchanged.

### 5.3 No new endpoints

Everything needed for the pane is on the existing list endpoint after the
serializer additions.

## 6. Direction stub for the SPA

`EmailPanel.svelte` branches on `direction`:

- `'inbound'`: row prefix glyph `←`, no tint; `display_address` is the
  sender.
- `'outbound'`: row prefix glyph `→`, tinted background; `display_address` is
  the recipient.

Today every email is `'inbound'`, so the outbound branch is unused but
rendered correctly when the data eventually arrives. No SPA-side conditional
"if we ever support outbound" guards.

## 7. Tests

- **`tests/test_email_utils.py`** — `strip_quoted_reply`: one case per marker
  style (`>`-line, `On X wrote:`, `-----Original Message-----`, Outlook
  forward block, `Begin forwarded message:`), a CRLF case, a no-marker
  passthrough.
- **`tests/test_email_models.py`** — `TempEmail.text_body` and
  `TempEmail.html_body` round-trip.
- **`tests/test_api_email.py`** — list response includes `direction`,
  `display_address`, `snippet`; snippet is non-empty when `text_body` is
  cached and `''` when `temp_data` is missing.
- **SPA** — no JS test runner here; manual verification on the job overview:
  - Cached email shows snippet on row 2.
  - Email with no cached body (simulated by clearing `text_body`) shows only
    row 1.
  - Card click navigates to `#/email/<id>`.

## 8. Files touched

| File | Change |
|---|---|
| `apps/core/models.py` | Add `TempEmail.text_body`, `TempEmail.html_body` |
| `apps/core/email_utils.py` | New `strip_quoted_reply`; refactor `extract_email_body` to use it |
| `apps/core/services.py` | Populate body on fetch; prefer cache in `get_email_content` |
| `apps/api/email/serializers.py` | Add `direction`, `display_address`, `snippet` |
| `frontend/src/components/EmailPanel.svelte` | New |
| `frontend/src/components/HistoryPanel.svelte` | Strip email branch out; keep history-only version |
| `frontend/src/components/jobs/JobDetail.svelte` | Mount `EmailPanel` in the old History slot |
| `frontend/src/routes/jobs/JobDetailPage.svelte` | Drop history fetch + add-note handler |
| `tests/test_email_utils.py` | `strip_quoted_reply` cases |
| `tests/test_email_models.py` | Body field round-trip |
| `tests/test_api_email.py` | New serializer field assertions |
| migration | One auto-generated for the `TempEmail` columns |

## 9. Docs to update post-implementation

Per CLAUDE.md "Keep these current":

- `docs/designs/architecture-and-conventions.md` — note `EmailPanel` lives
  where `HistoryPanel` used to on the Job overview; mention the
  `text_body`/`html_body` cache on `TempEmail` and that
  `EmailService.get_email_content` reads it first.
- CLAUDE.md "Email-to-Job Workflow" subsection — sentence about body caching.

## 10. Open follow-ups (explicitly deferred)

1. Outgoing email persistence — model + `OutboundEmailService` wiring + UI
   compose path.
2. Older-job email re-hydration after retention purge — `EmailService`
   on-demand re-fetch + UI trigger.
3. History pane replacement — re-mount `HistoryPanel.svelte` (likely
   alongside the Email pane rather than replacing it).
4. Richer HTML rendering (sanitized) on the dedicated email-detail page;
   today's text/plain-first behavior is kept.

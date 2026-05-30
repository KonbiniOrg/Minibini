# Email reply composer + send-path cleanup — design spec

**Status:** Draft, ready for review.
**Date:** 2026-05-29
**Scope:** add a free-form Reply composer for inbound emails, building on
the outbound foundation shipped in
`docs/plans/2026-05-29-outgoing-email-and-reply-tracking-design.md`. Add
a `{object_url}` placeholder (stubbed) to the document-send template
variable set. Bundle in a small cleanup that retires `send_email` /
the deprecated Django HTML compose view / the orphaned legacy
`QBOInvoiceSyncService.push_invoice` path, leaving
`OutboundEmailService.send_tracked` as the single outbound entry point.

Out of scope: free-form **new** email (composing a brand-new outbound
without an inbound parent) — explicitly dropped after a round of
brainstorming; not building it. Customer-facing public URLs for
view/accept/reject of documents — separate spec when it lands; the
`{object_url}` placeholder here is a stub against an
`our_public_url` Configuration default.

---

## 1. Problem

Inbound emails arrive, get linked to a Job / PO / Bill via the action
panel, sit there. There's no in-app way to *respond* to them; the user
has to switch to Gmail, paste the customer's address, write the reply,
hope the threading works. The outbound foundation already exists
(`OutboundEmailService.send_tracked` persists the email, threads via
the Message-ID we control, sets up the parent for reply correlation on
the next inbound) — but no SPA surface has a Reply button.

The other gap noticed during the brainstorm: the existing PO and
Estimate body templates can mention things like "Click here to view
your estimate," but there's no useful URL placeholder to substitute.
The real customer-facing public URL feature is bigger work (signed
tokens, public read views, accept/reject API) — deferred. A stubbed
`{object_url}` placeholder lets users author the boilerplate against a
sane URL shape now, with the real resolution swapped in when the
public URL feature lands.

## 2. Reply composer

### 2.1 Entry point

`EmailActionPanel.svelte` gains a new section at the top of the rail,
above the existing Job / Purchase Order / Bill grouping. Single styled
`<a>` element labelled "Reply" that routes to `#/email/:id/reply`.
Visible to any authenticated user (no permission atom required —
anyone reading the email can reply; the body is their own words).

### 2.2 Route + page

New SPA route `/email/:id/reply` mounting
`frontend/src/routes/email/EmailReplyPage.svelte`. The page:

1. Fetches `/api/emails/:id/` (the parent email record + its temp body
   and content) and `/api/emails/:id/reply-defaults/` (the prefilled
   form payload — see §2.4) in parallel.
2. Mounts the existing `DocumentSendForm.svelte` with no
   auto-attached PDFs (`sendDefaults.attachments_preview = []`),
   prefilled with the reply-defaults response.
3. Submit POSTs `multipart/form-data` to
   `/api/emails/:id/reply/` via `api.postMultipart`.
4. On success, navigates back to the parent email detail page
   (`#/email/:id`). On failure, the form-page surface stays open with
   the error visible (`DocumentSendForm`'s existing pattern).

Below the form, render a read-only snapshot of the parent email
(From / Subject / Date / body) so the user has the original in front
of them while composing — mirrors the document-send pattern.

### 2.3 API endpoints

Two new endpoints on the email API:

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/emails/{id}/reply-defaults/` | Pre-populated reply form payload (§2.4) |
| `POST` | `/api/emails/{id}/reply/` | Build outbound, delegate to `send_tracked` |

Both require `IsAuthenticated`. No atom. The `POST` accepts
multipart `attachments` files in addition to the JSON body fields
(matching the document-send endpoints' shape).

### 2.4 Reply prefill payload

`GET /api/emails/{id}/reply-defaults/` returns:

```json
{
  "to": "jane@customer.com",
  "cc": "",
  "bcc": "",
  "subject": "Re: Quote for bracket",
  "body": "\n\nOn Wed, May 28, 2026 at 9:32 AM, Jane Doe <jane@customer.com> wrote:\n> Hi,\n> \n> Could you quote 50 brackets…\n",
  "in_reply_to": "<parent-message-id@gmail.com>",
  "references": "<thread-root@gmail.com> <other@gmail.com> <parent-message-id@gmail.com>",
  "inherit_associations": {"job": 42, "purchase_order": null, "bill": null}
}
```

- **`to`** — parent `temp_email.from_email`.
- **`cc`** / **`bcc`** — blank by default. (Reply-All is out of scope;
  the user types CCs themselves if needed.)
- **`subject`** — see §2.5.
- **`body`** — quoted-original block; see §2.6.
- **`in_reply_to`** — parent's `message_id` (the value we'll set on
  the outgoing message's In-Reply-To header).
- **`references`** — parent's `temp_email.references` (if any) with
  the parent's `message_id` appended. Space-separated. When parent
  has no `references` saved, just the parent's `message_id`.
- **`inherit_associations`** — the parent's `job_id` /
  `purchase_order_id` / `bill_id` (nulls included). The reply send
  uses these to set the outbound EmailRecord's FKs.

The SPA echoes the threading headers and `inherit_associations` back
unchanged in the POST. Server treats the client-sent values as
authoritative-but-replaceable: it accepts whatever the SPA sends. (We
don't try to validate that the user didn't tamper with the
In-Reply-To, because they could just edit the body to look like a
quote and start a new thread either way — there's no security
boundary here. The headers exist for threading correctness.)

### 2.5 Subject building

Helper `_build_reply_subject(parent_subject: str) -> str`:

1. Strip leading `Re:` / `RE:` / `Fwd:` / `FW:` prefixes (any
   combination, any number) — reuse the existing
   `_SUBJECT_PREFIX_RE` in `apps/core/email_utils.py` (already used
   by `clean_subject_for_job_name`).
2. Prepend exactly one `Re: ` to the result.

So `Re: Re: Fwd: Quote for bracket` → `Re: Quote for bracket`. Empty
parent subject → `Re: (no subject)`.

### 2.6 Quoted-original body builder

New helper `build_reply_body(parent_email) -> str` in
`apps/core/email_utils.py`. Returns:

```
\n
\n
On <localized date>, <name> <<email>> wrote:
> <line 1>
> <line 2>
> 
> <line 3>
…
```

Details:

- **Top-posting only**: two blank lines first for the user's reply
  space, then the attribution line, then the quoted body. Cursor
  position is the SPA's concern (textarea autofocus + cursor at
  position 0 via JS).
- **Attribution date**: pulled from `parent.temp_email.date_sent`,
  formatted as `Mon, May 28, 2026 at 9:32 AM` (Python `strftime`
  `%a, %b %-d, %Y at %-I:%M %p`).
- **Name + email**: `parent.temp_email.from_email`, parsed via
  `parse_email_address`. When no display name was captured,
  attribution reads `<email> wrote:` (one less angle-bracket pair).
- **Quoted body source**: `parent.temp_email.text_body`. Each line is
  prefixed with `> ` (including blank lines, which become bare `> `,
  matching the standard mail-client convention so the visual gap
  survives reply chains).
- **No body cached**: `text_body` is empty (purged from cache or an
  HTML-only inbound). Attribution still renders, followed by a single
  `> (original message unavailable)` line. The reply is still
  threadable; the user types whatever they want above.
- **Already-quoted parent**: if `text_body` contains `> ` lines from a
  previous reply chain, those get re-prefixed (`> > line` etc.) —
  standard mail-client behavior, preserves the threading.

### 2.7 `OutboundEmailService.send_tracked` extension

Add two optional keyword parameters:

```python
def send_tracked(
    *, to, subject, body, cc=None, bcc=None,
    attachments=None, associate_with=None,
    in_reply_to=None, references=None,    # NEW
) -> EmailRecord:
```

Behavior on the SMTP side: when `in_reply_to` is non-empty, set the
outgoing message's `In-Reply-To` header to that value. When
`references` is non-empty, set `References` similarly. Both headers go
through `EmailMessage.extra_headers` alongside the existing
Message-ID setter.

Behavior on the persistence side: when `in_reply_to` / `references`
are non-empty, write them onto the new outbound `TempEmail` row (the
columns already exist from the inbound-correlation work in
`docs/plans/2026-05-29-outgoing-email-and-reply-tracking-design.md`).
This means an outbound reply's `TempEmail` records its own thread
context, exactly like an inbound row.

Backwards-compatible: the document-send paths
(`EstimateEmailService`, `PurchaseOrderEmailService`,
`InvoiceEmailService`) pass neither parameter and behave unchanged.

### 2.8 Association inheritance

The reply POST builds `associate_with` for `send_tracked` from the
client's `inherit_associations` payload. Picks the first non-null FK
in priority order Job → PurchaseOrder → Bill (`send_tracked`'s
`associate_with` is a single-target dict). When all three are null
(parent was unassociated), `associate_with=None` and the reply lands
unassociated; the next IMAP fetch will auto-correlate the *next*
inbound reply via the standard `correlate_reply` pass.

Note on shape: `send_tracked` is single-target by current design.
Inheriting all three FKs at once would require either a
multi-target call or three sequential calls; the brainstorm
concluded inheriting the highest-priority FK is enough for the
correlate_reply pattern to keep working transitively. If two of the
three are set on the parent, the reply only inherits Job, but a
subsequent customer reply to *that* reply will pick the same Job up
via In-Reply-To matching, and the user can manually add the PO/Bill
association via the action panel if needed.

## 3. `{object_url}` placeholder (stub)

### 3.1 Configuration key

New key `our_public_url` (default `https://example.com`). Single
global value until tenancy lands (same pattern as `our_domain`).

### 3.2 Template variable

The shared template variable set (per-document-type, used by the
Estimate / PO / Invoice send services) gains `{object_url}`,
resolved per document type:

| Document type | Resolution |
|---|---|
| Estimate | `{our_public_url}/estimates/{estimate.estimate_id}` |
| PO | `{our_public_url}/purchase-orders/{po.po_id}` |
| Invoice | `{our_public_url}/invoices/{invoice.invoice_id}` |

These URLs **do not actually work** for unauthenticated customers
today. They're placeholders so user-authored boilerplate can include
"Click here to view: {object_url}" against a sensible-looking URL
shape, and the resolution flips to a real signed token URL when the
public URL feature lands.

### 3.3 LATER.md entry

New entry describing the deferred public URL feature: a customer-
facing view-accept-reject surface per document type, signed-token
auth, the eventual swap of the `{object_url}` resolver to produce
real public URLs.

## 4. Cleanup: collapse to a single outbound entry point

After the Reply composer ships, `OutboundEmailService.send_email`
has these callers:

| Caller | Status |
|---|---|
| `OutboundEmailService.send_tracked` | Internal — should inline the EmailMessage construction |
| `apps/core/views.py:compose_email` | Deprecated Django HTML view, no SPA caller |
| `apps/qbo/services.py:QBOInvoiceSyncService._send_email` | Called only by the legacy `push_invoice` path, which is no longer reachable from the SPA (removed in Phase G of the outgoing-email work) |

Cleanup tasks:

### 4.1 Delete the deprecated `compose_email` HTML view

- Remove `compose_email` view function from `apps/core/views.py`.
- Remove the URL `apps/core/urls.py:14` (`path('compose/', …)`).
- Delete `templates/core/compose_email.html`.
- Remove any sidebar / dashboard links to `/core/compose/` (a quick
  grep before deleting will confirm).

The SPA's email work (the Reply composer in this spec; the
document-send pages in the prior spec) is the durable replacement.

### 4.2 Delete the orphaned QBO push_invoice path

- Delete `QBOInvoiceSyncService.push_invoice` and
  `QBOInvoiceSyncService._send_email`. (The class itself stays —
  `_build_qbo_invoice`, `_mark_as_sent`, and `_download_qbo_pdf` are
  used by `InvoiceEmailService.send_invoice`.)
- Delete the `QBOInvoicePushTest`, `IndividualContactInvoicePushTest`
  classes in `tests/test_qbo_invoice_push.py`. The
  `InvoiceQBOFieldsTest` class is independent and stays.

### 4.3 Inline `send_email` into `send_tracked`; delete `send_email`

- Move the `EmailMessage` construction (the body of the current
  `send_email`) directly into `send_tracked` where it calls SMTP.
  Roughly five lines: `EmailMessage(subject, body, from_email, to,
  cc, bcc)`, set `extra_headers['Message-ID']`, optionally set
  `extra_headers['In-Reply-To']` and `extra_headers['References']`,
  loop `msg.attach(...)`, call `msg.send()`.
- Remove `OutboundEmailService.send_email` from
  `apps/core/services.py`.
- Update `tests/test_outbound_email.py` — the existing
  `OutboundEmailServiceTest` class (covers the low-level
  `send_email`) goes away. The `SendTrackedTest` and downstream
  tests already cover the SMTP integration; no coverage gap.

## 5. Tests

- **`tests/test_email_utils.py`** — new test class
  `BuildReplyBodyTest` covering: standard quoted-original output,
  empty parent text_body (the placeholder line), already-quoted
  parent (re-prefixing), missing display name (single-angle-bracket
  attribution), and the date formatting.
- **`tests/test_email_utils.py`** — new test class
  `BuildReplySubjectTest` covering: bare subject (`X → Re: X`),
  single-Re prefix (`Re: X → Re: X`), repeated-Re (`Re: Re: Re: X → Re: X`),
  Fwd mixed with Re (`Re: Fwd: X → Re: X`), empty subject (`→ Re: (no subject)`).
- **`tests/test_outbound_email.py`** — extend `SendTrackedTest` to
  cover `in_reply_to` / `references` flowing through to both the
  outgoing message headers and the persisted `TempEmail`.
- **`tests/test_api_email.py`** — new endpoint tests:
  - `reply-defaults` returns the expected shape (to/cc/bcc, subject
    Re-prefixed, body with quoted original, in_reply_to /
    references / inherit_associations).
  - `reply-defaults` for a parent with no `text_body` returns the
    placeholder body.
  - `reply-defaults` 404 for unknown email.
  - `reply` happy path: creates an outbound EmailRecord linked to
    the parent's Job (or PO/Bill); sets in_reply_to / references
    headers on the outbound TempEmail; navigates back.
  - `reply` accepts uploaded attachments.
  - `reply` for a parent with no associations leaves the outbound
    unassociated.
  - `reply` 400 on missing `to`.
  - `reply` 502 on SMTP failure with the outbound row showing
    `last_send_error`.
- **Template rendering** — the `{object_url}` resolution is unit-
  tested via the existing template variable plumbing per document
  type (one assertion per document type that `{object_url}` resolves
  to the expected URL shape).
- **SPA** — no JS test runner; manual verification:
  - Reply button visible on the email detail page above the Job
    section in the action panel; navigates to the reply page.
  - Reply page prefills the form correctly (To, Subject `Re: `,
    body with quoted original visible below cursor).
  - Submit returns to email detail, where the new outbound row shows
    in the Job overview Email panel with the `→` direction glyph.
  - When the customer replies to our outbound, the inbound that
    arrives auto-correlates back to the same Job
    (`correlate_reply` already does this — verifies end-to-end).

## 6. Files touched

| File | Change |
|---|---|
| `apps/core/email_utils.py` | New `build_reply_body`, `build_reply_subject` helpers |
| `apps/core/email_templates.py` | New variable in the resolved set: `object_url` (per document type) |
| `apps/core/services.py` | `send_tracked` gains `in_reply_to` / `references` kwargs; `EmailMessage` construction inlined; `send_email` deleted |
| `apps/api/email/views.py` | New `reply_defaults`, `reply` view functions |
| `apps/api/email/urls.py` | Two new paths |
| `apps/core/views.py` | Delete `compose_email` view |
| `apps/core/urls.py` | Delete `/compose/` route |
| `templates/core/compose_email.html` | **Deleted** |
| `apps/qbo/services.py` | Delete `QBOInvoiceSyncService.push_invoice` and `_send_email` |
| `apps/estimates/services.py` | `get_email_defaults` extends the value dict with `object_url` |
| `apps/purchasing/services.py` | Same |
| `apps/invoicing/services.py` | Same |
| `frontend/src/components/email/EmailActionPanel.svelte` | New Reply section at top of the rail |
| `frontend/src/routes/email/EmailReplyPage.svelte` | **New** |
| `frontend/src/App.svelte` | Register the new route |
| `frontend/src/lib/email.js` | New `replyDefaults(id)`, `reply(id, formData)` methods |
| `tests/test_email_utils.py` | `BuildReplyBodyTest`, `BuildReplySubjectTest` |
| `tests/test_outbound_email.py` | Extend `SendTrackedTest` for `in_reply_to`/`references`; delete `OutboundEmailServiceTest` |
| `tests/test_qbo_invoice_push.py` | Delete `QBOInvoicePushTest`, `IndividualContactInvoicePushTest` |
| `tests/test_api_email.py` | New endpoint-coverage tests for reply |
| `docs/designs/LATER.md` | Public URL feature entry |

## 7. Docs to update post-implementation

- `docs/designs/architecture-and-conventions.md` §7 — add a §7.13
  describing the reply composer (the route, the prefill computation,
  the In-Reply-To / References plumbing), and note in §7.10 that
  `send_tracked` is now the only outbound entry point (delete the
  parenthetical about `send_email`).
- `docs/designs/data-constraints.md` — no change (the
  TempEmail.in_reply_to / references columns are already documented).
- `docs/designs/users-and-permissions.md` — add the two new endpoints
  to the endpoint→atom table (both `IsAuthenticated`, no atom).

## 8. Future work / explicitly deferred

1. **Customer-facing public URL feature.** A real `{object_url}`
   that customers can click to view (and, for Estimates, accept or
   reject) without a Minibini account. Needs signed tokens or
   per-document `public_token` columns, public read views per
   document type, and an accept/reject API surface. Whole separate
   spec when it's time. The `our_public_url` Configuration key here
   is the stub.

2. **Reply-All.** Replying to the original sender plus all original
   CCs. The reply composer's `CC` field is editable, so the user can
   paste them manually; auto-fill is the YAGNI.

3. **Forward.** Different prefill (no recipient, `Fwd:` subject,
   body becomes the quoted original, original attachments included).
   Worth doing eventually; not needed for reply-correlation parity
   with mail clients.

4. **Drafts.** Saved-but-unsent state for reply composition. Same
   answer as the document-send spec: no for v1, re-evaluate if
   actual complaints surface about SMTP failure + page reload
   losing composed content.

5. **Free-form new email composer.** Composing an outbound without
   an inbound parent. Explicitly dropped during brainstorming; the
   document-send paths and reply path cover what the user actually
   needs.

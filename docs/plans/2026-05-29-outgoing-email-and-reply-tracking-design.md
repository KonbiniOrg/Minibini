# Outgoing email + reply tracking — design spec

**Status:** Draft, ready for review.
**Date:** 2026-05-29
**Scope:** make outgoing email a first-class tracked artifact alongside
inbound email; add Estimate send (currently missing); retrofit the
existing PO and Invoice send paths onto the new tracking foundation;
add reply correlation so customer replies to our outbound emails
auto-link to the right Job / PO / Bill. Out of scope: reply composer
UI in the SPA (separate spec); sending outbound documents as replies
to the customer's most recent inbound email (future possibility,
captured in §13).

---

## 1. Problem

Outbound email is the missing half of our email subsystem. We have a
working inbound pipeline — IMAP fetch, EmailRecord persistence, the
right-rail action panel, Job-overview Email panel, three-way
associations to Job / PurchaseOrder / Bill. But on the outbound side:

- **POs** send via `PurchaseOrderEmailService.send_po` → SMTP. No
  EmailRecord row is created; the sent email vanishes from our records
  the instant it leaves the relay.
- **Invoices** send via `QBOInvoiceSyncService.push_invoice` → QBO
  push → QBO returns invoice PDF with Pay-Now link → Minibini sends
  both that PDF and a locally-generated Job Statement PDF via SMTP
  using a hardcoded subject and body. The user sees no compose surface
  and can't edit anything; the send fragment is a small dialog at the
  bottom of the Invoice detail page (`SendToQBODialog.svelte`).
- **Estimates** have no send mechanism at all. Users mark them `open`
  manually and presumably send them via Gmail outside the app.

Consequences:
- Outbound document emails don't show up in the Job overview Email
  panel, even though we built that panel with `direction='outbound'`
  in mind (it's been a hard-coded `'inbound'` stub waiting for
  real data).
- When a customer replies to a quote / invoice / PO we sent, there's
  nothing on our side that says "this incoming email is a reply to
  *that* one" — so the resulting EmailRecord lands unassociated and
  the user has to manually link it via the action panel.
- The "Mark Open" button on Estimates and the "Mark Sent" button on
  POs and Invoices exist because there's no real send action they can
  hang off of. They're a fiction — they let the user pretend the
  document was sent. Once we have a real send, they become a
  workaround we don't want.

## 2. Scope

In:

- New `EmailRecord.direction` column (currently a serializer stub).
- Persisting an outbound `EmailRecord` (+ a `TempEmail` for body
  caching) at send time for every email this system originates.
- A self-generated `Message-ID` set on every outbound message,
  persisted on the outbound `EmailRecord`.
- Reply correlation: at IMAP fetch time, for each newly-arrived email
  whose `In-Reply-To` or `References` headers point at one of our
  Message-IDs, auto-copy the parent's `job` / `purchase_order` /
  `bill` FKs onto the new EmailRecord.
- A shared full-page send UI used by all three document types
  (Estimate, PO, Invoice). Editable subject + body (template-driven),
  recipient, optional CC, attachments (auto-attached document PDF +
  user-added uploads, all removable).
- Configuration template keys per document type (mirroring the
  existing `po_email_*` pattern).
- Estimate PDF generation (new) and a new Estimate send service.
- Retrofit of PO send to route through the new shared shape; existing
  PO Configuration keys preserved.
- Retrofit of Invoice send: keeps the QBO push and dual-PDF dance,
  but the user sees the new compose surface and the button text drops
  the "to QuickBooks" lie. Also: a bug fix where retries after SMTP
  failure currently re-push to QBO and create duplicates.
- Removal of "Mark Open" (Estimate) and "Mark Sent" (PO, Invoice)
  buttons from their detail pages.
- `Send` button on each document detail page transitions the document
  status as part of the send-success path (Estimate `draft → open`,
  PO `draft → issued`, Invoice `draft → open`).

Out:

- **Reply composer UI** — a free-form compose surface for sending
  arbitrary outbound replies. Separate spec; will sit on the email
  detail page and re-use most of the foundation introduced here.
- **Drafts.** Outbound EmailRecords are either successfully-sent
  (`sent_at` set) or last-send-failed (`sent_at` null, `last_send_error`
  populated). No saved-and-not-yet-attempted state. If the page
  reloads before the user clicks Send, the composed content is lost —
  acceptable tradeoff, can revisit later if real complaints surface.
- **Sending outbound as a reply** to the customer's most recent
  inbound thread. Worth doing eventually for thread continuity in the
  customer's inbox, but the user explicitly wants the option to send a
  *new* email so we don't build the alternative form now. §13.

## 3. Data model changes

### 3.1 `EmailRecord` additions

```python
class EmailRecord(models.Model):
    INBOUND = 'inbound'
    OUTBOUND = 'outbound'
    DIRECTION_CHOICES = [(INBOUND, 'Inbound'), (OUTBOUND, 'Outbound')]

    direction = models.CharField(
        max_length=10, choices=DIRECTION_CHOICES, default=INBOUND,
    )
    sent_at = models.DateTimeField(null=True, blank=True)
    last_send_error = models.TextField(blank=True, default='')
    # job, purchase_order, bill, message_id, created_at — unchanged
```

Semantics:

- `direction='inbound'`, `sent_at=null` — current behavior, IMAP-fetched
  email. The migration backfills every existing row to `inbound`.
- `direction='outbound'`, `sent_at` set — a successfully-sent outbound.
- `direction='outbound'`, `sent_at` null, `last_send_error` populated —
  an outbound whose SMTP attempt failed; visible as a "needs retry"
  state on the source document page.
- `direction='outbound'`, `sent_at` null, `last_send_error` empty —
  a transient state during the SMTP call; should never persist beyond
  a single request.

One migration adds the three columns. Existing `EmailRecord` rows
backfill to `inbound` / `sent_at=null` / `last_send_error=''`.

`message_id` already exists with `unique=True, db_index=True`. We set
it explicitly on outbound rows to a self-generated value:
`<minibini-<uuid4-hex>@<our-domain>>`. The `<our-domain>` comes from
the `our_domain` Configuration key (see §3.3); `EMAIL_HOST_USER` is
deliberately *not* used as a source — it's the IMAP/SMTP provider
credential (gmail.com or similar), not the tenant's identity. When
tenancy lands, `our_domain` becomes per-tenant; until then it's a
single global Config value.

### 3.2 `TempEmail` for outbound

Outbound emails get a `TempEmail` row populated at send time, so the
Email panel and email detail page render them through exactly the same
code paths as inbound (subject, from, to, cc, body, attachment list).
The existing fields cover everything we need:

| Field | Outbound semantics |
|---|---|
| `subject` | The rendered, possibly-edited subject |
| `from_email` | Our `EMAIL_HOST_USER` |
| `to_email` | Comma-separated recipients (the form's `To`) |
| `cc_email` | Comma-separated CC (the form's `CC`) |
| `bcc_email` | New field needed — see below |
| `date_sent` | Set to `now()` at send time |
| `text_body` / `html_body` | The composed body, plain text only (we don't generate HTML) |
| `attachments_metadata` | `[{filename, content_type, size}, …]` |
| `has_attachments` | Bool derived from `attachments_metadata` |
| `uid` | Empty for outbound — no IMAP UID exists |

`bcc_email` is **not** currently on `TempEmail` (today's IMAP inbound
flow can't see BCC). Add it as a blank-default TextField — used only
when populating outbound rows. Existing inbound rows leave it empty.

### 3.3 Configuration keys

Mirroring the existing `po_email_subject_template` /
`po_email_body_template` shape:

| Key | Default |
|---|---|
| `estimate_email_subject_template` | `Estimate {estimate_number} from {our_business_name}` |
| `estimate_email_body_template` | `Hi {contact_fname},\n\nPlease find attached our estimate {estimate_number} for {job_name}. Let us know if you have any questions.\n\nThanks,\n{our_user_name}` |
| `po_email_subject_template` | (existing, unchanged) |
| `po_email_body_template` | (existing, unchanged) |
| `invoice_email_subject_template` | `Invoice {invoice_number} for {job_number}` |
| `invoice_email_body_template` | `Hi {contact_fname},\n\nPlease find attached your invoice {invoice_number} for {job_name}. The invoice includes a Pay Now link.\n\nThanks,\n{our_user_name}` |
| `our_domain` | Identifies *us* as the tenant for `Message-ID` generation. Default: `example.com`. The current single-tenant default is the placeholder until a real tenancy system lands and this becomes per-tenant. Not derived from `EMAIL_HOST_USER` — that's an IMAP credential, unrelated to our identity. |
| `our_business_name` | Used in subject templates and (later) outbound signatures. Defaults to `''`. |

All settable from the Settings page; defaults shown above are used
when the Config row is missing (graceful fallback, matching the
existing PO pattern).

## 4. `OutboundEmailService` and the outbound EmailRecord lifecycle

### 4.1 Today

`apps/core/services.py:OutboundEmailService.send_email(to, subject,
body, cc=None, bcc=None, attachments=None, from_email=None)` — a thin
wrapper around `django.core.mail.EmailMessage.send()`. Fire-and-forget;
no persistence.

### 4.2 New responsibility

`send_email` (or a new sibling — see below) becomes the single point
that persists outbound state. The flow:

1. **Generate** a `Message-ID` (`<minibini-<uuid4-hex>@<outgoing_email_domain>>`).
2. **Create** the `EmailRecord` with
   `direction='outbound'`, the generated `message_id`, the
   association FKs the caller specified (`job=…` / `purchase_order=…`
   / `bill=…`), `sent_at=None`, `last_send_error=''`. Same transaction:
   create the `TempEmail` with the message metadata + body +
   `attachments_metadata` (computed from the attachments tuples).
3. **Attempt SMTP.** Set the outgoing `EmailMessage.extra_headers['Message-ID']`
   to the generated value before `.send()`. (Django's `EmailMessage`
   otherwise lets the SMTP server pick a `Message-ID` for us, which we
   wouldn't know in advance.)
4. **On success:** set `sent_at=now()`, clear `last_send_error`, save.
5. **On failure:** save the exception message into `last_send_error`,
   leave `sent_at=None`, re-raise so the caller surfaces the error to
   the user.

Caller-facing shape (a new method, leaving the existing
`send_email` in place for non-document outbound that doesn't need
tracking):

```python
@staticmethod
def send_tracked(
    *, to, subject, body, attachments=None, cc=None, bcc=None,
    associate_with=None,    # {'job': job} | {'purchase_order': po} | {'bill': bill} | None
) -> EmailRecord:
    """Create an outbound EmailRecord + TempEmail, attempt SMTP,
    persist outcome. Returns the EmailRecord regardless of send
    success; the caller inspects sent_at / last_send_error."""
```

`associate_with` is an optional dict of at most one of the three
target keys. The caller passes whichever applies to the document
being sent. The new outbound EmailRecord inherits the FK at creation
time; the existing parameterized `EmailService.associate_with` is not
involved (we're setting the FK at INSERT, not via a separate UPDATE).

### 4.3 Retry semantics

Re-clicking Send on a document whose previous attempt failed:

- Finds the most recent `direction='outbound'`, `sent_at=null`
  EmailRecord tied to the document (via the appropriate FK).
- Reuses it (does not create a new row).
- Preserves `message_id` from the failed row — so if attempt 1
  partial-delivered somehow, the `In-Reply-To` chain stays coherent.
- Updates `text_body` / `subject` / `to_email` / `cc_email` / `bcc_email`
  from the current form POST — the user may have edited any of them
  between attempts.
- **Regenerates the document PDF from current state.** PDFs are not
  cached — every send attempt rebuilds them from the document. If the
  document was edited between attempt 1 (failed) and attempt 2, the
  retry sends the current content. SMTP failures don't actually
  deliver, so this is correct behavior, not a content-mismatch
  hazard. User-uploaded attachments come from the multipart POST the
  SPA sends each time.
- For Invoice: if `qbo_id` is set, skip the QBO push and reuse it
  (the §4.4 short-circuit). Always re-fetch the QBO PDF and
  regenerate the statement PDF — same regenerate-from-current-state
  principle.
- Attempts SMTP again. Success / failure handling as in §4.2.

If the user navigates away from the send page after a failure, the
form's composed body and attachments are lost (no drafts; §2). The
document detail page surfaces a "Last send failed: <error>"
indicator with a Send Email button that takes the user back to a
freshly-template-loaded send page. The server still finds the stale
EmailRecord by FK on the next send, so `message_id` is preserved
even across navigations.

PDF byte preservation (archival — "show me what I sent the customer
three months ago") is a separate concern from retry, not in scope
here. The document data model freezes once the doc is accepted /
issued / paid, so the bones are recoverable; the exact rendered
bytes are not.

### 4.4 Invoice-specific Send shim

`QBOInvoiceSyncService.push_invoice` becomes a coordinator:

1. **Short-circuit on retry.** If `invoice.qbo_id` is already set, skip
   the QBO push step entirely (fixes the existing
   duplicate-push-on-retry bug). Proceed directly to PDF regeneration.
2. **Push to QBO** (if not already pushed). Save `qbo_id`. Mark sent in
   QBO.
3. **Generate/fetch the two PDFs** (QBO invoice PDF, local job
   statement PDF). The QBO PDF fetch always runs because QBO's rendered
   output may have been changed by the push or by re-fetch.
4. **Send via** `OutboundEmailService.send_tracked` with
   `associate_with={'job': invoice.job}`. The composed subject and
   body come from the SPA form; the two PDFs are auto-attached
   (alongside any user uploads).
5. **On full success**, transition `invoice.status` if it was `draft`.

QBO step failures and SMTP failures surface as distinct error
messages on the document page so the user knows which one to retry.

## 5. Inbound reply correlation

### 5.1 Header capture

`TempEmail` gains two more columns:

| Field | Notes |
|---|---|
| `in_reply_to` | CharField (max 255, blank). Pulled from `msg.headers['in-reply-to']` at fetch time. The full bracketed token. |
| `references` | TextField (blank). Pulled from `msg.headers['references']`. Space-separated chain. |

Both are populated by `EmailService.fetch_new_emails` and
`fetch_emails_by_date_range` alongside the existing `text_body` /
`html_body` / `attachments_metadata` writes. Backfilled rows have
empty strings.

### 5.2 The correlation pass

A new helper, `EmailService.correlate_reply(email_record)`, runs once
per newly-created inbound EmailRecord at the end of the fetch loop:

1. Collect candidate parent `message_id`s: the `in_reply_to` (if set),
   plus every space-separated token in `references` (each may be a
   `<bracketed>` Message-ID).
2. Strip surrounding whitespace and angle brackets, then look up any
   `EmailRecord` with a matching `message_id`. Walk newest-first
   (probably just take the first match — `in_reply_to` if it resolves,
   otherwise the right-most match in `references`).
3. If a parent EmailRecord is found, copy its non-null
   `job_id` / `purchase_order_id` / `bill_id` onto the new
   EmailRecord and `save()`. If multiple parents matched and they
   disagree on associations, the immediate parent (`in_reply_to`)
   wins.

The auto-link is implicit and silent — no "auto-linked via reply"
badge on the action panel. (We considered this and ruled it out:
a human reads every email anyway, the existing Disassociate +
relink mechanic handles miscategorization, and the visual noise
isn't worth the rare correctness gain.)

A reply-to-a-reply-to-… chain works naturally because the original
parent's associations were already copied to its child when *that*
arrived; the grandchild copies them from the child.

### 5.3 What doesn't correlate

- **Forwards.** Most clients don't preserve `In-Reply-To` on a forward.
  These land unassociated; the user manually links them via the
  action panel. We do **not** add subject-line parsing as a fallback
  in this spec — keep the correlation behavior small and explicit.
  If it turns out we miss enough forwarded replies to be annoying,
  a fallback that scans subjects for our outbound document numbers
  (`EST-2026-0001`, `PO-…`, `INV-…`) is a focused follow-up.
- **Replies where the client stripped `In-Reply-To`** (rare). Same
  story.
- **Out-of-band correspondence** the customer sends from an unrelated
  address. Same.

## 6. The shared Send page

Three new SPA routes, one per document type, all using the same
shared component:

| Route | Component |
|---|---|
| `/estimates/:id/send` | `EstimateSendPage.svelte` |
| `/purchase-orders/:id/send` | `PurchaseOrderSendPage.svelte` |
| `/invoices/:id/send` | `InvoiceSendPage.svelte` |

Each is a thin wrapper that fetches the document, computes recipient
defaults, fetches the rendered subject + body (server-side
template-resolution; see §7), and mounts a shared
`DocumentSendForm.svelte` component plus a read-only rendering of
the document below.

### 6.1 Layout

```
[minimal header]   — see §6.4 below

<DocumentSendForm>
  To:            [text input, editable, prefilled from recipient defaults]
  CC:            [text input, blank by default; comma-separated]
  BCC:           [text input, blank by default; comma-separated]
  Subject:       [text input, prefilled from template]
  Body:          [textarea, ~12 rows, prefilled from template]
  Attachments:
    [filename]   [×]   ← auto-attached document PDF (removable)
    [filename]   [×]   ← (Invoice only) statement PDF (removable)
    [+ Add attachment]
  [Send Email]   [Cancel]
</DocumentSendForm>

────────────────────────────────────

[Document content rendered below — same component the detail page uses,
in read-only mode. Scrolls under the form.]
```

### 6.2 Send action

`Send Email` triggers a confirm dialog ("Send this email to <to>?")
then POSTs to the document-specific send endpoint (§7). On success,
navigates back to the document detail page; the detail page reflects
the new status and shows the sent EmailRecord in its associated-email
list. On failure, the error message renders inline on the send form
and the form keeps the user's composed content so they can retry
without re-keying.

### 6.3 Confirm dialog

Native `confirm()` is fine for v1 — keeps with how Disassociate works
in the action panel. The message includes the recipient so users
catch wrong-To slips.

### 6.4 Minimal header

These pages are transitional, not destinations. The header treatment
should signal "you came here to do one thing; finish it or cancel."
Concretely: no document header at the top (no status pills, no
status-change buttons, none of the navigation that a destination page
would have), just a breadcrumb back-link to the parent document. If
the existing Invoice Wizard route (`/invoices/:id/wizard`) has a
transitional-header treatment we can match, we adopt it; otherwise
we define the minimal shape here and the wizard can harmonize later.
Refinement based on usage is fine — the spec just commits to
"different from a destination page."

### 6.5 Attachment upload

The SPA POSTs the send as `multipart/form-data`. The backend collects
the file blobs alongside the form fields, assembles them into the
`(filename, content, mime_type)` tuples that
`OutboundEmailService.send_tracked` expects, and includes them
alongside the document-PDF auto-attachments. No size pre-check; SMTP
will surface any size-limit failure (commonly 25 MB total).

### 6.6 Recipient defaults

- **Estimate.** `Job.contact.email`.
- **PO.** `PO.contact.email` if set, else `PO.business.default_contact.email`.
- **Invoice.** `Invoice.job.contact.email`.

Any of these can be empty (contact has no email on file). In that
case the To field is blank and the Send button is disabled until the
user fills it in.

### 6.7 Permissions

| Action | Atom |
|---|---|
| Estimate send | `can_manage_jobs` (estimates live under jobs) |
| PO send | `can_manage_financials` |
| Invoice send | `can_manage_financials` |

The Send button is hidden on the document detail page when the
viewer lacks the relevant atom.

## 7. Per-document send endpoints

Three new endpoints, one per document type. They all share the same
body shape and same template-rendering preparation step, but the
status-transition and attachment-assembly logic is per-document.

| Endpoint | Body | Auto-attachments | Status transition on success |
|---|---|---|---|
| `POST /api/estimates/{id}/send/` | `{to, cc, bcc, subject, body}` + multipart files | `Estimate-{number}.pdf` | `draft → open` |
| `POST /api/purchase-orders/{id}/send/` | same | `PurchaseOrder-{number}.pdf` | `draft → issued` |
| `POST /api/invoices/{id}/send/` | same | QBO invoice PDF + Job Statement PDF | `draft → open` (plus QBO push if `qbo_id` unset) |

All three call `OutboundEmailService.send_tracked` with
`associate_with` populated as appropriate. The status transition fires
inside the same transaction as the EmailRecord creation, so a
mid-flow failure doesn't leave the document in an inconsistent state.

A pre-load endpoint per document is also needed so the page can
render template-resolved defaults before the user edits anything:

| Endpoint | Returns |
|---|---|
| `GET /api/estimates/{id}/send-defaults/` | `{to, subject, body, attachments_preview: [{filename, content_type, size}]}` |
| `GET /api/purchase-orders/{id}/send-defaults/` | same |
| `GET /api/invoices/{id}/send-defaults/` | same |

`attachments_preview` lets the form render the auto-attachment list
without generating the PDF twice (page load + send). The PDF is
actually generated server-side at send time, not at preview time.

## 8. Removed UI

These buttons come off:

- **Estimate detail page** — "Mark Open" button. The only legitimate
  reason to flip an Estimate from `draft → open` without sending is
  to drive the parent Job through state changes; that can be done by
  changing the Job's status directly. The Estimate status should
  reflect reality (we sent it or we didn't).
- **PO detail page** — "Mark Sent" button (existing
  `PurchaseOrderEmailService.send_po` already auto-issues, so the
  explicit button is partially redundant today; full removal goes
  with the new send page).
- **Invoice detail page** — the `SendToQBODialog.svelte` send fragment.
  Replaced entirely by the new send page; the dialog file is
  deleted. (Invoices don't have a separate "Mark Sent" button today —
  status flows through the wizard — so nothing else comes off here.)

## 9. Template variable resolution

A single helper resolves all templates:

```python
def render_email_template(template: str, *, document, contact, user) -> str:
    """str.format-style substitution. Unknown placeholders and null
    values render literally (no exception).
    """
```

Common variable set, applicable to all three document types:

| Variable | Source |
|---|---|
| `{contact_fname}` | `contact.first_name` |
| `{contact_lname}` | `contact.last_name` |
| `{contact_business}` | `contact.business.business_name` or blank |
| `{our_user_name}` | `user.first_name` |
| `{job_number}` | `document.job.job_number` (Estimate, Invoice) or blank (PO has no job FK) |
| `{job_name}` | `document.job.name` (same caveat) |
| `{document_number}` | `document.estimate_number` / `document.po_number` / `document.invoice_number` (generic, document-type-aware) |
| `{our_business_name}` | `Configuration['our_business_name']` |

Per-document additions (kept alongside `{document_number}` for
template portability):

- **Estimate:** `{estimate_number}` (alias of `{document_number}`).
- **PO:** `{po_number}`, `{vendor_name}` (existing — kept verbatim
  for backwards-compat with whatever PO Configuration values are
  already saved).
- **Invoice:** `{invoice_number}`.

Implementation: build a flat `dict` of all available variables for
the document at hand, then `template.format_map(SafeDict(values))`
where `SafeDict.__missing__` returns the original `{key}` literal
unchanged. (Standard recipe; no library needed.)

## 10. Tests

- **`tests/test_email_models.py`** — `EmailRecord` direction,
  `sent_at`, `last_send_error` round-trip; `TempEmail.bcc_email`,
  `in_reply_to`, `references` round-trip.
- **`tests/test_outbound_email.py` (extend existing)** —
  `OutboundEmailService.send_tracked` happy path (creates outbound
  EmailRecord, sets sent_at, attaches associations); SMTP failure path
  (sent_at stays null, last_send_error populated, exception re-raised);
  retry path (re-uses the failed EmailRecord, preserves message_id).
- **`tests/test_email_models.py` (service layer)** —
  `EmailService.correlate_reply` happy path (inbound with
  `In-Reply-To` matching an outbound copies the parent's FK); chain
  walk via `References`; no-parent-found no-op; multi-target parent
  (job + PO + bill all set) copies all three; conflicting parents
  prefer `In-Reply-To`.
- **`tests/test_api_invoicing.py` / `test_api_estimates.py` /
  `test_api_purchasing.py`** — send endpoints: happy path (status
  transitions, EmailRecord created, response shape), missing-To 400,
  permission gates, retry-after-failure path.
- **`tests/test_api_invoicing.py`** — Invoice send specifically:
  retry with `qbo_id` already set skips the QBO push (verifies the
  bug fix from §4.4).
- **SPA** — no JS test runner; manual verification:
  - Send page renders with prefilled fields; auto-attachment shows.
  - User can edit, add attachment, remove auto-attachment, send.
  - Confirm dialog fires with the recipient address.
  - SMTP failure surfaces an error and preserves composed content.
  - Document status updates on success.
  - Outbound EmailRecord shows up in the Job overview Email panel
    with the `→` direction glyph.

## 11. Files touched

| File | Change |
|---|---|
| `apps/core/models.py` | Add `EmailRecord.direction`, `sent_at`, `last_send_error`; `TempEmail.bcc_email`, `in_reply_to`, `references` |
| migration (auto) | The six column additions |
| `apps/core/services.py` | New `OutboundEmailService.send_tracked`; new `EmailService.correlate_reply`; `fetch_new_emails` / `fetch_emails_by_date_range` populate the new TempEmail columns + run the correlation pass |
| `apps/core/email_templates.py` (new) | `render_email_template` helper |
| `apps/api/email/serializers.py` | Make `direction` reflect real column instead of hardcoded `'inbound'` |
| `apps/estimates/pdf.py` (new) | `generate_estimate_pdf(estimate)` — mirror PO/invoice PDF patterns |
| `apps/estimates/services.py` | `EstimateEmailService` (analogous to `PurchaseOrderEmailService`) — `get_email_defaults(estimate)`, `send_estimate(estimate, to, subject, body, cc, bcc, attachments, user)` |
| `apps/purchasing/services.py` | Retrofit `PurchaseOrderEmailService.send_po` to route through `send_tracked` instead of directly calling `send_email`; keep its existing public signature |
| `apps/qbo/services.py` | Retrofit `QBOInvoiceSyncService.push_invoice` per §4.4 (qbo_id short-circuit + route through `send_tracked`) |
| `apps/api/estimates/views.py` | New `send`, `send_defaults` actions |
| `apps/api/purchasing/views.py` | New `send_defaults` action (`send` exists; align with new shape) |
| `apps/api/invoicing/views.py` | New `send`, `send_defaults` actions; remove `send-to-qbo` |
| `frontend/src/components/email/DocumentSendForm.svelte` (new) | Shared form |
| `frontend/src/routes/estimates/EstimateSendPage.svelte` (new) | |
| `frontend/src/routes/purchaseorders/PurchaseOrderSendPage.svelte` (new) | |
| `frontend/src/routes/invoices/InvoiceSendPage.svelte` (new) | |
| `frontend/src/components/invoices/SendToQBODialog.svelte` | **Deleted** |
| `frontend/src/App.svelte` | Register the three new send routes |
| `frontend/src/routes/estimates/EstimateDetailPage.svelte` | "Send Email" button; remove "Mark Open" |
| `frontend/src/routes/purchaseorders/PurchaseOrderDetailPage.svelte` | Confirm "Send Email" button; remove "Mark Sent" |
| `frontend/src/routes/invoices/InvoiceDetailPage.svelte` | Replace `SendToQBODialog` mount with "Send Email" link to the new page |
| `tests/test_email_models.py` | New model + correlation tests |
| `tests/test_outbound_email.py` | `send_tracked` tests |
| `tests/test_api_estimates.py` / `_purchasing.py` / `_invoicing.py` | Send-endpoint tests |

## 12. Docs to update post-implementation

- `docs/designs/architecture-and-conventions.md` §7 — add a subsection
  describing outbound EmailRecord tracking, the `direction` column, and
  the reply correlation pass.
- `docs/designs/data-constraints.md` §1.27 — extend `EmailRecord` to
  cover `direction`, `sent_at`, `last_send_error`; note the `TempEmail`
  additions in §1.27 or as a subsection.
- `docs/designs/estimates-and-prices.md` — add a section on Estimate
  send (PDF generation, status transition, template).
- `docs/designs/materials-inventory-and-purchasing.md` §PO email — note
  the routing-through-`send_tracked` change.
- `docs/designs/invoicing-and-expenses.md` — replace the QBO-send
  description with the new compose-and-send shape (QBO step preserved
  but de-emphasized).
- `docs/designs/users-and-permissions.md` — endpoint→atom table:
  three new send endpoints, three new send-defaults endpoints.

## 13. Future work / explicitly deferred

1. **Reply composer UI.** Free-form compose surface on the email
   detail page, for replying to arbitrary inbound emails. Builds on
   this spec's outbound tracking foundation. Drafts state may
   genuinely apply here. Separate spec.

2. **Send outbound documents as a reply to the customer's most recent
   inbound thread.** Technically straightforward — look up the latest
   `direction='inbound'` EmailRecord linked to the document's Job (or
   PO / Bill), set `In-Reply-To` and `References` on the outbound to
   thread to it. Improves customer-side thread continuity in Gmail
   etc. Deferred because the user wants the *option* to send a fresh
   email, and building both options + a toggle isn't worth it yet.
   When this lands it's probably a per-document Configuration toggle:
   "thread document emails into recent customer threads by default."

3. **Sent-folder upload via IMAP APPEND.** Pushing each successful
   outbound into the user's Sent folder so it shows in their normal
   mail-client UI (Gmail web, etc.) alongside replies they sent
   manually. Complementary to outbound tracking, not a replacement.
   Off the critical path for v1.

4. **Subject-line parsing fallback** for forwarded-rather-than-replied
   correlation. Only worth it if forwards turn out to be a noticeable
   miss rate.

5. **Outbound drafts** — saving a composed-but-not-sent send for
   later. Re-evaluate if real complaints surface about lost work from
   SMTP failures with the page reloaded.

6. **Error-message-display audit across the SPA** — captured
   separately in LATER.md. Will pick up the new send pages' error
   surfaces once that work runs.

7. **Tenancy and the `our_domain` / `our_business_name` Config keys.**
   Both keys are single-global values today (default `example.com`
   and `''` respectively) — placeholders until a real tenancy system
   lands. At that point they become per-tenant attributes pulled from
   the tenant's own setup configuration. The Message-ID generation
   and template rendering will both read from whatever the tenancy
   layer exposes instead of `Configuration.objects.get(...)`. No
   schema change in this spec anticipates that — the swap is
   internal to whoever resolves the keys.

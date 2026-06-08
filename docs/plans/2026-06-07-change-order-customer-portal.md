# Change Order Customer Portal

**Date:** 2026-06-07
**Branch:** feature/co-approval
**Status:** design (pre-implementation)

## 1. Problem & goal

Today an **Estimate** can be shown to a customer through a token-authorized,
login-not-required portal (`/portal/?token=…`). The customer can **accept**,
**reject**, or **request changes**; each decision drives the Estimate and its
Job through the right status transitions and notifies the shop.

A **ChangeOrder** (CO) — the amendment instrument that adjusts an already-accepted
agreement while a Job is `on_hold` — has *no* customer-facing surface. The shop
authors a CO, clicks "Mark as Sent" (a bare `draft → open` status flip with **no
email and no customer view**), and then has to relay the proposal and record the
customer's answer by hand (the CO detail page has internal "Record Accepted" /
"Record Rejected" buttons).

**Goal:** give a CO the same customer-facing treatment an Estimate has — a
token portal that displays the proposed change in a comparable manner and lets
the customer **accept / reject / request changes**, wired to the CO + Job
lifecycle and a shop notification. Stay **as parallel to the Estimate portal as
reasonably possible**, diverging only where the CO domain genuinely differs.

This is the follow-on to the change-order lifecycle work already on the branch
(see `docs/designs/estimates-and-prices.md` §14). It does **not** change CO
authoring, composition (`compose_agreement`), or the on_hold gate — only adds
the customer round-trip.

## 2. Background: the two existing systems

### 2.1 Estimate customer portal (the thing we're paralleling)

- **Token:** `Estimate.public_token` — `CharField(max_length=64, unique)`,
  minted once in `Estimate.save()` via `secrets.token_urlsafe(32)` when
  `not self.pk` (`apps/estimates/models.py:42-46, 110-117`).
- **API** (`apps/api/portal/`, registered at `/api/portal/`, all `AllowAny`,
  `authentication_classes([])`):
  - `GET  /api/portal/estimates/<token>/` → `build_estimate_payload`
  - `POST /api/portal/estimates/<token>/accept/`
  - `POST /api/portal/estimates/<token>/reject/` (body `{reason}`)
  - `POST /api/portal/estimates/<token>/request-changes/` (body `{reason}`)
- **Actionability** (`_is_actionable`): estimate is `open` **and** its job is
  `submitted`. Drafts 404. A click that races the shop (estimate closed, or job
  moved) is a silent no-op returning the refreshed payload.
- **Decisions:**
  - accept → `EstimateService.update_status(…, ACCEPTED)` → job `approved`
  - reject → `…update_status(…, REJECTED)` → job `rejected`
  - request-changes → `EstimateService.request_changes(pk, actor)`: writes a
    customer-action `HistoryEntry`, calls `revise_estimate` (new `draft` v+1,
    copies line items, parent → `superseded`, snapshots the parent's
    deliverables), then reverts job `submitted → draft`.
  - All decisions use `select_for_update`; on success, best-effort
    `EstimateEmailService.notify_shop_of_decision`.
- **Payload** (`build_estimate_payload`): `estimate_number`, `status`, dates,
  `deliverables[]` (frozen `DeliverableSnapshot` rows if present, else live job
  deliverables), `line_items[]` (`description/qty/units/price/amount`),
  `grand_total`, `actions[]`, `actionable`, `closed_message`, and
  `current_token` when `superseded` (forward link to the latest non-draft
  version).
- **Frontend:** separate Vite entry `frontend/portal/index.html` →
  `portal-main.js` → `PortalApp.svelte`, mounted on `#portal`. Reads
  `?token=` from the query string, renders read-only doc + confirm dialogs,
  POSTs decisions. Served statically at `/portal/` (no Django route).
- **Link delivery:** `EstimateEmailService.send_estimate` emails a PDF plus the
  portal link. `build_object_url('estimate', id)` →
  `<base>/portal/?token=<token>` (`apps/core/email_templates.py:46-70`), where
  `<base>` is Configuration `our_public_url`.

### 2.2 Change Order (the thing we're surfacing)

- `ChangeOrder` (`apps/estimates/models.py:207-284`, `db_table='change_orders'`,
  `@history`): `job` (CASCADE), `estimate` (PROTECT, the accepted estimate it
  amends), `change_order_number` (`{estimate_number}-CO{N}`), `status` (same six
  constants as Estimate), `created/sent/closed/expiration_date`,
  `version`/`parent` (reserved). **No `public_token` yet.**
- **Status machine** (`ChangeOrder.VALID_TRANSITIONS`): `draft → open|rejected`;
  `open → accepted|rejected|superseded|expired`; the four terminals. `save()`
  sets `sent_date`/`expiration_date` on entry to `open` (Configuration
  `est_expire_days`, default 30) and `closed_date` on terminals. `clean()`
  blocks `draft → open` with no line items.
- **Line items** `ChangeOrderLineItem` (`db_table='co_li'`): `action` ∈
  `add|remove|replace`; `target_line_item` → `EstimateLineItem` (required for
  remove/replace, null for add).
- **Service** `ChangeOrderService` (`apps/estimates/change_order_service.py`):
  `create` (job must be `on_hold` + have an accepted estimate; snapshots the
  prior agreement), `update_status` (**accepted** → job `on_hold → approved` +
  system `HistoryEntry`, no Task/Material mutation; **rejected/expired** →
  snapshot proposal, job stays `on_hold`), `mark_open`, `seed_new` (copy line
  items into a fresh draft with `parent` set), `discard_draft`, line-item ops.
- **Composition:** `compose_agreement(job)` = accepted estimate's line items with
  each accepted CO's deltas applied in acceptance order.
- **Internal SPA:** `frontend/src/routes/change-orders/ChangeOrderDetailPage.svelte`
  renders a merged baseline-vs-proposal diff (line items keyed off the accepted
  estimate's lines + the CO's `add/remove/replace`, deliverables off the
  `deliverables-baseline` endpoint) with shop-side action buttons.
- **Auto-expiry:** `mark_change_orders_expired` mirrors `mark_estimates_expired`;
  job stays `on_hold` after expiry.
- **Known gap (LATER):** "No CO PDF generation or email service yet." This work
  closes the email/customer-view half of that gap (PDF stays deferred).

## 3. Design

### 3.1 Token on ChangeOrder

Add `public_token` to `ChangeOrder`, identical to `Estimate`:

```python
public_token = models.CharField(max_length=64, null=True, blank=True, unique=True)
```

Mint it once in `ChangeOrder.save()` at creation:

```python
if not self.pk and not self.public_token:
    self.public_token = secrets.token_urlsafe(32)
```

(Put the mint **before** the existing `if self.pk:` branch, same as `Estimate`.)
Per-row, so a `seed_new` revision gets its own token. New migration in
`apps/estimates/migrations/`. `makemigrations` only — the human runs `migrate`.

### 3.2 Portal API — CO endpoints

New module siblings in `apps/api/portal/` (keep the package focused on the
customer surface). All `AllowAny`, `authentication_classes([])`, mirroring
`portal/views.py`:

- `GET  /api/portal/change-orders/<token>/` → `build_change_order_payload`
- `POST /api/portal/change-orders/<token>/accept/`
- `POST /api/portal/change-orders/<token>/reject/`        (body `{reason}`)
- `POST /api/portal/change-orders/<token>/request-changes/` (body `{reason}`)

Add the four routes to `apps/api/portal/urls.py` (names
`portal-change-order`, `…-accept`, `…-reject`, `…-request-changes`).

**Actionability** (the CO analog of `_is_actionable`):

```python
def _co_is_actionable(co):
    # Customer may act only on an OPEN CO whose job is still awaiting them.
    # An open CO is authored & sent while the job is on_hold and stays on_hold
    # until the customer accepts (then it goes approved). So "awaiting customer"
    # == job on_hold. Gate on both so a shop action that races the click no-ops.
    if co.status != ChangeOrder.STATUS_OPEN:
        return False
    return co.job_id is not None and co.job.status == Job.STATUS_ON_HOLD
```

**Decisions** (mirror `_decide` / `portal_estimate_request_changes`, each under
`select_for_update`, acting only when actionable, refreshing and returning the
payload, best-effort shop notify after commit):

- accept → `ChangeOrderService.update_status(pk, ACCEPTED)` (job `on_hold →
  approved`, **system** HistoryEntry — already implemented)
- reject → `ChangeOrderService.update_status(pk, REJECTED)` (snapshot proposal,
  job stays `on_hold` — already implemented)
- request-changes → `ChangeOrderService.request_changes(pk, actor)` (new — §3.3)

**Customer HistoryEntry — record it for *every* decision.** `update_status`
takes no actor and reject writes **no** history at all; accept writes only a
*system*-attributed entry (`_handle_accepted`,
`change_order_service.py:130-142`). The estimate portal, by contrast, records a
*customer*-attributed entry for every decision via `update_status(actor=…)`. To
reach parity, the **portal view records the customer-action HistoryEntry itself**
(`entry_type='action'`, `object_type='change_order'`, `user=None`,
`changes={'_action': 'Accepted/Declined via customer link', 'contact_id', 'customer_email'}`,
`text=reason`) for **accept and reject** — exactly as the estimate
`request-changes` view records its own entry. (request-changes records its entry
inside `ChangeOrderService.request_changes`, §3.3.) Factor a small
`_record_customer_action(co, action_label, actor)` helper in the portal module.

A token that doesn't resolve, or a CO in `draft`, 404s (`_not_available`),
matching the estimate rule that drafts are never portal-visible.

### 3.3 `ChangeOrderService.request_changes(pk, actor)`

The CO parallel of `EstimateService.request_changes`. The estimate version
makes a new draft revision and bounces the job back to `draft` so the shop
resumes editing. For a CO the job is **already** `on_hold` (the CO editing
room), so the parallel is: supersede the open CO and seed a fresh draft CO for
the shop to revise — the job needs no status change, and the on_hold exit guard
keeps the job parked until the new draft is resolved.

```python
@staticmethod
@transaction.atomic
def request_changes(pk, actor):
    co = ChangeOrder.objects.select_for_update().get(pk=pk)  # NotFoundError if missing
    # 1. Record the customer's comment against the CO they saw (same shape as
    #    the estimate flow's customer-action HistoryEntry).
    HistoryEntry.objects.create(
        entry_type='action', object_type='change_order', object_id=co.pk,
        user=None,
        changes={'_action': 'Changes requested via customer link',
                 'contact_id': actor.get('contact_id'),
                 'customer_email': actor.get('email')},
        text=actor.get('reason') or '',
    )
    # 2. Preserve the proposal the customer saw (Trigger-2-style), then supersede.
    DeliverableService.snapshot_document(change_order=co)
    co.status = ChangeOrder.STATUS_SUPERSEDED
    co.save()                      # sets closed_date
    # 3. Seed a fresh draft CO carrying the same deltas for the shop to revise.
    new_co = ChangeOrderService.seed_new(co.pk)   # parent=co, copies line items
    return new_co
```

Notes:
- `seed_new` already copies line items and sets `parent`; reuse it rather than
  duplicating the copy loop.
- Job stays `on_hold`; `JobService.update_job` already refuses to take a job
  off-hold while a `draft`/`open` CO exists, so the new draft keeps it parked —
  the structural parallel to the estimate flow's "job back to draft."
- `open → superseded` is already a legal CO transition.
- Snapshotting before supersede preserves what the customer saw even though the
  estimate/CO lines may change later (consistent with reject/expire Trigger 2).

### 3.4 Customer-facing payload — `build_change_order_payload(co)`

A CO **is** a diff, so the customer payload presents a before/after rather than
a flat list. Compute it **server-side** (keep the portal frontend thin and avoid
exposing the internal auth, line-item, and deliverables-baseline endpoints to an
anonymous caller). Add a composer to `apps/estimates/agreement.py` that produces
the same merged-row shape as `ChangeOrderDetailPage.svelte`'s `mergedRows` so
shop and customer see the same diff. **Baseline = `co.estimate.estimatelineitem_set`**
— `co.estimate` is always the *accepted* estimate (set by
`ChangeOrderService.create`, `change_order_service.py:45`) and is exactly what
the CO's `target_line_item` FKs point at. (The shop page instead picks the
source estimate heuristically — `accepted || latest non-superseded || last`,
`ChangeOrderDetailPage.svelte:199-203` — which normally resolves to the same
accepted estimate; the server using `co.estimate` directly is *more* correct, so
this is a faithful-but-not-byte-identical mirror.)

```python
def compose_change_order_diff(co):
    """Customer/portal-facing diff of a CO against its estimate's line items.
    Mirrors the shop CO detail page's merged-rows logic.
    Returns {'line_rows': [...], 'prior_total', 'proposed_total', 'diff_total'}.
    """
```

`line_rows[]` items: `{kind, line_number, description, qty, units, price,
amount}` where `kind ∈ {unchanged, changed, changed-orig, removed, added}`
(`changed` = the new value row, `changed-orig` = the struck original beneath it,
`removed` = struck, `added` = new line). Baseline for line items = the CO's
`estimate.estimatelineitem_set` (the same lines the CO's `target_line_item`
FKs point at and the same baseline the shop diff uses), **not**
`compose_agreement`. Single-CO is the validated path; with multiple accepted COs
this could understate the true current agreement — call it out in the doc and
LATER, matching the shop page's existing behavior (don't silently diverge).

`prior_total` = sum of estimate baseline lines; `proposed_total` = sum of
surviving + changed + added rows; `diff_total` = proposed − prior.

**Note the deliberate baseline asymmetry** (faithful to the shop page): the
**line-item** diff baselines off the flat accepted estimate (the single-CO
simplification), while the **deliverables** diff baselines off
`ChangeOrderService.baseline_document(co=co)` (multi-CO-aware: the latest
accepted CO before this one, else the estimate). Don't "fix" one to match the
other — they intentionally use different resolution rules, exactly as the shop
detail page does (line items off estimate lines, deliverables off the
`deliverables-baseline` endpoint).

`build_change_order_payload(co)` returns:

```jsonc
{
  "change_order_number": "JOB-2025-0001-1-CO1",
  "status": "open|accepted|rejected|expired|superseded",
  "sent_date": ..., "expiration_date": ..., "closed_date": ...,
  "deliverables": [ /* merged deliverable diff rows, see below */ ],
  "line_rows": [ /* from compose_change_order_diff */ ],
  "prior_total": "…", "proposed_total": "…", "diff_total": "…",
  "actions": ["accept","request_changes","reject"]  // [] when not actionable
  "actionable": true|false,
  "closed_message": "…" | null,
  "current_token": "…"   // only when superseded — next revision's token
}
```

**Deliverables diff** mirrors the page's `delivMergedRows`: baseline =
`DeliverableSnapshot` rows of `ChangeOrderService.baseline_document(co=co)`
(the prior agreed scope), live = `co.job.deliverables`. Rows:
`{kind, description, qty, units}` with the same kind vocabulary. Money via the
existing `_money` helper (quantize to `0.01`); qty as `str`. Build this inside
the portal module (it already imports the deliverables models) or as a sibling
composer — keep the customer-safe shaping in the portal layer, the pure diff
math in `agreement.py`/a service so it's unit-testable without HTTP.

`current_token` for a superseded CO points at the latest non-draft CO for the
same job, via a `_co_current_token` helper analogous to `_current_token`. Order
by **`-change_order_id`** (not the estimate's `-version, -pk` — CO `version`
stays 1 since `seed_new` doesn't bump it), exclude `draft`, return `None` if it
resolves to itself. **Consequence (parallel to estimates):** right after a
portal request-changes the seeded replacement is a `draft` (portal-invisible),
so `current_token` is `None` and the customer sees a "this change order was
superseded" page with **no forward link until the shop re-sends** the revision.
This matches the estimate flow exactly (`_current_token` also returns `None`
until the new draft is sent).

`closed_message`: when a CO is `open` but not actionable (job left `on_hold`
out from under it), reuse the estimate's `CLOSED_MESSAGE` wording adapted to
"change order".

### 3.5 Shop notification email

Add `ChangeOrderEmailService` in `apps/estimates/services.py` (or a
`change_order_services` module — match where `ChangeOrderService` email-style
helpers would naturally live; `services.py` keeps it beside
`EstimateEmailService`). Mirror `EstimateEmailService`:

- `notify_shop_of_decision(co, decision, reason='')` — best-effort
  `send_mail` to Configuration `business_email`; never raises (customer action
  already committed). Subject `Change order {number} {decision} by customer`.
  Fired by the portal after **all three** decisions — `accepted`, `declined`,
  and **`requested changes`** (the estimate portal notifies on request-changes
  too, `portal/views.py:214-215`).
- `get_email_defaults(co)` and `send_change_order(co, *, to, subject, body, …)`
  for the **send-to-customer** flow (§3.6). `send_change_order` transitions
  `draft → open` on success (like `send_estimate`) but attaches **no PDF** (CO
  PDF deferred) — the body carries the portal link, and `get_email_defaults`
  returns an **empty `attachments_preview`** (the estimate version hardcodes a
  PDF stub at `services.py:389-394`; the CO version omits it). The CO
  `draft → open` transition fires **no** job-status signal (`ChangeOrder.save()`
  has no job side effect, unlike `Estimate.save()`), so sending a CO leaves the
  job `on_hold` — correct. `DEFAULT_BODY` adapted to a change order ("review and
  approve the change online here: {object_url}").
  Subject/body overridable via new Configuration keys
  `change_order_email_subject_template` / `…_body_template` (parallel to the
  estimate keys; add to fixtures + test `setUp`).

### 3.6 Link delivery — send flow & `build_object_url`

- Extend `build_object_url` (`apps/core/email_templates.py`) with a
  `change_order` kind → `<base>/portal/?token=<token>&doc=change_order`
  (look the token up off `ChangeOrder`). Add `'change_order': 'change-orders'`
  to `_OBJECT_URL_PATHS` for the non-token fallback.
- API actions on `ChangeOrderViewSet` (`apps/api/change_orders/views.py`),
  mirroring the estimate viewset:
  - `GET  /api/change-orders/{id}/send-defaults/`
  - `POST /api/change-orders/{id}/send/` (to/subject/body/cc/bcc; transitions
    draft → open via `send_change_order`). `can_manage_jobs`.
- **Frontend (shop side):** replace the CO detail page's bare "Mark as Sent"
  button with a "Send to customer" flow reusing
  `components/email/DocumentSendForm.svelte` (as estimates do via
  `EstimateSendPage.svelte`) — a `/change-orders/:id/send` route, or an inline
  dialog. The underlying transition is still `draft → open`; the bare
  `mark-open` endpoint stays for back-compat/tests but the primary UI path
  sends the email. (Keeping `mark-open` avoids touching the existing
  lifecycle/expiry tests.)

### 3.7 Frontend customer portal

Reuse the **existing `/portal/` Vite entry** (no new html/entry, no new nginx
route). Turn `PortalApp.svelte` into a thin dispatcher on a `doc` query param:

- `?token=…` (no `doc`, or `doc=estimate`) → existing estimate view
- `?token=…&doc=change_order` → new change-order view

Mechanics:
1. Extract the current `PortalApp.svelte` body verbatim into
   `EstimatePortal.svelte` (same markup/logic/styles, same API calls) so the
   estimate path is byte-for-byte unchanged behaviorally.
2. `PortalApp.svelte` reads `token` + `doc` and renders `<EstimatePortal>` or
   `<ChangeOrderPortal>`. Update `frontend/tests/components/PortalApp.test.js`
   to target whichever component now owns the estimate markup (keep the same
   assertions — actionable shows buttons, non-actionable hides them).
3. `ChangeOrderPortal.svelte`: same shell/styles as the estimate portal.
   - `GET /api/portal/change-orders/{token}/`.
   - Header `Change order {change_order_number}`.
   - Terminal/closed banners parallel to the estimate (`requested` thank-you,
     `superseded` + forward link via `current_token`, `expired`, `rejected`,
     `accepted`, `closed_message`).
   - **Deliverables** diff table (added/changed/removed styling, read-only).
   - **Line items** diff table rendering `line_rows` with the same row tints as
     the shop page (changed amber, added green, removed struck), read-only;
     footer shows `prior_total → proposed_total` and `diff_total`.
   - Action buttons (accept / request changes / decline) gated on
     `actionable && !done`, with the same confirm-dialog pattern and reason
     textareas; POST to the CO portal endpoints. Copy adapted: accept =
     "approve this change", request-changes keeps the CO open (we send a revised
     change order), decline.

Follow `frontend/README.md` SPA conventions (semantic HTML, scoped `<style>`,
links navigate / buttons act, no blur-only saves, confirm only the
irreversible — here the three decisions are genuine confirmations because they
commit a customer decision).

### 3.8 Permissions

Portal endpoints are `AllowAny` (token-authorized), exactly like the estimate
portal. The new shop-side `send`/`send-defaults` actions require
`can_manage_jobs` (CO writes already do). No new atom. Update
`users-and-permissions.md` §3 endpoint table.

## 4. Status & lifecycle summary (the parallel)

| Step | Estimate | Change Order (this design) |
|---|---|---|
| Customer-visible when | `open` + job `submitted` | `open` + job `on_hold` |
| Accept | est `accepted`, job `approved` | CO `accepted`, job `on_hold → approved` |
| Reject | est `rejected`, job `rejected` | CO `rejected`, job stays `on_hold` |
| Request changes | parent `superseded`, new `draft` v+1, job `submitted → draft` | CO `superseded`, new `draft` CO (`seed_new`), job stays `on_hold` |
| Drafts in portal | 404 | 404 |
| Race with shop | silent no-op | silent no-op |
| Shop notified | `notify_shop_of_decision` | `notify_shop_of_decision` (CO) |
| Link delivery | `send_estimate` (PDF + link) | `send_change_order` (link, no PDF) |

## 5. Edge cases

- **Token collisions:** `unique=True` + `token_urlsafe(32)`; same as estimates.
  Estimate and CO tokens live in separate tables; the `doc` query param selects
  the endpoint, so cross-type token reuse is irrelevant (a CO token won't
  resolve an estimate and vice versa).
- **Concurrency:** every decision path takes `select_for_update` on the CO and
  re-checks actionability inside the transaction; a click that loses the race to
  a shop action returns the refreshed payload with empty `actions`.
- **Accept idempotency:** accepting an already-`accepted`/terminal CO is a
  no-op (not actionable) — returns payload, doesn't re-advance the job.
- **request-changes when not open:** no-op; no new draft created (parallels
  `test_request_changes_on_non_open_is_noop`).
- **Job moved off on_hold:** can't happen while a CO is `open` (exit guard), but
  the `_co_is_actionable` job-status check defends against it anyway → read-only
  with `closed_message`.
- **Snapshot idempotency:** `DeliverableService.snapshot_document` is
  idempotent, so request-changes snapshotting (and any prior create-time
  snapshot) is safe.
- **No accepted estimate / no line items:** a sendable CO already required line
  items (`clean()` blocks empty `draft → open`); `create` required an accepted
  estimate. The portal only ever sees `open`+ COs, so these are pre-satisfied.

## 6. Testing plan (TDD)

Write failing tests first, then implement. Backend in `tests/`, frontend in
`frontend/tests/`.

**Backend — model/service:**
- `test_change_order_model.py`: `public_token` minted on create, unique,
  stable across saves, distinct per `seed_new` child.
- New `test_change_order_request_changes.py` (mirrors
  `test_portal_request_changes.py`'s service section): supersedes the open CO,
  seeds a new draft carrying the deltas, job stays `on_hold`, records the
  customer-action HistoryEntry with the reason, snapshots the proposal, no-op
  guard for non-open.
- `agreement`/diff composer tests: `compose_change_order_diff` for add / remove
  / replace / unchanged, and totals (prior/proposed/diff).

**Backend — portal API** (new `test_portal_change_orders.py`, unauthenticated
`Client`, mirroring `test_portal_api.py` + `test_portal_job_status_gate.py`):
- GET open CO (no auth) → 200, payload shape, `actions` present when actionable.
- GET unknown token → 404; GET draft CO token → 404.
- GET superseded CO → `current_token` points at the sent revision.
- accept → CO `accepted`, job `approved`; no-op when job not `on_hold`;
  **customer-action HistoryEntry recorded** (`user=None`, `_action` =
  "Accepted via customer link").
- reject → CO `rejected`, job stays `on_hold`; **customer-action HistoryEntry
  recorded with the reason** (`_action` = "Declined via customer link").
- request-changes → supersedes + seeds draft; stores comment; no-op when not
  open; unknown token 404.
- shop-notification: `notify_shop_of_decision` fired for **all three** decisions
  (assert via `mail.outbox` with `business_email` configured).

**Backend — send flow:** `send-defaults` returns to/subject/body with the
portal link; `send` transitions `draft → open` and records an outbound email
(reuse the estimate send test patterns).

**Frontend (Vitest):**
- `ChangeOrderPortal.test.js`: renders line-item diff rows + deliverable diff
  from a mocked payload; shows action buttons when `actionable`, hides when not;
  posts the right endpoint on accept/reject/request-changes; renders terminal
  banners (accepted/rejected/superseded-with-link/expired).
- Update `PortalApp.test.js` for the dispatcher: the estimate path
  (`?token=…`, **no `doc` param**) still renders the estimate view with the same
  actionable/non-actionable button assertions — proving backward compatibility
  with existing estimate links and that the `EstimatePortal` extraction is
  behaviorally unchanged. Add a case that `doc=change_order` routes to the CO
  view.

Run backend with `python manage.py test` (single agent only — shared MySQL);
frontend with `npm run test:run` in `frontend/`.

## 7. Docs to update (durable, same session as code)

- `docs/designs/estimates-and-prices.md` §14: new subsection "Change order
  customer portal" — token, portal endpoints, `request_changes`, the diff
  payload, send flow; update §14.8 endpoint list.
- `docs/designs/users-and-permissions.md` §3: portal CO endpoints (AllowAny),
  CO `send`/`send-defaults` (`can_manage_jobs`).
- `docs/designs/data-constraints.md` §1.1: new Configuration keys
  `change_order_email_subject_template` / `…_body_template`.
- `docs/designs/LATER.md`: close/trim the "no CO email service" note (PDF stays
  open); note the single-CO diff-baseline simplification.

## 8. Out of scope

- CO PDF generation (stays in LATER).
- Multi-CO composed-baseline diff for the customer (single-CO is the validated
  path; documented simplification matching the shop page).
- A job-detail "latest customer change-request" banner for COs (the estimate
  has one; can follow later — the HistoryEntry is recorded regardless).
- Any change to CO authoring, `compose_agreement`, or the on_hold gate.

## 9. Implementation order

1. Model: `public_token` on `ChangeOrder` + migration. (TDD: model test.)
2. `compose_change_order_diff` in `agreement.py` + deliverable-diff helper. (TDD.)
3. `ChangeOrderService.request_changes`. (TDD: service test.)
4. `ChangeOrderEmailService.notify_shop_of_decision`. (TDD.)
5. Portal API (payload builder + 4 views + urls). (TDD: portal API tests.)
6. `build_object_url('change_order')`. (TDD.)
7. Send flow: `get_email_defaults`/`send_change_order` + viewset actions. (TDD.)
8. Frontend: dispatcher + `EstimatePortal` extraction + `ChangeOrderPortal` +
   shop send button. (Vitest.)
9. Docs.
10. Full backend + frontend test run; code review; commit.

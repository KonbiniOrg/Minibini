# Customer Estimate Approval — Spec

_2026-05-31_

Let a customer accept or reject an **Estimate** that the shop has emailed
them, without a Minibini account, by clicking a link in the send email
that lands on a customer-facing page with Accept / Reject actions.

This is the real implementation of the stub described in
`docs/designs/LATER.md` → "Customer-facing public URLs for documents
(`{object_url}` real resolution)". When this ships, that LATER entry is
resolved for Estimates (the PO / Invoice / Bill and CO halves remain
open).

---

## 1. Why this is more than a boolean

The customer's action is one bit, but it carries weight that shapes the
whole design:

- **Irreversible cascades.** Accept fires the existing
  `estimate_accepted` signal → `AtomCarryOverService` (spawns
  Tasks/Materials on the Job) and drives the Job to `approved`. Reject
  drives the Job to `rejected` (terminal) via
  `estimate_status_changed_for_job`. Neither is undone by "click the
  other button."
- **The document changes under the link.** The shop can revise
  (→ `superseded`), the estimate can auto-expire
  (`mark_estimates_expired`), or another open estimate can exist on the
  same Job. The link is long-lived; the document's authority is not.
- **No `User` to attribute to.** The action is unauthenticated; the token
  proves possession of the link, not the identity of the clicker.
- **The link is a bearer credential.** Whoever holds it can commit the
  shop's customer into (or out of) a job.

The design below resolves each: authority is read live from estimate
status (not baked into the link), attribution is an explicit
contact-referencing history entry through a reusable `actor` seam, and
the token is an unguessable per-document secret.

---

## 2. Scope

### In scope (v1)

- Customer-facing **read** of a single sent Estimate (its own line items
  + total + status).
- Customer **Accept** / **Reject** of that Estimate, with a confirmation
  step and an optional reject reason.
- A per-Estimate opaque `public_token`, minted on send.
- A separate Vite entry (the **portal**) serving the customer page, in
  the same build / same server as the operator SPA.
- Portal DRF endpoints (read + accept + reject), login-not-required, with
  their own customer-safe serializer.
- Email notification to the shop on accept/reject, addressed to a new
  `business_email` Configuration key, surfaced in a new **Business**
  Settings tab.

### Out of scope (anticipated fast-follows)

- **Change-order customer approval.** Prerequisite: COs have *no*
  send-to-customer flow today (no PDF, no email service, no
  `change_order` entry in `build_object_url`). Building CO sending, then
  CO approval, is a separate effort. The agreement-of-record view
  (`compose_agreement`: accepted Estimate + accepted COs, with a
  current-vs-proposed diff) is only meaningful for the CO case, so it
  comes with it.
- **Customer portal beyond the single document** — version history, prior
  revisions, a curated/customer-safe `HistoryEntry` projection.
- **Customer login / customer `User` accounts.** Deferred until a real
  portal-with-login requirement exists; the `actor` seam (§7.3) is where
  it will plug in.
- **Further Business-level configs.** The Business Settings tab ships with
  only `business_email`; more keys are out of scope here.

---

## 3. Data model changes

### 3.1 `Estimate.public_token`

`apps/estimates/models.py`:

- New field `public_token = CharField(max_length=64, null=True, blank=True,
  unique=True, db_index=True)`.
- Populated with `secrets.token_urlsafe(32)` (~43 chars) in
  `Estimate.save()` **at creation time** (`if not self.pk and not
  self.public_token`), so the token is durable from the very first write —
  long before any send. See §7.1 for why creation-time, not send-time.
- Per **row** — a revision is a new `Estimate` row and gets its own token.
  An old revision's token keeps resolving but the page shows `superseded`
  with no actions (§8).
- `unique=True` so a token resolves to exactly one estimate.
- A dormant token on an unsent draft authorizes nothing: it is surfaced
  in no email until send, and hitting `/portal/?token=…` for a draft
  resolves to "not available" (§5.1).

Migration: additive, nullable column on `estimates`. Backfill existing
rows with tokens in the same migration (harmless for already-sent
estimates — the token was never in their email — and keeps the column
uniformly populated).

### 3.2 `Configuration` key `business_email`

The shop's notification address. Read via the standard `Configuration`
accessor. Add to test `setUp()` and fixtures per CLAUDE.md. No default
delivery if unset — see §9 for the unset behavior.

---

## 4. Token lifecycle

| Event | Effect on token |
|---|---|
| Estimate created (incl. as `draft`) | token minted in the creation `save()` (§7.1); dormant — surfaced in no email until send |
| Estimate sent (`draft → open`) | token already exists; the URL in the email just reads it |
| Estimate revised | parent keeps its token (resolves, shows `superseded`); the new revision row mints its own at creation |
| Estimate expired / rejected / accepted | token unchanged; page resolves and shows the terminal state, no actions |

The token **never hard-expires.** Available actions are derived live from
estimate `status`, not from the link. This means an old link is always
safe to click — it just shows current truth.

Revocation, if ever needed, is nulling/regenerating the column (not built
in v1, but the opaque-column model makes it trivial later).

---

## 5. Portal surface — the customer page

A second Vite entry in `frontend/`, built by the same `npm run build`,
served by the same server. Nothing operator-side is imported.

- New entry folder, e.g. `frontend/portal/index.html` → `src/portal-main.js`
  → `PortalApp.svelte`. (Folder named `portal/`, **not** `public/` —
  `public/` is reserved by Vite for static assets.)
- `vite.config.js`: add `build.rollupOptions.input` listing both
  `index.html` (operator app) and `portal/index.html`.
- Dev: Vite serves the portal at `/portal/`; the existing `/api` proxy to
  `:8000` covers it. Prod: build emits `dist/portal/index.html`, served at
  `/portal/`.
- The portal has **no auth gate** — it never calls `/api/auth/me`, never
  mounts `App.svelte`, the operator nav, or the auth store.
- v1 is a single view, so no router is required. The token is read from
  the query string: `/portal/?token=<token>`. (`build_object_url` produces
  this URL — §7.4.)
- It may reuse the CSS conventions and a *trimmed* copy of the API helper,
  by explicit import only.

### 5.1 Page layout

Top-down, the customer page shows:

1. **Deliverables** — the Job's deliverables (what the customer is
   buying), on top. Each row is `description`, `qty_ordered`, `units`,
   in `sort_order`. No price (the Deliverable model carries none). Omitted
   if the Job has no deliverables.
2. **Line items + total** — the estimate's own line items (the priced
   proposal) and grand total.
3. **Status banner + actions** — per the table below.

### 5.2 Customer view states

The page fetches `GET /api/portal/estimates/<token>/` and renders by
status:

| Estimate status | What the customer sees |
|---|---|
| `open` | Deliverables + line items + total; **Accept** and **Reject** buttons |
| `accepted` | Deliverables + line items + total; "You accepted this on `<date>`." No actions |
| `rejected` | "This estimate was declined on `<date>`." No actions |
| `expired` | "This estimate expired on `<date>`. Please contact us." No actions |
| `superseded` | "A newer version of this estimate has been issued." Plus a **link to the current estimate** (`/portal/?token=<current_token>`) when one is resolvable (§6.1). No actions on this row |
| `draft` (shouldn't occur — token dormant, never emailed) | generic "not available" |
| token not found | generic "not available" (same response shape; no enumeration signal) |

The "current estimate" for a `superseded` row is the live head of its
revision lineage: the highest-`version` `Estimate` with the same
`estimate_number` whose status is not `superseded`. Its `public_token`
feeds the link. If the head is itself terminal (e.g. all revisions
rejected), the link still resolves and shows that state.

### 5.3 Confirmation + reject reason

- Both Accept and Reject open a confirmation dialog stating consequences
  in plain language:
  - Accept → "Accepting this estimate authorizes us to begin the work it
    describes."
  - Reject → "Declining this estimate closes out this job. This can't be
    undone here — contact us if you change your mind."
- Reject's dialog includes an **optional** free-text reason, recorded in
  the history entry (§7.3).
- This is the one place a confirmation is warranted under the project's
  "confirmations are for the irreversible" rule — both actions are
  irreversible from the customer's side.

---

## 6. Portal API

New viewset/views in their own module `apps/api/portal/`, routed under
`/api/portal/`. Named **portal**, not "public" — these aren't public
documents, they simply don't require a login to view. All:

- `authentication_classes = []` (so no session / CSRF is required for the
  not-logged-in customer to POST).
- `permission_classes = [AllowAny]`.
- Look up the estimate by `public_token`; return the generic
  "not available" shape (not 404-with-detail that distinguishes states)
  when the token is unknown.

| Verb + path | Behavior |
|---|---|
| `GET /api/portal/estimates/<token>/` | Returns the customer-safe payload (§6.1) for the matched estimate, including `status` and an `actions` list derived from status (`["accept","reject"]` only when `open`) |
| `POST /api/portal/estimates/<token>/accept/` | Accept (§8). Body: none |
| `POST /api/portal/estimates/<token>/reject/` | Reject (§8). Body: `{reason?: string}` |

### 6.1 Customer-safe serializer

A **dedicated** serializer — never the internal `EstimateSerializer`. It
exposes only:

- `estimate_number`, `status`, `sent_date`, `expiration_date`,
  `closed_date` (as relevant to the displayed state).
- **Deliverables** (the Job's): `description`, `qty_ordered`, `units`,
  in `sort_order`. No price. Empty list if none.
- Line items: `description`, `qty`, `units`, `price`, `amount`
  (line-number order). These mirror the customer-safe shape already used
  by `compose_agreement`.
- A computed grand total (line items).
- `actions` (derived from status).
- `current_token` — only on a `superseded` estimate: the `public_token`
  of the live head of the revision lineage (§5.2), for the
  "current estimate" link. Null/absent otherwise.

It must **not** leak: internal notes, staff usernames, cost/margin,
`HistoryEntry`, Job internals (beyond the deliverables above),
worksheet/atom internals, or any field not in the list above.

### 6.2 Abuse surface

The token is 32 random bytes — brute force is infeasible, so no rate
limiting in v1. The endpoints do exactly one thing each (read, or a single
guarded status transition); they expose no other mutation.

---

## 7. Backend wiring

### 7.1 Token minted at creation (not at send)

The token is minted in `Estimate.save()` on creation (§3.1), **not** in the
send flow. Reason — ordering. The send flow is: build the email body
(which embeds the URL → needs the token) → **SMTP send** → on success,
`save()` the `draft → open` transition. The email leaves *before* the
status save. If the token were persisted only by a save that runs after
the send (e.g. folded into the draft→open `save()`), a failure of that
post-send save would leave the customer holding a live link whose token is
in **no** DB row — orphaned forever.

Minting at creation removes the window entirely: the token is durable from
the first write, so `build_object_url` always finds it and no email can
ever reference an unpersisted token. `EstimateEmailService.send_estimate`
therefore does **no** token work — it just reads `estimate.public_token`.

### 7.2 `update_status` actor seam

`EstimateService.update_status(pk, new_status, actor=None)`:

- `actor` is an optional small descriptor (e.g.
  `{"kind": "customer", "contact_id": N, "email": str, "reason": str|None}`),
  not a `User`.
- The existing `estimate.save()` side effects (signals, dates, carry-over,
  Job status) are unchanged.
- When `actor` is present, write an explicit `action` `HistoryEntry`
  (§7.3) after the transition.
- All current callers pass no `actor` and behave exactly as today.

### 7.3 Attribution

On a customer transition, write one explicit `HistoryEntry`:

- `entry_type='action'`, `object_type='estimate'`, `object_id=<pk>`,
  `user=None`.
- `changes={'_action': 'Accepted via customer link' | 'Declined via
  customer link', 'contact_id': N, 'customer_email': str, 'status':
  {'old':…, 'new':…}}`, and `reason` text (reject) in the appropriate
  field per the HistoryEntry conventions (`text` for human-entered reason;
  `_action` for the system description).
- The auto-`@history` audit entry for the status flip will land with
  `user=None` (request is unauthenticated) — the explicit action entry is
  what carries the customer identity context.

This is the seam a future customer-`User` plugs into: `actor` would then
also resolve a `user=` for the entry.

### 7.4 `build_object_url`

`apps/core/email_templates.py`: change Estimate URL resolution from the
stub `<base>/estimates/<id>` to `<base>/portal/?token=<token>`, reading
`<base>` from the existing `our_public_url` Configuration key. The token
always exists by this point (minted at creation, §7.1). Other doc kinds
(PO/Invoice/Bill) keep their current stub behavior — unchanged here.

---

## 8. Accept / reject behavior

Both transitions run under `select_for_update` with a re-check:

1. Load the estimate by token `select_for_update`.
2. If `status != open`, do **not** transition — return the current
   customer-safe payload (the page re-renders current state with a
   message). This makes a customer click that races the shop (already
   accepted / revised / expired) a no-op, not an error.
3. If `open`: call `EstimateService.update_status(pk, STATUS_ACCEPTED |
   STATUS_REJECTED, actor=<customer descriptor>)`.
   - Accept → existing `estimate_accepted` carry-over + Job→`approved`.
   - Reject → existing Job→`rejected` (terminal) signal.
4. Send the shop notification (§9).
5. Return the updated customer-safe payload.

Idempotency: re-POSTing accept on an already-`accepted` estimate is a
no-op via the step-2 guard.

---

## 9. Shop notification

After a successful customer accept/reject, send an email via the existing
outbound email infrastructure to the address in the `business_email`
Configuration key:

- Subject/body: brief — which estimate, which customer, the decision, and
  (for reject) the reason if given. Link back to the Job/Estimate in the
  operator app.
- If `business_email` is unset or blank: skip sending (log/no-op); the
  accept/reject still succeeds and is still recorded in history. The
  notification is best-effort and must never block or roll back the
  customer's action.

---

## 10. Settings UI — Business tab

- New **Business** tab in the Settings SPA surface, holding a single
  editable field bound to the `business_email` Configuration key (read via
  the existing settings API; saved with an explicit Save, per the
  "no blur-only saves" rule).
- The tab is structured so additional business-level keys can be added
  later (out of scope here).

---

## 11. Testing (TDD)

Write failing tests first. Cover at least:

- Token mint on send; absent on draft; per-revision uniqueness; old
  revision token resolves and reports `superseded`.
- Portal GET: each status → correct payload + `actions`; deliverables
  present and customer-safe; `superseded` returns `current_token` for the
  live head; unknown token → generic "not available"; serializer leaks
  nothing beyond §6.1.
- Accept (open) → `accepted`, carry-over fires, Job → `approved`, history
  entry with contact context + `user=None`, notification attempted.
- Reject (open) → `rejected`, Job → `rejected`, reason recorded.
- Race guards: accept/reject when status already terminal → no-op,
  current payload returned, no duplicate side effects.
- Notification: sent to `business_email`; unset key → skipped, action
  still succeeds.
- Portal endpoints require no auth and enforce no CSRF.

Per CLAUDE.md: tests use the test DB; never touch the dev DB; only one
agent runs `python manage.py test` at a time.

---

## 12. Docs to update on completion

- `docs/designs/estimates-and-prices.md` §15 — add the customer-approval
  surface (token, portal page, portal endpoints, the `actor` seam).
- `docs/designs/architecture-and-conventions.md` — the portal as a second
  Vite entry; the `/api/portal/` AllowAny endpoint pattern (the first of
  its kind).
- `docs/designs/users-and-permissions.md` — note the portal endpoints sit
  outside the atom model (token-authorized, AllowAny, login-not-required).
- `docs/designs/data-constraints.md` §1.1 — new `business_email`
  Configuration key; `Estimate.public_token` field.
- `docs/designs/LATER.md` — mark the "Customer-facing public URLs"
  entry resolved **for Estimates**; note PO/Invoice/Bill and CO remain.

---

## 13. Open questions / decisions captured

- **Naming (decided):** portal entry served at `/portal/`; config key is
  `business_email`.
- **Token minted at creation, not send (decided):** persisting the token
  only in a post-send save risks a sent email whose token is in no DB row
  if that save fails. Creation-time minting makes the token durable before
  any email leaves. See §7.1.
- **No shadow customer `User` in v1 (decided)** — the `@history`
  middleware resolves the actor from `request.user`, which is anonymous on
  the public endpoint, so a shadow user wouldn't even be picked up
  automatically; the explicit action entry + `actor` seam covers
  attribution without the User-table reach. Revisit when customer login is
  a real requirement.

# Portal "Request changes" — customer-initiated estimate revision

_Spec — 2026-06-03. Branch: `feature/direct-create-line-items`._

## Problem

A customer who receives an estimate, wants the job, but needs changes has only two
honest options today:

- **Reject** — but that's terminal and rejects the *job*, not just the estimate version.
- **Do nothing and email/call the shop** — the app learns nothing. The estimate sits
  `open` (still acceptable), the job sits `submitted`, and there's no in-app signal that
  the customer asked for a revision.

The second case is a trap: the app's displayed state is stale, and the customer could
still click Accept on terms they've already asked to change. (Note: once the shop
*revises*, `revise_estimate` immediately supersedes the parent — `services.py:164` — so
the customer is locked out of accepting the stale one. The trap window is purely between
"customer wants changes" and "shop revises.")

We want a third portal action that is the missing signal, and that leaves the job +
estimate in a clear, in-the-pipeline state — **without adding any new status**.

## Design (no new states; one new transition)

Add a portal action **Request changes** (with a comment), shown only while the estimate
is `open`. When the customer submits it, the server:

1. Records the customer's comment (see **Comment storage** below).
2. Calls `EstimateService.revise_estimate(parent)` — existing behavior: creates a new
   `draft` estimate (version + 1, line-item **sources moved**, `source_template` copied)
   and supersedes the parent (`open → superseded`).
3. Reverts the job `submitted → draft`.
4. Notifies the shop (`EstimateEmailService.notify_shop_of_decision`, decision word
   `"requested changes"`), including the comment.

**Resulting state:** job = `draft`, live estimate = `draft` (v2), old estimate =
`superseded`, comment captured. That's the normal pre-submission quoting state, expressed
entirely with existing statuses. The shop edits the auto-staged v2 draft and re-sends;
re-sending runs the existing transitions (estimate `draft → open`, job `draft → submitted`)
and the loop closes with no new machinery.

### The one structural change: a new job transition

`Job.VALID_TRANSITIONS` (`apps/jobs/models.py:99`) currently does **not** permit
`submitted → draft` (submitted may only go to `approved` or `rejected`). Add it:

```python
Job.STATUS_SUBMITTED: [Job.STATUS_APPROVED, Job.STATUS_REJECTED, Job.STATUS_DRAFT],
```

Reverting to `draft` is side-effect-free: the job-status side effects fire only on
`on_hold`/`cancelled`/`work_complete`/`completed`/earmark-releasing statuses
(`apps/jobs/services.py:411-446`); `draft` triggers none of them.

### Why a new action and not "rework Reject"

Reject and Request-changes have **opposite** job outcomes — Reject declines the *job*
(terminal, `job → rejected`); Request-changes keeps the job alive. Folding them loses the
one bit that matters (does the job survive?) and forces the shop to infer intent from a
free-text comment. Adding the third action **relieves** Reject of an overloaded duty:
afterward Reject means exactly one thing.

### Churn is self-limiting

After the auto-revise the estimate is a `draft` (not portal-visible — drafts return "Not
available"), and the old token renders the `superseded` "a revised estimate is coming"
view. The customer can't request changes again until the shop re-sends. No v2→v3→v4 spam.

### Shop escape hatch

If the requested change is a dealbreaker, the shop discards the v2 draft and rejects the
job (`draft → rejected` is allowed). Auto-revising only *stages* a draft; it commits the
shop to nothing irreversible.

## Comment storage

**Reuse the existing customer-action `HistoryEntry`** — no new column. The portal reject
`reason` already lands here (`EstimateService.update_status`, `services.py:80-98`):

- `entry_type='action'`, `object_type='estimate'`, `object_id=<superseded parent pk>`,
  `user=None`
- `text=` the customer's comment
- `changes={'status': {'old': 'open', 'new': 'superseded'}, '_action': 'Changes requested
  via customer link', 'contact_id': ..., 'customer_email': ...}`

Recording it against the **superseded parent** (the estimate the customer was actually
looking at) keeps it consistent with accept/reject and preserves the audit trail. The
banner/board surfacing (below) finds it by querying the latest change-request action
across the job's estimates — so which estimate in the tree it's attached to doesn't matter
for display.

## Surfacing (so the auto-staged draft is actionable)

The danger of auto-revision: the v2 draft is a verbatim copy and looks finished, so a shop
user may not realize it's a change-request or know what to edit. Mitigations:

1. **Job + estimate detail banner.** A banner at the top of the job and the v2 estimate
   echoing the latest change-request comment: _"Customer requested changes: '…'."_ This is
   the shop's work order — they edit those lines and re-send. Derivation: latest
   `HistoryEntry` with `_action='Changes requested via customer link'` among the job's
   estimates.

2. **Board badge — "Revision".** The job drops back into the draft/quoting pillar. Show a
   derived **"Revision"** badge — _not_ a stored state — computed from "the job's live
   estimate is a `draft` with `version > 1`." (This deliberately also covers
   shop-initiated revisions; the per-customer comment lives in the detail banner, not the
   badge.)

## Backend changes

- `apps/jobs/models.py` — add `STATUS_DRAFT` to `submitted`'s allowed transitions.
- `apps/estimates/services.py` — new `EstimateService.request_changes(pk, actor)`:
  writes the change-request `HistoryEntry` on the parent, calls `revise_estimate(parent)`,
  reverts the job `submitted → draft`, returns the new draft. Wrap in
  `transaction.atomic()`.
- `apps/estimates/services.py` — `notify_shop_of_decision` already takes a decision word;
  call it with `"requested changes"` and the comment.
- `apps/api/portal/views.py` — new `portal_estimate_request_changes(request, token)`
  (`AllowAny`, no auth), mirroring `portal_estimate_reject`: pull `comment`/`reason` from
  the body, guard that the estimate is `open` (else no-op like the other decisions), call
  the service inside `select_for_update`.
- `apps/api/portal/urls.py` — add
  `estimates/<str:token>/request-changes/` → the new view.
- `build_estimate_payload` — `actions` becomes `['accept', 'request_changes', 'reject']`
  when status is `open`.

## Frontend changes

- **Portal page** — third button **Request changes**, opening a small comment field
  ("Tell us what to change") and POSTing to the new endpoint. On success, the page shows
  the locked "a revised estimate is on the way" view.
- **Job detail / estimate detail** — the change-request banner (latest comment).
- **Board** — the derived **"Revision"** badge on draft jobs whose live estimate is v > 1.

## Edge cases

- **Customer requests changes on v2 as well** — same cycle; each request supersedes the
  prior and bumps the version. One-tree-per-job handles it.
- **Estimate not `open`** (race: shop already revised/closed it) — no-op, return the
  current payload, exactly like accept/reject racing the shop.
- **Attribution** — the auto-revise + job revert + history entry are attributed to the
  customer/contact via the existing portal `_actor_for` dict; `user=None`.

## Testing (TDD)

- Service: `request_changes` supersedes the parent, creates a v2 `draft` with moved
  sources, reverts job `submitted → draft`, writes the comment `HistoryEntry`.
- Transition: `submitted → draft` now valid; other backward transitions still rejected.
- Portal: `POST /request-changes/` on an `open` estimate returns the locked payload and
  performs the revise + revert; on a non-`open` estimate is a no-op; unknown token → 404.
- Payload: `open` estimate exposes `request_changes` in `actions`.
- Notification: shop email sent with decision word + comment.

## Out of scope

- A distinct "changes requested" job status or board column (deliberately avoided — the
  derived "Revision" badge + detail banner cover it).
- Distinguishing customer-initiated vs. shop-initiated revisions on the **board** (the
  badge intentionally covers both; the customer comment is detail-level only).
- Forcing the customer to use the button (case (b), pure email, can't be eliminated — the
  button just makes the right path the easy path, and the shop-revise path already
  supersedes correctly).

# Work Shifts — Design Spec

**Date:** 2026-05-30
**Branch:** `feature/shifts`
**Status:** Design approved in brainstorming; pending written-spec review before planning.

## 1. Purpose & drivers

Add **attendance tracking** to Minibini: workers clock in when they arrive and
clock out when they leave, producing a per-worker record of presence. Two
primary drivers:

1. **Payroll** — total clocked hours per worker over a pay period.
2. **Comparing clocked time against logged task time (Bleps)** — clocked time is
   the outer envelope; Bleps are what's accounted for inside it. The difference
   is presence not landing on any job. (Only a *report of shift times* ships in
   v1; the side-by-side clocked-vs-logged comparison view is deferred — see §12.)

"Who's on the clock right now" falls out for free (open shifts) and will be
surfaced minimally; a dedicated presence view is not in scope.

This replaces the existing 501 stubs `POST /api/shifts/clock-in/` and
`POST /api/shifts/clock-out/` (`apps/api/time_tracking/urls.py`).

## 2. Scope

**In (this round):**

- Clock in / clock out for all users.
- Auto-clock-in: starting a Blep while off the clock opens a shift.
- Clock-out closes any open Blep(s).
- Review my shifts (Home → Time tab, alongside the existing Blep list).
- Update my own most-recent shift within a 30-hour window.
- Request a change to an older shift (amend) **or** record a missing one
  (create) → manager approves/denies.
- **Symmetric change-requests for Bleps** (the deferred "Request Edit" path —
  now built), reusing the shift machinery.
- The shift↔blep enclosure invariant, enforced everywhere a time record is
  mutated, with conflict UI.
- Payroll shift-time report (per worker, per day, configurable date range).
- Login lands on the user's Home screen.

**Out / deferred (see §12):** auto-closing stale open shifts (cron); a dedicated
"who's here now" view; the clocked-vs-logged *comparison/gap* view; manager
approve-with-modification; per-worker schedule shapes feeding `/schedule`.

## 3. The enclosure invariant

> **Every Blep must be fully enclosed by a Shift of the same user:**
> `shift.start_time ≤ blep.start_time` **and** `blep.end_time ≤ shift.end_time`.

Clocked time is the outer envelope; no logged task time may ever spill outside
it. This holds by construction going forward (auto-clock-in births a blep inside
a shift; clock-out closes open bleps so none can straddle a clock-out gap). **No
edit — by worker or manager — may persist a state that leaves an in-window blep
un-enclosed.**

The invariant binds **all** bleps — there is **no exemption for pre-feature
bleps**. This is pre-production code, so existing bleps that would otherwise be
orphaned are given enclosing shifts by a one-time backfill script (see §14)
rather than carved out of the rule.

This is hard data integrity. **Add it to `docs/designs/data-constraints.md`.**

## 4. Data model

### 4.1 `Shift` (in `apps.core`, alongside `User`)

```python
@history(exclude=['shift_id'])
class Shift(models.Model):
    shift_id   = models.AutoField(primary_key=True)
    user       = models.ForeignKey('core.User', on_delete=models.PROTECT)
    start_time = models.DateTimeField()                       # clock-in
    end_time   = models.DateTimeField(null=True, blank=True)  # null = on the clock

    class Meta:
        db_table = 'shifts'
```

- **Open shift** = `end_time IS NULL`. "Here now" = the set of open shifts.
- **One open shift per user at a time**, enforced front-end *and* back-end.
  MySQL has no partial unique index, so enforce in the service / `clean()` (block
  clock-in / create when the user already has an open shift), not via a DB
  constraint.
- **Multiple shifts per day are allowed** (lunch, a doctor's appointment — any
  number). No "one shift per day" constraint. The only guard is one *open* shift
  at a time.
- `user` is required (a shift always belongs to someone) — unlike `Blep.user`,
  which is nullable.
- `@history`-tracked (payroll-sensitive audit trail of every time change).

### 4.2 Change requests — abstract base + two subclasses

Matches the house `BaseLineItem` / `AbstractWorkContainer` pattern. Shared logic
(submit, approve, deny) is written once against the base; only "apply to the real
record" and "which conflicts to check" differ per subclass.

```python
class TimeChangeRequest(models.Model):   # abstract
    STATUS_PENDING  = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_DENIED   = 'denied'

    requester       = models.ForeignKey('core.User', on_delete=models.PROTECT,
                                         related_name='+')
    requested_start = models.DateTimeField()
    requested_end   = models.DateTimeField(null=True, blank=True)
    reason          = models.TextField()          # REQUIRED, non-blank
    status          = models.CharField(..., default=STATUS_PENDING)
    has_known_conflict = models.BooleanField(default=False)  # set at submit (§7)
    reviewer        = models.ForeignKey('core.User', null=True, blank=True,
                                        on_delete=models.PROTECT, related_name='+')
    reviewed_at     = models.DateTimeField(null=True, blank=True)
    review_note     = models.TextField(blank=True, default='')
    created_at      = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True

@history(exclude=['request_id'])
class ShiftChangeRequest(TimeChangeRequest):
    request_id = models.AutoField(primary_key=True)
    shift = models.ForeignKey('core.Shift', null=True, blank=True,   # null = create
                              on_delete=models.PROTECT)
    class Meta:
        db_table = 'shift_change_requests'

@history(exclude=['request_id'])
class BlepChangeRequest(TimeChangeRequest):
    request_id = models.AutoField(primary_key=True)
    blep = models.ForeignKey('jobs.Blep', null=True, blank=True,     # null = create
                             on_delete=models.PROTECT)
    task = models.ForeignKey('jobs.Task', null=True, blank=True,     # which job the
                             on_delete=models.PROTECT)                # work was against
    class Meta:
        db_table = 'blep_change_requests'
```

- `shift`/`blep` null ⇒ a **create** request (record a missing shift/blep);
  non-null ⇒ an **amend** request.
- `task` is required on a *create* blep request; on an amend it mirrors the
  existing blep's task (task reassignment is out of scope here).
- *(Model placement of the two request models — `apps.core` vs. their subjects'
  apps — is an implementation-plan detail; the abstract base lives where it can
  be imported by both.)*

## 5. Lifecycle rules

- **Clock in** → create an open `Shift` for the user (blocked if one is already
  open).
- **Clock out** → set `end_time = now`, and **close any open Blep** for that user
  (set its `end_time = now`) so the envelope invariant holds.
- **Auto-clock-in** → starting a Blep while the user has no open shift opens one
  first (its `start_time` = the blep's start), then the blep proceeds normally.
- **Forgot to clock out** → the shift stays open; **no auto-close sweep in v1**
  (avoids a new cron dependency — none is wired in any deployed environment). A
  stale open shift is simply visible and correctable by hand. Revisit only if it
  proves a nuisance.
- **Forgot to clock in entirely** → covered two ways: a blep auto-opens a shift
  (so any logged work creates one); and a fully-missing day (worked, no clock-in,
  non-customer work with no bleps) is recorded via a **create** change request.

## 6. Self-service edit windows

- **30-hour rolling window**, anchored on the record's `start_time`, for both
  **shifts and bleps**. (Bleps move from 24h → 30h for consistency; the existing
  `within24h` check in `RecentTimeList` becomes `within30h`.)
- Within the window: the **owner** edits directly (`IsAuthenticated`).
- Outside the window: the owner files a **change request**; a `can_manage_time`
  manager edits directly or resolves the request.
- 30h (vs. 24h) lets a worker fix all of *yesterday* without racing to do it
  before *today's* clock-in.

## 7. Change-request workflow & conflict handling

One overlap check, surfaced everywhere a time record is mutated. The server is
the hard gate; the client does a soft check for UX. **No two-records-at-once
editor is ever built.**

| Situation | Behaviour |
|---|---|
| **Worker self-edit** (within 30h) that would break the invariant | **Block Save**, clear message naming the offending record ("this shift no longer covers your 2:00–4:30 blep on Job X — fix that blep first"). |
| **Worker files a request** (older than 30h) that would conflict | **Warn but allow** — the request is only a proposal, and the worker often can't fix the old counterpart themselves. Set `has_known_conflict = True`; the conflict travels to the manager. |
| **Manager approves a request / direct-edits** that would break the invariant | **Block**, with an **inline jump-link** to edit the conflicting record (same modal, manager mode). Fix it, return, approve/save succeeds. "Change both records" = two deliberate single-record edits stitched by the link. |

Throughline: **warned-and-allowed** when filing a proposal; **hard-blocked**
when committing a mutation. Nobody ever persists invalid data.

- **Approve** applies `requested_start`/`requested_end` to the target verbatim
  (creating the record if the target FK is null), after the invariant check.
  v1 is **binary** — no approve-with-modification; a manager who wants different
  values direct-edits the records instead.
- **Deny** sets `status = denied`; `review_note` optional.

## 8. Permissions

| Action | Permission |
|---|---|
| Clock self in/out | `IsAuthenticated` |
| Clock another user in/out (on behalf) | `can_manage_time` |
| Edit own shift/blep within 30h | `IsAuthenticated` (owner) |
| Edit anyone's shift/blep, any time | `can_manage_time` |
| File a change request (own record) | `IsAuthenticated` |
| Approve / deny a change request | `can_manage_time` |
| Payroll shift-time report | `can_manage_time` **OR** `can_manage_financials` |

The on-behalf clock and after-window edits match the permissions doc's existing
note for the shift stubs (`IsAuthenticated` for self; `can_manage_time` for
others). **Wire these in `docs/designs/users-and-permissions.md`** (it currently
lists the shift endpoints as stubs awaiting atom assignment).

## 9. API

Replace the `time_tracking` stubs and add request/report endpoints.

```
POST /api/shifts/clock-in/                 self → IsAuthenticated; on-behalf → can_manage_time
POST /api/shifts/clock-out/                (closes any open blep server-side)
GET  /api/shifts/                          ?user=me&since=...  (own list; all for manager)
GET  /api/shifts/active/                   current open shift(s) — clock state / here-now
PATCH/api/shifts/{id}/                     owner ≤30h, else can_manage_time; invariant-gated

GET/POST       /api/shift-change-requests/
POST           /api/shift-change-requests/{id}/approve/    can_manage_time; invariant-gated
POST           /api/shift-change-requests/{id}/deny/
GET/POST       /api/blep-change-requests/
POST           /api/blep-change-requests/{id}/approve/
POST           /api/blep-change-requests/{id}/deny/

GET  /api/shifts/report/?start=&end=&user= per-worker per-day shift times;
                                           can_manage_time OR can_manage_financials
```

- The manager queue reads pending requests of **both** types (unified list — a
  combined read endpoint or two calls merged client-side; planning decides).
- Live conflict detection in the modal reuses `GET /api/bleps/?user=&since=` (and
  the equivalent for shifts) to soft-check enclosure; the server `approve`/`PATCH`
  re-checks and is authoritative.
- All DELETE responses (if any) return 200 + JSON per house rule.

## 10. Frontend (reuse-first)

- **Generalize `BlepEditModal` → `TimeEditModal`** — props `recordType`
  (`'shift'|'blep'`) and `action` (`'edit'|'create'|'request'`). `request` mode
  adds a required **reason** textarea and a conflict-warning banner (warn-allow);
  `edit`/`create` modes do live conflict detection and **disable Save** on a
  broken invariant, showing the jump-link to the conflicting record. Keeps the
  existing `datetime-local` / `isoToLocal` / `localToIso` / target-user pieces.
- **Home → Time tab:** add a `ShiftLogTable` built like `BlepLogTable`
  (date/duration formatting, running tick, optional `actions` snippet). The
  request flow is built **once** and wired into **both** tables as a trailing
  per-row action column: **Edit** when within window, **Request Change** when
  older — identical to `BlepLogTable`'s `actions` snippet. This fills in the
  existing `requestEdit()` stub in `RecentTimeList` (currently
  `alert('not yet implemented')`) to open `TimeEditModal` in request mode, and
  adds the shift equivalent. Bump `within24h` → `within30h`. Add a **"My pending
  requests"** list so workers see approved/denied outcomes.
- **Home top:** big **Clock In / Clock Out** buttons, state-aware (reads the open
  shift via `/api/shifts/active/`), visible regardless of the active tab — first
  thing on arrival.
- **Login lands on Home** — add a redirect to `#/` after successful login
  (`stores/auth.js` / `LoginPage`); currently nothing routes post-login.
- **Manager Users page:** a new **Shifts** tab holding (a) the unified pending
  change-request queue with **Approve / Deny** (deny allows a review note),
  modeled on the reimbursement review precedent (`UserReimbursementPanel`); (b)
  direct-edit access to shifts/bleps (invariant-gated); (c) the **payroll
  report** with a **date-range picker** (start/end or last-N-days — a UI control,
  not a stored Configuration key).

## 11. History / audit

Both `Shift` and the two request models carry `@history(...)`. Every clock edit,
request, approval, and denial leaves a `HistoryEntry` — essential for payroll.

## 12. Deferred / out of scope

- **Auto-close stale shifts** (nightly sweep) — needs a scheduler; v1 leaves open
  shifts visible and hand-corrected.
- **Dedicated "who's here now" view** — only the open-shift clock state on Home in
  v1.
- **Clocked-vs-logged comparison/gap view** — the v1 report shows shift times
  only; bleps may join it later.
- **Approve-with-modification** — v1 approve is binary; managers direct-edit
  instead.
- **Per-worker schedule shapes feeding `/schedule`** — a separate feature (the
  schedule doc's "per-worker schedule shapes" future work).

## 13. Durable docs to update (same session as implementation)

- `data-constraints.md` — enclosure invariant; `Shift` field constraints;
  one-open-shift rule.
- `users-and-permissions.md` — promote the shift stub endpoints to live, with the
  §8 atom map; the new request/report endpoints; login-lands-on-Home.
- `architecture-and-conventions.md` — `TimeEditModal` generalization; shift
  endpoints live (drop the stub references); `@history` on shifts/requests.
- `jobs-tasks-and-worksheets.md` — the Blep auto-clock-in / clock-out-closes-blep
  lifecycle (where Blep behaviour is documented).

## 14. Addendum: backfill enclosing shifts for existing bleps

Because the enclosure invariant (§3) binds **all** bleps with no pre-feature
exemption, every existing blep must already sit inside a shift before the data is
exercised. A one-time backfill script creates those shifts.

- **Approach:** for each user, group their existing bleps (by calendar day is the
  simplest grouping that works) and create one `Shift` per group spanning
  `min(blep.start_time)` → `max(blep.end_time)`, so the shift fully encloses every
  blep in the group. (A finer contiguous-cluster grouping is fine too if a single
  day spans an implausible range; day-grouping is the default.)
- **Edge cases the script must handle:** bleps with a null `end_time` (open) and
  bleps with a null `user` (cannot belong to a shift) — decide skip-or-flag during
  implementation; flag any blep it cannot enclose rather than silently dropping it.
- **Timing:** run **after code is complete but before browser testing against the
  fixture data**, so the test dataset satisfies the invariant.
- **Execution & DB-safety:** the script is **run by the human user, never by
  Claude** (per the project's never-write-to-dev-DB rule). Deliver it as a
  management command (or fixture-aware script) the user invokes; it must be
  idempotent (safe to re-run — skip bleps already enclosed by a shift).

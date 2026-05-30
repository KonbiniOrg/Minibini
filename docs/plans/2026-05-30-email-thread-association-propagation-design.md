# Email-thread association propagation — design spec

**Status:** Draft, ready for review.
**Date:** 2026-05-30
**Scope:** when an `EmailRecord` gains a Job / PO / Bill FK — whether
by `create-X-from-email`, by the user manually linking via the
action panel, or by `correlate_reply` auto-linking an inbound — copy
that same association to every other EmailRecord in the same
RFC 5322 thread that doesn't already have it. Symmetric for all
three association targets. Don't overwrite differing existing
associations. Disassociate stays one-email-at-a-time.

Out of scope: a UI affordance distinguishing auto-linked siblings
from human-confirmed ones (we explicitly ruled this out in the
original action-panel brainstorm — a human reads every email
anyway, the existing Disassociate handles miscategorization);
cross-tenant propagation (no tenancy yet); thread-level operations
other than association inheritance (no "delete whole thread," no
"mark thread read," etc.).

---

## 1. Problem

Today, when a user creates a Job from email E5 in a long thread, only
E5 is linked to the new Job. E1–E4 — all the back-and-forth that led
up to the decision to spin up a Job — stay orphaned in the inbox.
Each of those earlier emails is part of the historical record of how
the Job came to be, but the user has to manually link each one via
the action panel.

The user's request: when any email in a thread gets associated, the
rest of the thread should pick up the same association. If a stray
email at the tail of the thread doesn't actually belong (e.g., the
last message turned the conversation in a direction unrelated to the
new Job), the user can still hit Disassociate on it. Catching the
common case automatically beats forcing manual cleanup of the common
case in service of an uncommon exception.

The same logic applies symmetrically to Purchase Order and Bill
associations.

## 2. Thread definition

A thread is the transitive closure of an email's RFC 5322 reply
graph. Two emails are in the same thread when their "thread key
set" intersects, where an email's key set is:

```
{ self.message_id }
∪ { self.temp_data.in_reply_to }     (when non-empty)
∪ { tokens in self.temp_data.references }
```

For each token we normalize by stripping whitespace; we do *not*
strip angle brackets (`<…>`), since both inbound and outbound
EmailRecords store `message_id` with brackets intact and we want
the comparison to match.

### 2.1 Computation

A new helper in `apps/core/email_utils.py`:

```python
def collect_thread_member_ids(email_record):
    """Return the EmailRecord PKs in the same RFC 5322 thread as
    ``email_record``, including ``email_record`` itself.

    Walks via Message-ID, In-Reply-To, and References intersection.
    One iterative pass over the database (bounded by thread size).
    """
```

Algorithm (BFS over the thread graph):

1. Start with `known_ids = {email_record.message_id}` and any
   non-empty `in_reply_to` / `references` tokens from
   `email_record.temp_data`.
2. Repeat:
   - Query EmailRecords whose own `message_id` is in `known_ids`,
     OR whose `temp_data.in_reply_to` is in `known_ids`,
     OR whose `temp_data.references` mentions any token in
     `known_ids` (substring match — see §2.2).
   - For each row found, add its `message_id`, `in_reply_to`, and
     `references` tokens to a `next_ids` set.
   - If `next_ids ⊆ known_ids`, stop. Otherwise, merge
     `next_ids` into `known_ids` and loop.
3. Return the set of EmailRecord PKs whose `message_id` is in the
   final `known_ids`.

In practice, threads converge in 1–2 iterations because each round
captures everything reachable via direct relationships and the
References chain already encodes ancestry. The query is bounded by
the size of the inbox; we cap iterations at a defensive `8` to
prevent any pathological loop.

### 2.2 References substring matching

`References` is a space-separated list. We could split it server-side
in Python on every email, or use SQL `LIKE '%<token>%'`. The `LIKE`
approach lets the database do the work in one query per round:

```sql
SELECT ... FROM temp_email
WHERE in_reply_to IN (...)
   OR message_id IN (...)
   OR references LIKE '%<id-1>%'
   OR references LIKE '%<id-2>%'
   ...
```

For typical thread sizes (a few to a few dozen message-IDs), the
`OR` chain is fine; for very large threads, batching by chunks of
~20 IDs per query is a trivial optimization if it ever matters.

`References` tokens always include angle brackets per RFC 5322, so
the substring match is unambiguous (no risk of an ID like `<abc>`
matching a partial of another like `<abcdef>` because the closing
`>` is included).

## 3. Propagation behavior

A new helper in `apps/core/services.py:EmailService`:

```python
@staticmethod
def propagate_thread_association(email_record, target_field):
    """Copy ``email_record.<target_field>`` to other EmailRecords in
    the same thread that have a NULL value for the same field.

    Does nothing if email_record has no value for that field (we
    only propagate *something*, not the absence of something).
    Does NOT overwrite a non-null value already set on a sibling —
    that's a deliberate human choice we respect.
    """
```

Steps:

1. Read the value `source_value = getattr(email_record, target_field + '_id')`.
   If null, return — nothing to propagate.
2. Compute the thread member PK set via `collect_thread_member_ids`.
3. `EmailRecord.objects.filter(pk__in=thread_pks, **{target_field + '_id__isnull': True}).update(**{target_field + '_id': source_value})`.

That's a single bulk UPDATE. We don't iterate Python instances and
don't fire `Model.save()` — we explicitly want bulk semantics here.
Audit-trail-wise, the propagated associations get an
`EmailRecord`-level history entry from the `@history` decorator on
the EmailRecord model (via the next save) — wait, no: bulk
`.update()` bypasses signals and the history capture. **We
deliberately accept that.** A history entry per propagated row
would flood the activity feed with noise; the user-initiated
association on the source email IS the audited event, and the
propagated set is the implicit consequence the spec promises.

(Sidebar: if we ever decide the propagated rows DO need their own
history entries, we'd iterate and `.save()` each one instead — but
that's a deliberate future change, not an oversight here.)

### 3.1 Single-target propagation per call

Each call to `propagate_thread_association` handles exactly one
target field. The caller — typically `EmailService.associate_with`
— knows which field was just set. We don't try to propagate "all
non-null FKs" speculatively when one is being set, because the
others were already propagated at the time *they* were set.

The exception is `correlate_reply`, which can set multiple FKs on a
new inbound at once (when the parent had all three set). It calls
`propagate_thread_association` once per non-null FK after copying.

## 4. Where it runs

### 4.1 `EmailService.associate_with` — primary call site

The parameterized association entry point already exists in
`apps/core/services.py`:

```python
@staticmethod
def associate_with(email_record_id, target_field, target_pk):
    ...
    setattr(email_record, target_field, target)
    email_record.save()
    return email_record
```

After the `email_record.save()`, add:

```python
    EmailService.propagate_thread_association(email_record, target_field)
```

That single line covers everything that flows through `associate_with`:

- `link_to_job` / `link_to_po` / `link_to_bill` view endpoints — both
  the original action-panel UI and any future caller.
- `create_job_from_email` view — which calls
  `EmailService.associate_with(pk, 'job', job.pk)` after creating
  the Job.
- `create_po_from_email` view — same shape.
- The Bill stub create flow (`EmailCreateBillPage` → future
  `link-to-bill` call) — same shape when it lands.

### 4.2 `EmailService.correlate_reply` — also propagates

`correlate_reply` runs at IMAP fetch time when a new inbound's
In-Reply-To or References matches an existing EmailRecord. Today it
copies the parent's FKs onto the new inbound via direct `.update()`:

```python
EmailRecord.objects.filter(pk=email_record.pk).update(**updates)
```

After the update, call:

```python
for field in updates:
    EmailService.propagate_thread_association(email_record, field.removesuffix('_id'))
```

(Or, equivalently, call `propagate_thread_association` once per FK
field that was just set.)

This closes a gap that exists today: if E1 is linked to a Job, E2
(reply to E1) was somehow unlinked, and E3 (reply to E2) arrives,
`correlate_reply` finds E1 via E3's References chain and copies J
onto E3 — but E2 stays orphaned. After this change, E3's new
association propagates and picks up E2 along the way.

### 4.3 `EmailService.disassociate_from` — no propagation

Disassociating an email from a Job (or PO or Bill) operates on that
one email only. The user is making a deliberate "this specific email
doesn't belong here" call. Propagating disassociation would force
every sibling-link to require re-confirmation, which is the
opposite of what the user wants.

If the user really does want to clear a whole thread, the existing
Disassociate button on each email is the path — one click per
email, which the user has explicitly accepted as the right cost for
the exception case.

## 5. Edge cases

### 5.1 Sibling already linked to a different target

E1 is linked to Job 5 (set sometime ago). User now creates Job 7
from E5 in the same thread. Propagation tries to set Job 7 on every
thread member where `job_id IS NULL`. E1's `job_id` is 5 (non-null),
so it's untouched. E1 stays linked to Job 5; E2, E3, E4 (assumed
null) get Job 7.

The user can see this inconsistency by browsing the linked Jobs and
will resolve it manually if needed.

### 5.2 Mixed FK types on siblings

E1 is linked to PO 3. User links E5 (same thread) to Job 7.
Propagation only touches `job_id` because that's the field being
set. E1 keeps PO 3 *and* gains Job 7 (since its `job_id` was null).
Other thread members with no associations gain just Job 7.

This is correct — the thread is now considered to be about both PO
3 and Job 7, which is plausible.

### 5.3 Cross-thread emails that happen to share an old ancestor

A customer keeps replying to an ancient `<welcome@…>` Message-ID
that we sent years ago, instead of starting fresh threads. Two
otherwise-unrelated conversations end up sharing `<welcome@…>` in
their References. Linking one to Job A would propagate to the
other.

This is the standard threading hazard mail clients deal with. In
practice it's rare (most clients hide the broken thread, customers
who do this notice and click "compose new"), and the user's manual
Disassociate handles it when it happens. Not worth defensive code
in v1.

### 5.4 Self-loop / pathological References

A maliciously-formed References header could in principle reference
the email's own Message-ID, or chain back to a Message-ID we
generated for a different thread. Our BFS converges either way
(the `next_ids ⊆ known_ids` exit), and the propagation just
under-includes or over-includes a few siblings. The defensive
iteration cap (8) prevents any unbounded loop.

### 5.5 Outbound emails in the thread

Outbound EmailRecords (replies we sent) participate in the same
thread by the same RFC 5322 rules. They show up in the BFS just
like inbound emails and pick up association FKs when null. This is
correct: an outbound reply we sent about a Job should be associated
with that Job.

### 5.6 Email with no temp_data

EmailRecords whose `TempEmail` row has been purged from the cache
have no `in_reply_to` / `references` data. The BFS step that reads
those fields safely returns empty sets for such rows (they get
included in `known_ids` via their `message_id` but contribute no
new tokens). They're still propagation targets via their
`message_id`.

## 6. Tests

- **`tests/test_email_models.py`** (service-layer) — new
  `PropagateThreadAssociationTest` class covering:
  - Linear chain (E1 → E2 → E3 → E4) where one mid-chain email gets
    a Job; all four end up with the Job.
  - Branching thread (E1 has two replies E2a, E2b, each with their
    own replies) — linking from any branch covers all members.
  - Sibling already linked to a different Job stays untouched
    (§5.1).
  - Mixed FK types — linking E5 to a Job doesn't touch E1's PO
    (§5.2).
  - Outbound EmailRecords in the thread pick up the new
    association (§5.5).
  - Email with no temp_data participates correctly as a target
    (§5.6).
  - `propagate_thread_association` is a no-op when the source's FK
    is null.
- **`tests/test_email_utils.py`** — new `CollectThreadMemberIdsTest`
  class covering the BFS:
  - Single email in its own thread (no references).
  - Linear chain via References — all included.
  - Reply by In-Reply-To only (no References) — included.
  - Two emails sharing a thread root but otherwise unrelated —
    both included.
  - BFS iteration cap (use a contrived 8+ depth chain — should still
    converge because the chain is captured in `references`; the cap
    is defensive, not normally hit).
- **`tests/test_api_email.py`** — extend the existing link/create
  tests with a "propagates to siblings" assertion:
  - `link_to_job` happy path: linking E2 also sets E1, E3 if they're
    in the same thread and null.
  - Same for `link_to_po` and `link_to_bill`.
  - `create_job_from_email` happy path: the new Job's FK lands on
    every thread member.
  - `create_po_from_email` same.
- **`tests/test_outbound_email.py`** —
  `IMAPFetchPopulatesHeadersAndCorrelatesTest` extension: when
  `correlate_reply` sets a new inbound's Job FK from a parent
  linked to that Job, a thread sibling that was previously orphaned
  (e.g., an earlier inbound that lost its association during a
  prior bug, or a sibling reply that arrived out-of-order) gets
  picked up too.

## 7. Files touched

| File | Change |
|---|---|
| `apps/core/email_utils.py` | New `collect_thread_member_ids(email_record)` helper |
| `apps/core/services.py` | New `EmailService.propagate_thread_association`; one-line call at end of `associate_with`; per-field call after `correlate_reply`'s `.update()` |
| `tests/test_email_utils.py` | `CollectThreadMemberIdsTest` |
| `tests/test_email_models.py` | `PropagateThreadAssociationTest` |
| `tests/test_api_email.py` | Sibling-propagation assertions on the existing link/create tests |
| `tests/test_outbound_email.py` | Sibling-propagation assertion on the IMAP-fetch-correlation test |
| `docs/designs/architecture-and-conventions.md` | Update §7.11 (reply correlation) to mention the new propagation step downstream of correlate_reply; add a short §7.11a or extend §7.11 covering the propagation behavior end-to-end |

No SPA work. The action panel + email-detail page already render the
current association state correctly; once the backend propagates,
the next page load (or `onChange` callback after a link/create
action) picks up the new state automatically.

## 8. Docs to update post-implementation

`docs/designs/architecture-and-conventions.md` §7.11 (reply
correlation) gets a short addition describing the propagation: when
an EmailRecord's FK is set via `associate_with`, the same FK
propagates to other thread members whose value is null, computed
via the RFC 5322 thread graph (Message-ID + In-Reply-To +
References). Cite the helper functions and note the non-overwriting
behavior.

`docs/designs/data-constraints.md` §1.27 EmailRecord: optional
sentence noting that the three association FKs (`job`,
`purchase_order`, `bill`) propagate within a thread when set —
they're not strictly per-email invariants in practice, even though
the schema treats them as such.

## 9. Out of scope / future

1. **UI affordance distinguishing auto-linked vs manually-linked
   associations.** Considered and rejected in the original
   action-panel brainstorm. Reconsider only if real complaints
   surface about confusion over how a sibling email got linked.

2. **Propagation on disassociate.** The user explicitly opted out
   of this — "the previous ones can still be removed from it by
   hand" implies disassociate is a per-email surgical tool, not a
   thread-level one.

3. **Thread view in the SPA.** Showing all emails in a thread
   together (with their shared and individual associations) would
   be a real UX improvement separate from this work. Sequence after
   this lands so the thread view has correctly-propagated
   association data to render from.

4. **Bulk operations across a thread** ("mark whole thread as
   read," "delete whole thread"). Different feature, different
   scope.

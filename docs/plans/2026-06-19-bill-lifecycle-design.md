# Bill Lifecycle — Payments & PO Linking (Design)

**Date:** 2026-06-19
**Status:** Design approved.
**Owning docs to update on implementation:** `docs/designs/materials-inventory-and-purchasing.md` (§13 Bill, §9–11 PO↔Bill), `docs/designs/quickbooks-integration.md` (push/poll), `docs/designs/invoicing-and-expenses.md` (Bill payment lifecycle pointer)

## 1. Goal

Two related improvements to the Bill lifecycle:

1. **Distinguish "we sent a payment" from "the payment cleared."** Capture payment-OUT details we record ourselves (check number, CC receipt, method, amount, date) separately from bank-clearance-IN data that QBO reconciliation reports back later. The Bill's *lifecycle standing* does not wait on clearance — clearance is confirmation metadata, not a gating state.
2. **Make linking a Bill to its PO low-friction and safe.** Keep Bill creation manual, but turn "create/link a Bill from an existing PO" into a first-class action (incl. the email-to-Bill flow finding the right PO), with derived guardrails against accidental double-billing. No bill-ahead, no PO↔Bill schema change.

## 2. Key decisions (resolved in brainstorming)

**Payments**

- **One "paid" lifecycle, not two states.** A sent-but-uncleared payment does *not* hold the Bill in a separate status. (Chosen over a distinct "Payment Sent" state — no realistic workflow needs to act on the gap.)
- **Payments are child records (`BillPayment`), not fields on the Bill.** Installments happen; each check/charge is its own row and clears independently.
- **Bill status is derived** from sum-of-payments vs. total, not manually toggled.
- **Payment recording happens in Minibini** (hybrid model) and pushes to QBO immediately. **Clearance comes back via polling.**
- **QBO architecture: push distributed per-action, poll unified.** Push stays on each action (`push_invoice`/`push_bill`/`push_bill_payment`). Polling consolidates into one inbound service that sweeps all types.
- **The entire QBO side is stubbed today** — Minibini-native pieces built for real and fully testable without live Intuit; QBO push + poll behind seams to be wired in the upcoming QBO session.

**PO ↔ Bill**

- **No auto-draft Bill ("bill-ahead").** Rejected: it materializes a guessed PO→Bill mapping before the real invoice arrives and adds lifecycle-coupling machinery (auto-delete-on-cancel, re-issue idempotency) for little gain.
- **Keep the existing single FK `Bill.purchase_order`. No many-to-many.** The common direction — *several Bills against one PO* (partial deliveries / backorders) — is already what the single FK supports. The rare reverse direction (one Bill spanning multiple POs) is explicitly out of scope; if it ever lands it's a separate change.
- **The PO gets no payment/billing status field.** Receiving and billing are independent axes. "How much of this PO is billed" is **derived**, never stored.
- **Double-billing is surfaced, not blocked.** The only hard refusal is the pre-existing one: you cannot bill a `draft` PO. Beyond that, two derived tiers of *surfacing* (see §11), no lock.
- **The email-to-Bill flow finds the PO** rather than creating/matching a placeholder Bill (see §8).

## 3. `BillPayment` model

New model in `apps/purchasing/models.py`, `db_table='bill_payments'`, `@history`-decorated.

| Field | Type | Origin | Notes |
|---|---|---|---|
| `bill` | FK `Bill` CASCADE | — | Parent |
| `amount` | `Decimal(10,2)` | OUT | `> 0` |
| `payment_date` | `DateTimeField` | OUT | When we paid |
| `method` | choices: `check` / `credit_card` / `ach` / `cash` / `other` | OUT | |
| `reference` | `CharField` blank | OUT | Check #, CC receipt, confirmation # |
| `created_by` | FK `core.User` SET_NULL | OUT | Recorder |
| `created_date` | `DateTimeField` default now | OUT | |
| `qbo_payment_id` | `CharField` blank default `''` | IN | Set by poller; QBO BillPayment id |
| `cleared_date` | `DateTimeField` null | IN | Null until reconciliation confirms; set by poller |

**Payment OUT vs. clearance IN is the load-bearing split:** OUT fields are user-entered and editable (while the Bill is non-terminal); IN fields are written *only* by the polling service and are read-only in the UI.

**Validation:** `amount > 0`; cannot add a payment to a `draft`, `cancelled`, or `refunded` Bill.

## 4. Derived Bill status + `BillPaymentService`

A new `BillPaymentService` (`apps/purchasing/services.py`) is the sole writer of `BillPayment` rows and the recomputer of `Bill.status`:

| Method | Effect |
|---|---|
| `record_payment(bill, *, amount, payment_date, method, reference, user)` | Create `BillPayment`, recompute Bill status, call `QBOBillSyncService.push_bill_payment` (stub) |
| `update_payment(payment, **out_fields)` | Edit OUT fields (non-terminal Bill only), recompute status |
| `delete_payment(payment)` | Remove a recorded payment, recompute status |

**Status derivation** (`amount_paid = sum(BillPayment.amount)`, `total = sum(BillLineItem.amount)`):

| Condition | `Bill.status` |
|---|---|
| `amount_paid == 0` | `received` |
| `0 < amount_paid < total` | `partly_paid` |
| `amount_paid >= total` | `paid_in_full` |

Status is only derived once a Bill is past `draft` (a draft Bill has no payments). `receive` and `cancel` remain explicit user actions. The old manual **`mark_paid`** status action is **removed** — recording a payment is the only path to `partly_paid` / `paid_in_full`.

**Status-machine change required.** The current machine is forward-only; derived status must move **backward** when payments are deleted/edited (`partly_paid → received`, `paid_in_full → partly_paid`). Implementation: the payment-driven recompute sets `Bill.status` through a dedicated path that permits these reversals (lean: a `BillPaymentService` recompute that bypasses the forward-only guard, keeping the user-facing transition machine otherwise honest). `refunded` stays a manual terminal action out of `paid_in_full`.

**Balance fix (free win):** balance is now exactly `total − amount_paid`. The "coarse balance" wart noted in `materials-inventory-and-purchasing.md` §13/§15 and the planned `qbo_amount_paid`-on-Bill cache are both obsoleted — real per-payment amounts replace them.

## 5. Pay-in-full shortcut

A **"Pay in full"** affordance on the Bill detail that opens the same `RecordPaymentModal` **pre-filled with the outstanding balance** as the amount. It is *not* one-click — the user still must enter method, reference, and date before saving. It is a convenience pre-fill over the general Record Payment path, sharing one code path (`record_payment`).

## 6. QBO push seam (stubbed today)

`QBOBillSyncService.push_bill_payment(payment)`:

1. Ensure the Bill exists in QBO — call `push_bill(bill)` if `bill.qbo_id` is unset (today `push_bill` exists but is unwired).
2. Create a QBO `BillPayment` against it; persist `qbo_payment_id` on the Minibini `BillPayment`.

**Today:** real signature, logged to `QBOSyncLog`, guarded behind the no-live-QBO seam — no Intuit calls. Called immediately on `record_payment` (push-on-every-action). Failure is swallowed-and-logged for now; inbound clearance polling self-heals state later regardless. Block-vs-retry policy is a per-action decision to finalize when wired live.

## 7. Unified inbound polling (bill branch stubbed)

Consolidate inbound QBO polling into **one** service that sweeps all inbound types, per the "push distributed, poll unified" architecture:

- The existing live invoice branch (`QBOPaymentPollingService.poll_all`) is unchanged in behavior.
- The parked `QBOBillPaymentPollingService` is folded in as the **bill-clearance branch**, reframed to write per-`BillPayment` `cleared_date` / `qbo_payment_id` from QBO reconciliation data (not the old `Bill.qbo_payment_status` cache).
- The bill branch is **stubbed today** (interface present, guarded no-op without live QBO); the single `poll_qbo_payments` command drives the unified service.
- Future inbound types already noted (Job-P&L actuals, CDC reverse-sync) are meant to live under this same umbrella.

## 8. Email → Bill: find the PO

With no auto-draft Bill and no M2M, the email-to-Bill job is simply: **create a Bill, find and link the right (single) PO if one exists.** A three-tier fallback:

1. **Reply-correlated (best case).** A PO sent to a vendor carries a Message-ID; an inbound reply whose `In-Reply-To` matches auto-links to that PO (existing reply-correlation machinery, `architecture-and-conventions.md` §7.11). If the vendor's invoice email is a reply to the PO email, that PO is **pre-selected** — no guessing.
2. **Vendor-scoped pick.** No thread correlation, but the sender resolves to a known vendor → present that vendor's billable POs (`issued` / `partly_received` / `received_in_full`, cancelled excluded by default), annotated with their derived billed status (§11), for the user to pick.
3. **No PO.** No match → create a PO-less Bill (the rare legitimate hand-add).

This enhances the existing create-Bill-from-email flow (`?email=&vendor=`) to additionally find/pre-select a PO. The §11 double-bill surfacing applies once a PO is chosen.

## 9. UI surfaces

- **Bill detail (`BillDetailPage.svelte`):**
  - New **Payments** section listing each `BillPayment` — OUT details (method, reference, amount, date) plus a clearance badge (`pending` / `cleared <date>`). **Record Payment** and **Pay in full** buttons (gated `can_manage_financials`, shown when Bill is `received` / `partly_paid`). New `RecordPaymentModal`. Remove the old "Mark Paid in Full" button.
  - **Linked-PO area:** the linked PO (if any), plus the §11 surfacing — an informational "this PO already has Bill(s): [links]" notice and, when the value test trips, the fully-billed warning banner. Both persist on the Bill, not just at create time.
- **Bill form (`BillFormPage.svelte`):** a **PO picker** (vendor-filtered, `issued`+ POs) as a first-class control, replacing reliance on the `?po=` URL param alone (which still works). Selecting a PO auto-fills the vendor and offers to copy the PO's line items as a starting point. The §11 surfacing renders inline as soon as a PO is chosen.
- **Bill list (`BillListPage.svelte`):** Balance column becomes exact (`total − amount_paid`); drop the coarse-balance caveat.
- **PO detail (`PurchaseOrderDetail.svelte`):** show the PO's Bills and its derived billed status (e.g. "Billed $1,240 / $1,240 — fully billed", or "Billed $0 / $1,240").

## 10. API

**Payments**
- `POST /api/bills/{id}/payments/` — record a payment (`BillPaymentService.record_payment`). `can_manage_financials`.
- `PATCH /api/bills/{id}/payments/{pid}/` — edit OUT fields.
- `DELETE /api/bills/{id}/payments/{pid}/` — delete a payment (200 + JSON body per the all-DELETEs-return-200 convention).
- Remove the `mark_paid` status action from `BillViewSet`. Keep `receive`, `cancel`.
- `BillSerializer` / `BillSummarySerializer` expose `amount_paid`, exact `balance`, and nested payments (clearance fields read-only).

**PO linking / billed status**
- PO picker uses the existing PO list filtered by vendor + billable statuses (e.g. `GET /api/purchase-orders/?business=<id>&billable=true`).
- `PurchaseOrderSerializer` exposes derived `billed_total`, `is_fully_billed`, and a lightweight `bills` list (id / number / status / total) for the PO-detail and the surfacing notices.
- `BillSerializer` exposes the linked PO plus a derived `po_billing` hint block (`other_bills`: existing non-cancelled Bills on the same PO with links; `po_fully_billed`: bool) so the Bill detail/form can render the two-tier surfacing without extra round-trips.

## 11. PO ↔ Bill linking, derived billing, and double-bill surfacing

**Link model (unchanged schema).** `Bill.purchase_order` stays a nullable FK (`PROTECT`). Linking is setting that FK — via create-from-PO, the PO picker, or the email flow. Existing `Bill.clean()` rule kept: a linked PO must be `issued` or later (never `draft`). This is the **only hard refusal.** (PROTECT is effectively moot — a PO is deletable only while `draft`, and a draft PO can't carry a Bill.)

**Derived PO billing (no stored status).** On `PurchaseOrder`:
- `billed_total` — `Sum` of `total` over non-cancelled Bills linked to this PO.
- `po_total` — `Sum` of its line items.
- `is_fully_billed` — `billed_total >= po_total` (and `po_total > 0`).
- `bills` reverse accessor (`related_name='bills'` on the FK) for the surfacing queries.

**Two-tier surfacing at create/link time and persistently on the Bill** (neither blocks):

1. **Informational — any prior Bill.** Whenever a Bill is added to (or linked to) a PO that already has ≥1 non-cancelled Bill, show "This PO already has Bill(s): [INV-… link, …]". Always shown, regardless of value — so the user can spot a duplicate even before the PO is fully billed.
2. **Warning banner — value test.** When `is_fully_billed` is true, escalate to a prominent ⚠ banner: "PO-… is already fully billed (Bill INV-…, $… — fully received). Add another Bill anyway?" Receipt status is shown as supporting context; the **trigger is value coverage**, not receipt. Still non-blocking, consistent with the "don't hard-confirm reversible actions" UI convention (a draft Bill is deletable).

## 12. Testing (TDD)

Backend (Django `TestCase`, separate test DB — never touch dev DB):
- `BillPayment` validation (amount > 0; rejected on draft/terminal Bill).
- Status derivation across add/edit/delete, including backward transitions (`partly_paid → received`, `paid_in_full → partly_paid`).
- Exact balance computation.
- `push_bill_payment` stub invoked on `record_payment` and logs to `QBOSyncLog` without live calls.
- Unified poller bill branch is a guarded no-op without live QBO; invoice branch unchanged.
- Derived PO billing: `billed_total` excludes cancelled Bills; `is_fully_billed` boundary (`==`, just-under, over); `po_total == 0` guard.
- Linking a Bill to a `draft` PO is rejected; to `issued`+ accepted.
- Surfacing data: `other_bills` populated when prior Bills exist; `po_fully_billed` flips exactly at value coverage.

Frontend (Vitest, `frontend/tests/`):
- `RecordPaymentModal` validation and submit.
- Pay-in-full pre-fills balance but still requires method/reference/date.
- Bill detail payments list renders OUT details + clearance badge.
- Exact balance in list.
- PO picker filters to vendor + billable; informational notice renders when prior Bills exist; warning banner renders only when fully billed.

## 13. Out of scope / deferred

- **One Bill spanning multiple POs (M2M).** Rejected for now; revisit as a separate change if real demand appears.
- **Auto-draft / bill-ahead.** Rejected.
- Live QBO bill-payment push and clearance polling — stubbed; wired in the upcoming QBO session.
- Refund modeling beyond the existing manual `paid_in_full → refunded` transition.
- Line-item-level Bill↔PO reconciliation — the link is header-level only.
- Employee-as-Vendor and other unrelated QBO unfinished-work items.

## 14. Open questions

1. Backward-status mechanism — dedicated bypass recompute in `BillPaymentService` (lean) vs. adding reverse transitions to `VALID_TRANSITIONS`.
2. Whether editing/deleting a *cleared* payment should be blocked once polling is live (a cleared payment reflects real bank movement) — probably yes; not enforced while QBO is stubbed.
3. Vendor-scoped PO picker default filter — exclude cancelled/fully-billed POs entirely, or show them de-emphasized for the occasional legitimate late invoice.

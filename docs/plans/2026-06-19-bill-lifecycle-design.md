# Bill Lifecycle — Payments & Auto-Draft-from-PO (Design)

**Date:** 2026-06-19
**Status:** Design approved; email-flow section deferred (see §8)
**Owning docs to update on implementation:** `docs/designs/materials-inventory-and-purchasing.md` (§13 Bill), `docs/designs/quickbooks-integration.md` (push/poll), `docs/designs/invoicing-and-expenses.md` (Bill payment lifecycle pointer)

## 1. Goal

Two related improvements to the Bill lifecycle:

1. **Distinguish "we sent a payment" from "the payment cleared."** Capture payment-OUT details we record ourselves (check number, CC receipt, method, amount, date) separately from bank-clearance-IN data that QBO reconciliation reports back later. The Bill's *lifecycle standing* does not wait on clearance — clearance is confirmation metadata, not a gating state.
2. **Auto-generate a draft Bill with every issued PO**, pre-filled from the PO, so Bills rarely need to be added by hand. The draft Bill is editable until the real vendor invoice arrives and it is marked `received`.

## 2. Key decisions (resolved in brainstorming)

- **One "paid" lifecycle, not two states.** A sent-but-uncleared payment does *not* hold the Bill in a separate status. (Chosen over a distinct "Payment Sent" state — no realistic workflow needs to act on the gap.)
- **Payments are child records (`BillPayment`), not fields on the Bill.** Installments happen; each check/charge is its own row and clears independently.
- **Bill status is derived** from sum-of-payments vs. total, not manually toggled.
- **Payment recording happens in Minibini** (hybrid model) and pushes to QBO immediately. **Clearance comes back via polling.**
- **QBO architecture: push distributed per-action, poll unified.** Push stays on each action (`push_invoice`/`push_bill`/`push_bill_payment`). Polling consolidates into one inbound service that sweeps all types.
- **The entire QBO side is stubbed today** — Minibini-native pieces built for real and fully testable without live Intuit; QBO push + poll behind seams to be wired in the upcoming QBO session.
- **Auto-draft Bill is created on PO issue, deleted on PO cancel** (only while still draft). It is a user convenience, not a historical artifact.

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

**Status-machine change required.** The current machine is forward-only; derived status must move **backward** when payments are deleted/edited (`partly_paid → received`, `paid_in_full → partly_paid`). Implementation: the payment-driven recompute sets `Bill.status` through a path that permits these reversals (either add the reverse transitions to `VALID_TRANSITIONS`, or have `BillPaymentService` set status via a dedicated recompute that bypasses the forward-only guard). `refunded` stays a manual terminal action out of `paid_in_full`.

**Balance fix (free win):** balance is now exactly `total − amount_paid`. The "coarse balance" wart noted in `materials-inventory-and-purchasing.md` §13/§15 and the planned `qbo_amount_paid`-on-Bill cache are both obsoleted — real per-payment amounts replace them.

## 5. Pay-in-full shortcut

A **"Pay in full"** affordance on the Bill detail that opens the same `RecordPaymentModal` **pre-filled with the outstanding balance** as the amount. It is *not* one-click — the user still must enter method, reference, and date before saving. It is a convenience pre-fill over the general Record Payment path, sharing one code path (`record_payment`).

## 6. QBO push seam (stubbed today)

`QBOBillSyncService.push_bill_payment(payment)`:

1. Ensure the Bill exists in QBO — call `push_bill(bill)` if `bill.qbo_id` is unset (today `push_bill` exists but is unwired).
2. Create a QBO `BillPayment` against it; persist `qbo_payment_id` on the Minibini `BillPayment`.

**Today:** real signature, logged to `QBOSyncLog`, guarded behind the no-live-QBO seam — no Intuit calls. Called immediately on `record_payment` (push-on-every-action). Failure is swallowed-and-logged for now; inbound clearance polling self-heals state later regardless. Block-vs-retry policy is a per-action decision to finalize when wired live.

## 7. Unified inbound polling (bill branch stubbed)

Consolidate inbound QBO polling into **one** service that sweeps all inbound types, per the "push distributed, poll unified" architecture. Concretely:

- The existing live invoice branch (`QBOPaymentPollingService.poll_all`) is unchanged in behavior.
- The parked `QBOBillPaymentPollingService` is folded in as the **bill-clearance branch**, reframed to write per-`BillPayment` `cleared_date` / `qbo_payment_id` from QBO reconciliation data (not the old `Bill.qbo_payment_status` cache).
- The bill branch is **stubbed today** (interface present, guarded no-op without live QBO); the single `poll_qbo_payments` command drives the unified service.
- Future inbound types already noted (Job-P&L actuals, CDC reverse-sync) are meant to live under this same umbrella.

## 8. Email → Bill reframe — **DEFERRED, NEEDS MORE THOUGHT**

> This section is intentionally unresolved. Revisit with the user before implementing.

With auto-draft Bills, the vendor-invoice email almost always corresponds to a Bill that **already exists** (created when the PO was issued). The email-to-bill flow should therefore **match and update the existing draft Bill** — fill in the real `vendor_invoice_number`, due date, confirm amounts, and mark `received` — rather than minting a second Bill (today's `EmailCreateBill` create-new behavior, the `?email=&vendor=` flow, and the email-associate-bill picker).

**Open sub-questions to work through:**
- How does the flow pick *which* draft Bill to match — by the PO the email thread correlates to (via reply correlation / `In-Reply-To`), by vendor, or by presenting a picker?
- Behavior when several draft Bills exist for one vendor.
- The rare genuinely-no-PO case where create-new is still correct must survive.
- Interaction with the existing email↔PO reply-correlation machinery.

No implementation of this section until it is designed.

## 9. UI surfaces

- **Bill detail (`BillDetailPage.svelte`):** new **Payments** section listing each `BillPayment` — OUT details (method, reference, amount, date) plus a clearance badge (`pending` / `cleared <date>`). **Record Payment** and **Pay in full** buttons (gated `can_manage_financials`, shown when Bill is `received` / `partly_paid`). New `RecordPaymentModal`. Remove the old "Mark Paid in Full" button.
- **Bill list (`BillListPage.svelte`):** Balance column becomes exact (`total − amount_paid`); drop the coarse-balance caveat.
- **PO detail:** no new control needed — the draft Bill simply appears in the vendor's/PO's Bill surfaces after issue.

## 10. API

- `POST /api/bills/{id}/payments/` — record a payment (`BillPaymentService.record_payment`). `can_manage_financials`.
- `PATCH /api/bills/{id}/payments/{pid}/` — edit OUT fields.
- `DELETE /api/bills/{id}/payments/{pid}/` — delete a payment (200 + JSON body per the all-DELETEs-return-200 convention).
- Remove the `mark_paid` status action from `BillViewSet`. Keep `receive`, `cancel`.
- `BillSerializer` / `BillSummarySerializer` expose `amount_paid`, exact `balance`, and nested payments (with clearance fields read-only).

## 11. Auto-draft Bill from PO

- **On PO `draft → issued`** (side-effect in the PO issue path / `PurchaseOrderService`): create one draft Bill via `BillService.create_bill_from_po(po)` (copies vendor + line items). **Idempotency guard:** skip if a Bill already references this PO (so reverse→re-issue doesn't duplicate).
- **On PO `→ cancelled`:** delete the linked Bill **iff it is still `draft`** (placeholder, safe to delete). A Bill that already advanced to `received`/paid is left untouched.
- One auto Bill per PO; additional hand-added Bills for the same PO remain possible (rare — e.g. multiple vendor invoices against one PO).

## 12. Testing (TDD)

Backend (Django `TestCase`, separate test DB — never touch dev DB):
- `BillPayment` validation (amount > 0; rejected on draft/terminal Bill).
- Status derivation across add/edit/delete, including backward transitions (`partly_paid → received`, `paid_in_full → partly_paid`).
- Exact balance computation.
- Auto-draft Bill created on PO issue; idempotent on re-issue; deleted on cancel only while draft; untouched when received/paid.
- `push_bill_payment` stub invoked on `record_payment` and logs to `QBOSyncLog` without live calls.
- Unified poller bill branch is a guarded no-op without live QBO; invoice branch unchanged.

Frontend (Vitest, `frontend/tests/`):
- `RecordPaymentModal` validation and submit.
- Pay-in-full pre-fills balance but still requires method/reference/date.
- Bill detail payments list renders OUT details + clearance badge.
- Exact balance in list.

## 13. Out of scope / deferred

- Email → Bill matching flow (§8) — explicitly deferred.
- Live QBO bill-payment push and clearance polling — stubbed; wired in the upcoming QBO session.
- Refund modeling beyond the existing manual `paid_in_full → refunded` transition.
- Employee-as-Vendor and other unrelated QBO unfinished-work items.

## 14. Open questions

1. **§8 email flow** — the whole matching design.
2. Backward-status mechanism — reverse transitions in `VALID_TRANSITIONS` vs. a dedicated bypass in `BillPaymentService` (lean: dedicated recompute, keeps the user-facing machine honest).
3. Whether editing/deleting a *cleared* payment should be blocked (a cleared payment reflects real bank movement) — probably yes once polling is live; not enforced while QBO is stubbed.

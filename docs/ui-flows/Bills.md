# Bills — UI flow

**Purpose:** A from-the-user's-perspective walkthrough of the full Bill
lifecycle — receiving a vendor invoice, recording payments against it, linking
it to a purchase order, and the double-bill safeguards. It guides manual/user
testing today and is intended to seed the automated UI test platform later —
each checklist item maps to an assertion. Keep it current as the Bill UI evolves.

**Model (2026-06 payment-lifecycle work):** a Bill is a vendor invoice,
optionally linked to one `PurchaseOrder` (single FK — a bill belongs to at most
one PO; one PO may have many bills). Payments are **child records**
(`BillPayment`): each records what we paid out (amount, method, reference, date)
plus clearance data that QBO reconciliation fills in later. **Bill status is
derived from payments**, never set by hand:

| Status | Meaning |
|---|---|
| `draft` | Being built; header + line items editable; deletable |
| `received` | The real vendor invoice is matched; `amount_paid == 0` |
| `partly_paid` | `0 < amount_paid < total` |
| `paid_in_full` | `amount_paid >= total` |
| `cancelled` | Terminal; from `received` with a reason |
| `refunded` | Terminal; manual, from `paid_in_full` |

Status moves **backward** automatically when payments are removed
(`paid_in_full → partly_paid → received`). **Balance is exact**: `total −
amount_paid` for active bills, and **$0.00** for `paid_in_full` / `cancelled` /
`refunded` (you owe nothing on a terminal bill). See
`docs/designs/materials-inventory-and-purchasing.md` §13 and
`docs/plans/2026-06-19-bill-lifecycle-design.md`.

## Personas

- **Viewer** — any authenticated user, no atoms. Can view the bill list and bill
  detail, but sees **no** New Bill / Record Payment / Pay in full / Receive /
  Cancel / Delete / Edit controls.
- **Financials** — holds `can_manage_financials`. Full CRUD: create bills,
  receive, record/edit/delete payments, cancel, delete drafts, link POs.

## Dev note — QuickBooks is stubbed

QBO push and clearance polling are **stubbed** for this phase:
- Recording a payment **works fully offline** — the QBO push is a logged no-op,
  so no QBO connection is needed and nothing errors.
- **Clearance never populates in dev.** A payment's clearance badge stays
  **"pending"** forever because the bill-clearance poller is a stub; `cleared
  <date>` only appears once the live QBO poller lands. Pending-forever is
  **expected, not a bug**.

## Prerequisites (test-data setup)

- [ ] **A Business (vendor)** with a `default_contact` — every Bill needs a
  vendor; the form's Vendor dropdown lists businesses.
- [ ] **An *issued* (or later) PurchaseOrder** with line items, on that vendor —
  needed for create-from-PO (§1), PO linking, and the surfacing flows (§7).
- [ ] **A *draft* PurchaseOrder** — to exercise the "can't bill a draft PO" guard
  (§7).
- [ ] **An AccountingCategory** — for bill line items.
- [ ] **Two users** — a plain authenticated **Viewer** and a
  `can_manage_financials` **Financials** user — for the persona-gated steps.
- [ ] **(Email flow, §8) an inbound vendor email that is a reply to a PO we
  sent** — so the reply is auto-correlated to that PO. Harder to stage in dev; if
  you can't, test §8's no-correlation branch only and note the gap.

---

## 1. Creating a bill — the entry points

Routes: list `#/bills`; create `#/bills/new`; detail `#/bills/{id}`; edit
`#/bills/{id}/edit` (draft only).

- [ ] **New Bill button (persona):** on `#/bills`, **New Bill** is visible to
  **Financials** only; absent for a **Viewer**.
- [ ] **From a PO (the common path):** `#/bills/new` → use the **Purchase
  order…** picker (typeahead). It lists only that **vendor's** `issued` /
  `partly_received` / `received_in_full` POs — **draft and cancelled POs are
  excluded**. Pick one → the vendor is filled in and the PO's line items are
  copied onto the new bill as a starting point.
- [ ] **From scratch (rare):** `#/bills/new` → pick a Vendor (Business),
  optionally a Contact, enter Vendor Invoice #, Due Date; leave the PO picker
  empty → save. A PO-less bill is created.
- [ ] **Guard — can't bill a draft PO:** if you reach the form with a draft PO
  (e.g. a hand-typed `?po=<draftPoId>`), saving is **refused** with a validation
  error. Only `issued`-or-later POs can carry a bill.
- [ ] **Edit is draft-only:** open a `received`-or-later bill's edit route
  (`#/bills/{id}/edit`) → it reports the bill can no longer be edited; only
  `draft` bills expose the header form.

## 2. Receiving — matching the real invoice

- [ ] **Mark Received:** on a `draft` bill's detail, **Financials** sees **Mark
  Received** (draft → `received`). After receiving, the bill is no longer
  editable/deletable and the payment controls appear.
- [ ] **No "Mark Paid in Full" button:** confirm it is **gone** from bill detail
  — the only way to reach `paid_in_full` is by recording payments (§3). (This is
  the deliberate replacement of the old manual action.)

## 3. Recording payments (the core)

On a `received` or `partly_paid` bill, **Financials** sees **Record Payment** and
**Pay in full**. Both open the **Record Payment** modal with fields **Amount**,
**Method** (Check / Credit Card / ACH / Cash / Other), **Reference** (check #,
receipt, confirmation #), **Date**.

- [ ] **Partial payment → partly_paid:** on a $200 received bill, Record Payment
  $50 (method Check, ref `4471`) → **Save**. Status flips to **partly paid**;
  **Balance** drops to **$150.00**; the payment appears in the **Payments**
  section showing method, reference, amount, and a **pending** clearance badge.
- [ ] **Covering the rest → paid_in_full:** record another $150 → status flips to
  **paid in full**; Balance shows **$0.00**.
- [ ] **Guard — amount required/positive:** Save with a blank or `0` amount →
  refused (error shown, no payment created).
- [ ] **Guard — can't pay a draft bill:** a `draft` bill exposes no payment
  controls; attempting a payment is refused.
- [ ] **Guard — can't pay a terminal bill:** a `cancelled` / `refunded` bill
  exposes no payment controls.
- [ ] **Persona:** a **Viewer** sees the Payments section read-only — no Record
  Payment / Pay in full / per-payment Delete.

## 4. Pay in full shortcut

- [ ] **Pre-fills the balance:** on a partly-paid bill with $150 outstanding,
  click **Pay in full** → the modal opens with **Amount pre-filled to 150.00**.
- [ ] **Still explicit:** it is **not** one-click — you must still choose Method
  and (optionally) Reference/Date and press **Save** before anything is recorded.

## 5. Editing & removing payments → backward status

- [ ] **Delete a payment moves status back:** on a `paid_in_full` bill, delete a
  payment from the Payments section (per-row **Delete**) → status drops back to
  **partly paid** (or **received** if nothing remains); Balance rises by the
  removed amount. No confirmation prompt — deleting a payment is reversible
  (re-record it), so it just happens.
- [ ] **Edit a payment recomputes:** edit a payment's amount so it no longer
  covers the total → status recomputes to **partly paid** accordingly.
- [ ] **Guard — can't edit a payment on a terminal bill:** editing a payment on a
  `cancelled` / `refunded` bill is refused.

## 6. Balances — exact, and zero on terminal

- [ ] **Active = exact:** a `received` bill with no payments shows Balance = its
  full total; a `partly_paid` bill shows the **exact remainder** (total −
  amount_paid), not the full total.
- [ ] **Cancelled = $0.00:** a `cancelled` bill shows **Balance $0.00** even if it
  was never paid — you owe nothing on a cancelled bill. *(This looks surprising if
  you expect the total; it is correct. Report a non-zero balance on a cancelled
  bill as a bug.)*
- [ ] **Paid/refunded = $0.00:** `paid_in_full` and `refunded` bills show $0.00.
- [ ] **List matches detail:** the `#/bills` list **Balance** column shows the
  same exact figures (it is server-computed, not derived in the browser).

## 7. PO linking & double-bill surfacing

A PO accepts **more than one** bill (partial deliveries / backorders). The UI
**surfaces** potential duplicates but never blocks them (except the draft-PO
guard in §1). Two tiers, shown on both the **create form** and the **bill
detail**:

- [ ] **Informational notice (any prior bill):** create/link a second bill to a
  PO that already has a non-cancelled bill → an info line **"This PO already has N
  other bill(s):"** with each prior bill as a **link** to its detail.
- [ ] **Warning banner (fully billed):** when existing non-cancelled bills already
  cover the PO's full total → a prominent **"⚠ {po_number} is already fully
  billed. Check for a duplicate before paying."** banner. It does **not** block —
  you can still proceed.
- [ ] **Multiple bills allowed:** confirm a second bill against one PO actually
  saves (the partial-delivery case) — the surfacing is advisory only.
- [ ] **Cancelled bills don't count:** a cancelled bill on the PO is **not**
  listed in "other bills" and does not contribute to the fully-billed test.

## 8. PO detail — billed status

- [ ] **Billed vs. total:** on `#/purchase-orders/{id}`, the PO shows **"Billed:
  $X / $Y"** where Y is the PO total and X is the sum of its non-cancelled bills.
- [ ] **Fully-billed marker:** once bills cover the total, a **"— fully billed"**
  marker appears alongside it.

## 9. Email → Bill finds the PO

From an email's detail, the **Create bill** action opens the email-create-bill
page (`#/email/{id}/create-bill`), which resolves the sender to a vendor and
navigates to `#/bills/new` pre-filled.

- [ ] **Reply-correlated PO pre-selected:** when the vendor's invoice email is a
  reply to a PO we sent (so it's auto-linked to that PO), the new-bill form opens
  with **that PO already selected** in the picker (and the §7 surfacing showing).
- [ ] **No correlation → plain create:** an email with no PO association opens the
  form with the **vendor filled but no PO** selected; you can pick one or leave it
  blank (PO-less bill).

## 10. Cancel & delete guards

- [ ] **Cancel requires a reason:** on a `received` bill, **Cancel** (Financials)
  prompts for a reason; submitting without one is refused. After cancel → status
  `cancelled`, Balance $0.00 (§6).
- [ ] **Delete is draft-only:** **Delete** is offered only on `draft` bills;
  `received`-or-later bills cannot be deleted (cancel is the path instead).

## 11. Permissions summary

- [ ] **Viewer (no atom):** list + detail are visible; **every** write control
  (New Bill, Mark Received, Record Payment, Pay in full, payment Delete, Cancel,
  Delete, Edit) is absent. A direct write attempt (e.g. crafted request) returns
  403.
- [ ] **Financials:** all of the above are available.

---

## Coverage matrix

| Dimension | Cases |
|---|---|
| Creation | from PO (line items copied) · from scratch (PO-less) · from email (PO pre-selected / none) |
| PO-link guard | issued+ PO accepted · draft PO refused · cancelled/draft excluded from picker |
| Status (derived) | draft → received · received → partly_paid → paid_in_full · received → cancelled · paid_in_full → refunded |
| Backward status | delete payment: paid_in_full → partly_paid → received · edit payment recomputes |
| Payment fields | amount (>0 guard) · method (check/credit_card/ach/cash/other) · reference · date |
| Payment guards | none on draft · none on cancelled/refunded · edit refused on terminal |
| Balance | active = exact (total − paid) · cancelled = 0 · paid_in_full = 0 · refunded = 0 · list matches detail |
| Double-bill surfacing | info notice (any prior bill, linked) · warning banner (fully billed) · non-blocking · cancelled excluded · shown on form + detail |
| PO detail | billed/total figure · fully-billed marker |
| Clearance (stubbed) | badge stays "pending" in dev (expected) |
| Persona | Viewer (read-only, no controls) · Financials (full CRUD) |
| Cancel/delete | cancel requires reason · delete draft-only |

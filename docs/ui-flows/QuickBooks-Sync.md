# QuickBooks Sync — UI flow

**Purpose:** A from-the-user's-perspective walkthrough of the QuickBooks
**push** behaviours added in the 2026-06 QBO work — recording a bill payment
with a payment-account picker, the per-record sync state (synced / sync
failed), and the **delete symmetry** that refuses a local delete when its QBO
void fails. It spans bill payments, company expenses, and reimbursement
batches because they now share one sync model (`QBOSyncable` +
`QBOSyncService`). It guides manual/user testing today and is intended to seed
the automated UI test platform later — each checklist item maps to an
assertion. Keep it current as the QBO UI evolves. Cross-links: `Bills.md` §3
(recording payments), `Expenses.md` (expense lifecycle).

**Model (2026-06 QBO push work):** every QBO-mirrored record (`BillPayment`,
`Expense`, `Reimbursement` batch) carries a **sync state** — `pending` →
`synced` (has a `qbo_id`) or `sync_failed` (carries an error). Creating/editing
the record pushes to QBO; **a QBO failure never blocks the local write** — it
just lands the row in `sync_failed`, which is visible and retryable. Deleting is
the exception: a **failed QBO delete refuses the local delete** and keeps the
row (so QBO and Minibini can't silently diverge). See
`docs/designs/quickbooks-integration.md` (Shared sync scaffolding, Bill payment
push).

## Personas

- **Viewer** — any authenticated user, no atoms. Sees lists/detail and the sync
  badges, but **no** Record Payment / Edit / Delete / expense-delete controls.
- **Financials** — holds `can_manage_financials`. Records/edits/deletes bill
  payments, deletes company expenses, creates/deletes reimbursement batches.
- **Config** — holds `can_manage_config`. Configures the QBO connection and the
  **payment accounts** list in Settings (the source of the picker's options).

## Dev notes — environment caveats that look like bugs but aren't

- **Full push/void testing needs a connected QBO sandbox.** With QBO connected,
  recording pushes and rows go **synced**; deleting voids in QBO. **Without** a
  connection you can still test: the require-account guard (§2), the
  disconnected→`sync_failed` marking (§4), and that the local write still
  commits. See `docs/designs/quickbooks-integration.md` Appendix for connecting.
- **Payment accounts must be configured first.** The Record Payment picker (and
  the expense/reimbursement account pickers) read `Configuration['qbo_payment_accounts']`,
  populated in Settings (§1). With none configured the picker shows a disabled
  **"No payment accounts configured."**
- **Recording while disconnected marks `sync_failed`, not `pending`.** Because
  the push raises "No active QBO connection," every record made offline shows
  **sync failed — retry**. Expected and consistent; not a bug.
- **Clearance polling is still stubbed** (separate from push). A bill payment's
  **clearance** badge stays "pending" forever in dev even after a successful
  push — `cleared <date>` only lands when the inbound poller ships. Push success
  (the **synced** indicator / QBO id) is the thing to verify here, not clearance.

## Prerequisites (test-data setup)

- [ ] **A connected QBO sandbox** (for the §3/§5/§6 push & void paths) — or note
  which steps you're running in the disconnected-only mode.
- [ ] **At least one payment account** configured in Settings (§1) — a Bank one
  and a Credit Card one to exercise both PayType branches.
- [ ] **A `received` Bill** on a vendor with a QBO vendor record (for payments).
- [ ] **A company-paid Expense** (for the expense sync + delete steps).
- [ ] **A reimbursement batch** of personal expenses (for §10).
- [ ] **Two users** — a **Viewer** and a `can_manage_financials` **Financials** —
  plus a `can_manage_config` **Config** user for §1.

---

## 1. Setup — configure payment accounts (Config)

Route: `#/settings`.

- [ ] **Accounts come from QBO:** as **Config**, in the QBO section, the
  payment-account picker/list is populated from `/api/qbo/payment-accounts/`
  (Bank / Credit Card / Other Current Asset). Enable at least one Bank and one
  Credit Card account and save.
- [ ] **Empty state blocks recording (not just the dropdown):** with **no**
  payment accounts configured, the forms that need one don't let you proceed —
  the **Record Payment** modal shows a **"No payment accounts are configured — set
  them up in Settings → QuickBooks"** message *instead of* the input fields
  (§2); the reimbursement panel replaces its **Reimburse selected** button with
  the same hint (§10); and the expense form notes that **company-paid needs a
  configured account** under "Paid by". A payment account is **necessary info**,
  so without one these flows are gated, not merely awkward.

## 2. Recording a bill payment — the account picker & guard

On a `received` / `partly_paid` bill, **Financials** clicks **Record Payment**.
The modal has **Amount**, the **Payment account** picker, **Reference**, **Date**
— there is **no Method dropdown** (removed; the account + reference describe the
payment).

- [ ] **Account picker lists configured accounts:** the **Payment account**
  dropdown shows each account's **display name** (e.g. "Business Checking",
  "Visa"), not raw ids.
- [ ] **Account auto-selected:** when accounts are configured, the picker
  defaults to the first one (you can change it) — so the required field is
  pre-filled.
- [ ] **Guard — account required (always):** clear the account (pick the blank
  "— select account —" option) and Save → **blocked client-side** with **"Choose
  a payment account."**, no request sent. (The backend also rejects a blank
  account with 400 regardless of QBO connectivity — it's necessary info, not a
  QBO-only requirement.)
- [ ] **Errors state the reason:** a refused save shows the **specific** message
  (e.g. the field error), not a generic "Could not record payment." *(Report a
  generic/opaque failure message as a bug.)*
- [ ] **Records & commits locally:** choose an account, enter Amount/Reference →
  **Save** → the payment appears in the Payments section and the bill status /
  balance update (per `Bills.md` §3).

## 3. Push result — synced (QBO connected)

- [ ] **Synced indicator:** with QBO connected, after recording, the payment row
  shows a **synced** indicator (and a QBO id is set) — the BillPayment was pushed
  to QBO, linked to the bill.
- [ ] **Bank vs Credit Card:** a payment on a **Bank** account and one on a
  **Credit Card** account both push successfully (different QBO PayType under the
  hood; both should land **synced**).
- [ ] **Reference becomes the doc number:** a payment with a Reference pushes that
  as the QBO DocNumber (verify in QBO if you have access; otherwise just confirm
  **synced**).

## 4. Disconnected → sync failed (retryable)

Run with QBO **disconnected** (Settings → Disconnect, or no sandbox).

- [ ] **Local write still succeeds:** Record Payment with an account chosen →
  the payment is **created** and bill status/balance update normally.
- [ ] **Row shows sync failed + a Retry button:** the payment row shows **sync
  failed** (not pending) with the error in a tooltip, and a **Retry** button (the
  old text-only "— retry" is now a real control). The push raised "No active QBO
  connection."
- [ ] **(Reconnect) Retry button works:** once QBO is reconnected, click the
  row's **Retry** → it re-runs the *owed* operation (a failed create re-creates;
  a failed edit re-updates) and the row flips to **synced**. Editing the payment
  (§5) also re-attempts the push.

## 4a. Retry re-runs the operation that failed (not a blind re-push)

The retry knows which verb a `sync_failed` row owes (create / update / delete),
so it does the right thing — the key correctness fix.

- [ ] **Failed update retries as an update:** edit a **synced** payment while QBO
  is unreachable (the update fails → row shows sync failed); reconnect → **Retry**
  → the *edit* is actually re-applied to QBO (not silently marked synced with the
  old values).
- [ ] **Failed delete retries as a delete:** a payment whose delete was refused
  (§6) shows sync failed; **Retry** (or Delete again) **deletes** it — it does not
  flip back to synced.
- [ ] **Cross-entity failures panel (Settings):** as **Financials**, the Settings
  page shows a **QBO sync failures** panel listing every failed payment / company
  expense / reimbursement batch with its pending operation; a per-row **Retry**
  and a **Retry all** button. Retry-all re-runs each (one failure doesn't stop the
  rest) and reports how many are still failing.

## 5. Editing a synced payment → re-sync

- [ ] **Edit re-syncs:** on a **synced** payment, edit the Amount → Save → the
  QBO BillPayment is updated and the row stays **synced**.
- [ ] **Edit of a never-synced payment pushes fresh:** editing a payment that has
  no QBO id (e.g. recorded while disconnected) **creates** the QBO BillPayment on
  save → row flips to **synced**.

## 6. Deleting a synced payment — void symmetry (the key new behaviour)

Deleting a payment voids its QBO BillPayment **first**, then deletes locally.

- [ ] **Happy path:** with QBO connected, per-row **Delete** on a synced payment
  → the QBO BillPayment is voided, the payment is removed, and bill status moves
  backward (per `Bills.md` §5).
- [ ] **Refused on QBO failure (the headline):** make the QBO void fail (delete
  a synced payment while QBO is **unreachable**) → the delete is **refused**: an
  **error is shown** ("Could not delete … the payment was kept … retry"), the
  **payment still appears** in the list, and it is now marked **sync failed**.
  Bill status/balance are **unchanged**.
- [ ] **Retry = delete again:** with QBO reachable again, click **Delete** on that
  same retained payment → it now voids and removes. *(There is no separate retry
  control — re-invoking Delete is the retry.)*
- [ ] **Idempotent — already gone:** if the QBO BillPayment was already deleted in
  QBO out of band, Delete still **completes locally** (the not-found void counts
  as success) — the row is not stranded.
- [ ] **No-QBO-id payment deletes freely:** a payment with no `qbo_id` (recorded
  offline, never synced) deletes locally with no QBO call.
- [ ] **Persona:** a **Viewer** sees no Delete control on payments.

## 7. Bill detail payments table — display

- [ ] **Account name, not method:** each payment row shows the **payment
  account's display name** + the **Reference**, replacing the old "method" column.
  A payment with no resolvable account shows **—**.
- [ ] **Sync indicator per row:** rows show **synced** (has QBO id) or **sync
  failed** (with the error available on hover/title); a brand-new pending row
  shows neither until the push resolves.

## 8. Expense sync state (cross-link: `Expenses.md`)

Company-paid expenses push as a QBO Purchase and now expose business status and
QBO sync status **separately**.

- [ ] **Two statuses shown:** on `#/expenses`, an expense shows its **business
  status** (submitted / reimbursed / rejected) **and** a **QBO sync** badge
  (synced / sync failed) — they are different fields now.
- [ ] **Separate sync filter:** the expense list has a **QBO sync** filter
  (pending / synced / sync failed) distinct from the business-status filter;
  filtering by sync state returns the right rows.
- [ ] **Home list badge:** the home **Expenses** widget shows the sync badge off
  the sync state (not the business status).

## 9. Deleting a company expense — void symmetry

- [ ] **Refused & retained on void failure:** delete a **synced** company expense
  while QBO is unreachable → **refused (400)**, the expense **still exists**
  marked **sync failed**, and — importantly — its **stock receipt is NOT
  reversed** (QOH unchanged). Retry the delete once QBO is reachable.
- [ ] **Happy path & no-qbo_id:** a synced expense deletes (and voids in QBO) when
  connected; an expense with no QBO id deletes locally with no QBO call.

## 10. Reimbursement batch sync (cross-link: `Expenses.md`)

- [ ] **Batch sync badge:** on the reimbursement panel, a batch shows its **QBO
  sync** state (synced / sync failed); **Retry sync** is offered on a
  `sync_failed` batch and re-pushes.
- [ ] **Known gap — no unwind button:** there is **no delete/unwind control** for
  a batch in the SPA today (the backend supports it, the UI doesn't). So the
  batch **void-symmetry** behaviour can't be exercised from the browser — note
  this rather than hunting for a button. *(Tracked in `docs/designs/LATER.md`.)*

## 11. Permissions summary

- [ ] **Viewer:** sees sync badges; **no** Record Payment / edit / delete / expense
  delete controls. A crafted write returns 403.
- [ ] **Financials:** records/edits/deletes payments, deletes company expenses,
  manages batches.
- [ ] **Config:** configures the QBO connection + payment accounts (§1); does not
  need Financials to do so. Since 2026-10-17 also sees the **QBO Sync Failures**
  panel and may Retry / Retry all from it (and read the QBO Log tab) — but still
  cannot edit/delete expenses or manage batches.

## 12. Customer/Vendor status sync (sandbox hand test)

Contact/Business deactivate and reactivate push QBO's `Active` flag, and the
contacts import pulls QBO-side inactive/active changes back as suggestions.
Mechanics: `docs/designs/quickbooks-integration.md` "Active-flag push" and
"Setup-time data import". Every "per finding" item depends on the pending
sandbox probe (that doc, "Customer/Vendor Active flag — sandbox findings");
record the answers there.

**Run against the sandbox company only.** Preconditions: dev stack up
(`runserver` + `npm run dev`), `.env` has `QBO_ENVIRONMENT=sandbox`,
Settings → QuickBooks shows Connected, and a pull has been done from the
Contacts page so the snapshot exists. Log in as a user with
`can_manage_jobs` **and** `can_manage_config`. Keep the QBO sandbox UI open
in a second tab (Sales → Customers, Expenses → Vendors, "Include inactive"
enabled in the gear menu). "Sync log" = Django admin → QBO → QBO sync logs.

**Push (konbini → QBO)**

- [ ] **1. Business push:** business **B1** created in konbini, an invoice sent
  once so it has `qbo_customer_id`, no vendor id, no open records → Business
  page → **Deactivate** → Continue. Badge `inactive`; its contacts inactive;
  history shows the flip; sync log `customer / deactivate / success`. QBO:
  Customer inactive (name suffix per finding (a)).
- [ ] **2. Reactivate (after 1):** Reactivate. Badge gone; contacts back; sync log
  `customer / reactivate / success`. QBO: Customer active; record whether the
  name is restored.
- [ ] **3. Both roles:** business **B2** imported as both customer and vendor
  (same-name merge) → Deactivate → Continue. Two sync log rows, `customer`
  and `vendor`, both success. QBO: Customer **and** Vendor inactive.
- [ ] **4. Both roles reactivate (after 3):** Reactivate. Two
  `reactivate / success` rows; both active in QBO.
- [ ] **5. Individual contact:** contact **C1** (no business) pushed as a customer
  → Deactivate. Sync log `contact_customer / deactivate / success`; QBO
  Customer inactive.
- [ ] **6. Cascade never pushes:** business **B3** with 3 contacts and a customer
  id → Deactivate → Continue. **One** sync log row (the business), none for
  the 3 contacts; one Customer inactive in QBO.
- [ ] **7. Never pushed:** business **B4** with no QBO ids → Deactivate /
  Reactivate. Flips; **no** sync log rows; nothing in QBO.
- [ ] **8. Disconnected:** Settings → QuickBooks → Disconnect; B1 active →
  Deactivate B1. Flips locally; no sync log row; no error; QBO unchanged
  (still active).
- [ ] **9. Disconnected-push gap (after 8):** reconnect; Contacts → Pull. The B1 row
  appears as **reactivate** (QBO active, local inactive) — the documented
  disconnected-push gap. Apply → B1 active again, no push row.
- [ ] **10. QBO refuses (customer), per finding (b):** create an unpaid invoice in
  QBO for B1's customer → Deactivate B1. If QBO refuses: red message
  "QuickBooks refused to deactivate B1: ...", B1 **stays active**, sync log
  `deactivate / failed` carrying the QBO text. If QBO accepts: as #1.
- [ ] **11. QBO refuses (vendor), per finding (b):** unpaid bill in QBO for B2's
  vendor → Deactivate B2. Per finding (b) for vendors. If refused, check
  the Customer (pushed first) — it is the **known half-push limitation**:
  if the Customer is now inactive while B2 is still active in konbini,
  record it; if so, the push order needs an all-or-nothing pre-check (file it);
  retry after paying the bill should succeed.
- [ ] **12. Token refresh:** let the access token expire (or set
  `access_token_expires_at` in the past via admin) → Deactivate B3. Token
  refresh happens silently; success; Customer inactive.

**Pull (QBO → konbini)**

- [ ] **13. qbo_inactive row:** in QBO make B3's customer inactive by hand;
  konbini: Contacts → Pull. B3 row state **deactivate**, **unchecked** by
  default, with the hint text.
- [ ] **14. Refusal per row (after 13):** B3 has an open job → check the row →
  Apply. Row stays; warning "1 contact couldn't be applied: B3: Cannot
  deactivate B3: 1 open job (...)"; B3 stays active; **no** sync log row.
- [ ] **15. Apply after resolving (after 14):** close the job → Apply again. B3 and
  its contacts inactive; no sync log row (QBO already agrees).
- [ ] **16. qbo_active row:** in QBO make B3's customer active again; Pull → Apply
  the **reactivate** row. B3 and all contacts active; no push row.
- [ ] **17. Unmatched inactive dropped:** in QBO create a brand-new customer and
  immediately make it inactive; Pull. It does **not** appear; the pull
  summary counts exclude it.
- [ ] **18. Both-roles round trip:** B2 (both roles): in QBO inactivate only the
  Vendor; Pull. One **deactivate** row (vendor kind); the customer row
  reads imported. Apply → B2 inactive locally; the next Pull shows the
  customer row as **reactivate** (QBO customer still active). Record
  whether this round trip is acceptable or needs a both-roles rule.

**Edges and regressions**

- [ ] **19. Inactive-name adoption, per finding (c):** a konbini business **B5**
  whose name equals an **inactive** QBO customer; send B5's first invoice.
  Either adopts (sync log shows which id) or errors with the duplicate-name
  text; no 500.
- [ ] **20. Sync failures panel:** after any of the above, Settings → QuickBooks
  sync failures panel — status-push failures do **not** appear (money
  pushes only) and the panel does not error with status rows in the log.
- [ ] **21. Frozen banner:** B1 inactive → job detail of a closed job on B1's
  contact; PO detail on B1 as vendor. Frozen banner; **Change contact...**
  offered only if B1 itself is active (here: not).
- [ ] **22. Phone regression:** send an invoice for an active business pushed
  earlier. Unchanged behavior; the QBO customer's `PrimaryPhone` equals the
  business's **first** phone entry.

Record every "per finding" result and anything surprising in
`docs/designs/quickbooks-integration.md` under the sandbox-findings
subsection, then delete the probe customer/vendor in the sandbox (or leave
them inactive, named "konbini probe ...").

---

## Coverage matrix

| Dimension | Cases |
|---|---|
| Payment account | picker lists display names · auto-selects first · empty → form replaced by "configure in Settings" message (modal + reimbursement + expense form) |
| Account guard | required always — client-side "Choose a payment account." + backend 400 (regardless of QBO connection) · specific error message (not generic) |
| Push result | synced badge + QBO id when connected · reference → DocNumber |
| Disconnected | local write commits · row = sync failed (not pending) · reconnect + Retry → synced |
| Retry (per-verb) | failed create → re-creates · failed update → re-applies the edit (not a blind re-push) · failed delete → deletes (not back to synced) · bill-payment row Retry button · cross-entity failures panel on Settings + Retry all |
| Edit | synced → re-sync · never-synced → push fresh |
| Delete (void symmetry) | happy void+delete · QBO fail → refused + retained + sync_failed (status unchanged) · retry = delete again · idempotent not-found deletes locally · no-qbo_id deletes freely |
| Bill table display | account name + reference (no method) · sync indicator per row · — when account unresolved |
| Expense sync | business vs sync status separate · sync filter · home badge · delete refused+retained (stock not reversed) |
| Reimbursement | batch sync badge · retry-sync re-pushes · no unwind button in SPA (gap) |
| Status sync | push on deactivate/reactivate (customer, vendor, contact) · cascade never pushes · no id / disconnected = local only · QBO refusal blocks flip · pull rows deactivate/reactivate · per-row refusal warning · unmatched inactive dropped |
| Persona | Viewer read-only · Financials full · Config sets up accounts |

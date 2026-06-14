# Expenses — UI flow

**Purpose:** A from-the-user's-perspective walkthrough of the full Expense
lifecycle. It guides manual/user testing today and is intended to seed the
automated UI test platform later — each checklist item maps to an assertion.
Keep it current as the Expense UI evolves.

**Model (2026-06-14 cost-model redesign):** an expense has a single `amount` and
a Job (or overhead). It optionally records **one purchased item**, which is
either a **cost item** (freeform or non-inventoried PLI → creates a consumable
material at the entered unit cost; `amount` is the job cost, charged at purchase)
or a **stock receipt** (inventoried PLI → bumps inventory QOH; `amount` is *not*
job-costed — the cost lands when the job consumes the stock). Expenses never link
to an existing material. See `docs/plans/2026-06-14-expenses-cost-model-redesign.md`.

## Personas

- **Worker** — no permission atoms. Can submit and view *their own* expenses.
- **Financials** — holds `can_manage_financials`. Full CRUD, sees all expenses,
  can reject, can batch reimbursements, and can enter expenses for other people.

## Dev note — QuickBooks

**Company-paid** expenses push to QBO on save. If the dev env isn't connected to
QBO they land in `sync_failed` — expected, not a bug. Prefer **personal**
expenses except where you're specifically exercising the company/QBO path.

---

## 1. Creating expenses — the shapes

Entry points: **Add Expense** in the task-list toolbar (`#/jobs/{id}/tasklist`,
modal pre-anchored to that job); the Expenses page (`#/expenses`); the Home
"My Expenses" card (locked to self). The purchased item is optional: **+ Add a
purchased item** reveals a price-list-item picker (or "None (freeform)").

- [ ] **Overhead (no job):** clear the Job field → save. Saves fine; blank Job in
  the list.
- [ ] **Job service cost (no item):** pick a Job, add no item, save. Anchored to
  the job. *(Silent-drop fix — a job alone is valid.)* e.g. third-party shipping.
- [ ] **Cost item — freeform:** pick Job → Add a purchased item → leave PLI as
  "None (freeform)" → enter description, quantity, **unit cost** → save. Creates a
  consumable material at that unit cost.
- [ ] **Cost item — non-inventoried PLI:** Add a purchased item → pick a
  non-inventoried PLI → quantity + unit cost → save. Creates a PLI-linked
  consumable material.
- [ ] **Stock receipt — inventoried PLI:** Add a purchased item → pick an
  **inventoried** PLI → the form switches to a **stock-purchase** (quantity only,
  no unit-cost field, with a note that it adds to inventory) → save. **No
  consumable material is created; inventory QOH goes up.**
- [ ] **No existing-material list:** confirm there is *no* option to pick/link an
  already-existing material — only create-new.

Payment branch:
- [ ] **Personal** → requires "Purchased by" (see §2).
- [ ] **Company** → requires a payment account; reference field appears; QBO push.

## 2. The "Purchased by" picker (permission-gated)

- [ ] **Worker:** no Purchased-by pulldown; the expense is implicitly theirs.
- [ ] **Financials:** pulldown shown, **defaults to the current user**; can pick
  someone else (entering on behalf of).

## 3. What the purchased item creates

- [ ] **Freeform / non-inv PLI → consumable material at the entered cost.** Enter
  qty 2, unit cost $30 (goods = $60), amount **$66** (the $6 over is tax/shipping).
  The material's unit cost is **$30** (what you typed) — *not* $33 (amount ÷ qty).
  No division, no surprise; the gap between `amount` and goods is unbudgeted tax.
- [ ] **Inventoried PLI → stock receipt, no material.** After saving, the job has
  **no new material row** for it, but the PLI's **quantity-on-hand increased** by
  the entered quantity (check the price-list item / inventory).
- [ ] **Material modal freeform cost still locked** (separate rule): on the task
  list, **Add Material** with no PLI → the Unit Cost field is **disabled** (cost
  comes from an expense/PO, not typed here).

## 4. Where the expense surfaces (Job UI)

- [ ] **Job overview** (`#/jobs/{id}`) → **Materials & Expenses** pillar: a
  **cost-item** expense's material shows as a material row with a **"paid $X"**
  annotation; a **service cost** (no item) shows its own expense row. Pillar count
  includes the material-less expenses.
- [ ] **Task list** → **"Expenses (no material)"** table (data-table style, with a
  **Purchased-by** column); refreshes after adding via the toolbar.
- [ ] **Job header financials (Spent / Profit):**
  - A **cost expense** raises **Spent** by its `amount` immediately (cost-at-
    purchase). Verify no double-count.
  - A **stock receipt** does **not** change Spent at purchase (it's inventory) —
    see §5.

## 5. Stock receipts & cost-at-consumption (the new core)

- [ ] **Buy stock → Spent unchanged at purchase.** Record an inventoried stock
  receipt on a job; the job's **Spent does not move** (the amount is inventory).
- [ ] **Cost lands at consumption.** Have a consumable material for that PLI on
  the job; start the task that consumes it → the job's Spent rises by
  `qty × unit_cost` at that point.
- [ ] **Plywood top-up (the headline case):** a 10-sheet inventoried material,
  only 7 on hand. Try to start the task → **blocked** with "only 7 on hand …"
  (§6). Record a stock-receipt expense for 3 → QOH 7→10. Start the task again →
  succeeds; the job is charged for **10 once** (no double-count from the expense).
- [ ] **Overage stays as stock.** Buy 5 instead of 3 → after the 10-sheet
  material consumes, 2 remain in QOH for the next job (nothing lost).
- [ ] **Reverse on delete/reject:** delete (or, for a personal expense, reject) a
  stock-receipt expense → its QOH bump is **reversed**.

## 6. The shortfall block + reduce-and-split workaround

- [ ] Starting a task whose inventoried material exceeds on-hand stock is
  **hard-blocked**; the error reads roughly *"only N on hand. To start now, reduce
  this material to N and add a second task/material for the remainder while it is
  procured."*
- [ ] **Workaround works:** reduce the material to the on-hand quantity → the task
  starts; add a second task/material for the remainder; procure (a stock receipt
  or PO) and proceed. (Trust-the-user; the system suggests but doesn't force it.)

## 7. Editing & moving (full editability)

- [ ] **Move to the right job:** edit an expense, change the Job → it moves; a
  cost-item's material moves with it (stays consistent).
- [ ] **`material` is create-only:** there's no way to swap/relink the purchased
  item after creation.
- [ ] **Permissions:** a worker can submit/view their own but **can't
  edit/delete**; financials can edit/delete any.

## 8. The freezes

- [ ] **Invoiced-freeze:** put a material-less (service) expense on an invoice
  (§9), then **edit or delete** it → **blocked** ("on an invoice; remove it
  first"). Remove from the invoice → editable again. An expense whose **material**
  is on an invoice is likewise frozen.
- [ ] **Reimbursed money-lock:** batch a personal expense (§10), then change
  **amount / payment method / payment account / purchased-by** → **blocked**;
  **delete** → blocked. Editing **description** is allowed. Unwind the batch →
  fully editable again.

## 9. Billing — the invoice wizard

Open the invoice wizard for the job.

- [ ] A **material-less** (service) job expense appears in an **"Expenses"** group,
  labeled `[expense]`.
- [ ] A **cost-item** expense does **not** appear as an expense atom — it bills
  through its **material** (no double-billing).
- [ ] A **stock receipt** **never** appears (it's inventory, not a billable cost).
- [ ] An **overhead** (no-job) expense **never** appears.
- [ ] Select an expense atom → line item at **pass-through cost** (qty 1 ×
  amount); **edit the line's price** to set the charge.
- [ ] Once on a non-cancelled invoice, the pool shows it **claimed** (greyed,
  "→ line N"), not offered again.

## 10. Reimbursement cycle (personal)

- [ ] Submit a **personal** expense → `submitted`.
- [ ] As financials, batch it into a **Reimbursement** → `reimbursed`.
- [ ] Confirm the **money-lock** (§8) now applies.
- [ ] **Unwind** the reimbursement → back to `submitted`, editable again.

## 11. Reject (personal)

- [ ] As financials, **reject** a submitted personal expense → `rejected`. A
  **cost-item** material is deleted (earmark/ad-hoc receipt unwound); a **stock
  receipt's** QOH bump is reversed; rejection is **refused** if a cost-item
  material was already `consumed`.

---

## Coverage matrix

| Dimension | Cases |
|---|---|
| Shape | overhead · job service cost · cost item (freeform) · cost item (non-inv PLI) · stock receipt (inventoried PLI) |
| No-join | existing-material list absent; `material` create-only |
| Payment | personal (purchased-by) · company (QBO push) |
| Persona | worker (no picker, own-only) · financials (picker, full CRUD, reject, batch) |
| Cost timing | cost item → at purchase (entered unit cost, no division) · stock receipt → at consumption (Spent unchanged at purchase) |
| Inventory | stock receipt bumps QOH · top-up unblocks task start · overage stays as stock · delete/reject reverses QOH |
| Shortfall | task-start hard block + reduce-and-split suggestion + workaround |
| Freezes | invoiced (self + via material) · reimbursed money-lock |
| Billing | service expense offered · cost item via its material · stock receipt never · overhead never · pass-through then edit price · claimed state |

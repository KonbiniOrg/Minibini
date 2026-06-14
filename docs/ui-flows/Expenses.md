# Expenses — UI flow

**Purpose:** A from-the-user's-perspective walkthrough of the full Expense
lifecycle. It guides manual/user testing today and is intended to seed the
automated UI test platform later — each checklist item maps to an assertion.
Keep it current as the Expense UI evolves.

## Personas

Several behaviors differ by permission, so test with two users:

- **Worker** — no permission atoms. Can submit and view *their own* expenses.
- **Financials** — holds `can_manage_financials`. Full CRUD, sees all expenses,
  can reject, can batch reimbursements, and can enter expenses for other people.

## Dev note — QuickBooks

**Company-paid** expenses push to QBO on save. If the dev env isn't connected to
QBO they land in `sync_failed` — expected, not a bug. Prefer **personal**
expenses except where you're specifically exercising the company/QBO path.

---

## 1. Creating expenses — the four shapes

Entry points: **Add Expense** in the task-list toolbar (`#/jobs/{id}/tasklist`,
opens the modal pre-anchored to that job); the Expenses page (`#/expenses`, for
an un-anchored create); the Home "My Expenses" card (locked to self).

- [ ] **Overhead (no job):** clear the Job field → save. Saves fine; blank job in
  the list.
- [ ] **Job-only, no material:** pick a Job, change nothing else, save. The
  expense anchors to the job. *(This is the silent-drop fix — picking a job alone
  is valid; the old bug saved with no job.)*
- [ ] **Link an existing material:** pick a Job → its materials list appears →
  pick one → save.
- [ ] **New material (mini-PO):** pick a Job → "+ Add new material" → save;
  creates the material on the job.

Payment branch:
- [ ] **Personal** → requires "Purchased by" (see §2).
- [ ] **Company** → requires a payment account; reference field appears; pushes
  to QBO.

## 2. The "Purchased by" picker (permission-gated)

- [ ] **Worker:** no Purchased-by pulldown; the expense is implicitly theirs.
- [ ] **Financials:** pulldown shown, **defaults to the current user**; can pick
  someone else (entering on behalf of).

## 3. Where the expense surfaces

- [ ] **Job overview** (`#/jobs/{id}`) → **Materials & Expenses** pillar: a
  material-less expense gets its **own row**; a material-linked expense shows as a
  **"paid $X" annotation** on its material's row (not a duplicate). Pillar count
  includes material-less expenses.
- [ ] **Task list** → **"Expenses (no material)"** table at the bottom (standard
  data-table style, **Purchased-by** column). Refreshes after adding via the
  toolbar.
- [ ] **Job header financials (Spent / Profit):** Spent rises by the expense
  amount. Verify **no double-count** — a material-linked expense raises Spent
  once (via the material cost), not twice.

## 4. Cost-on-material behaviors

- [ ] **Cost flows on link:** link a $50 expense to a freeform material with
  qty 2 and no cost → material unit cost becomes **$25** (amount ÷ qty).
- [ ] **Freeform cost is document-sourced:** Add Material with **no** price-list
  item → the **Unit Cost field is disabled** (with a hint). Cost comes from the
  expense/PO, never typed.
- [ ] **Unlink resets cost:** edit the expense, remove the material → material
  cost returns to **0** (when nothing else backs it).
- [ ] **Clobber guard:** linking an expense to a material that already has a
  PLI/PO cost → **mismatch error**, no silent overwrite.

## 5. Editing & moving (full editability)

- [ ] **Move to the right job:** edit an expense, change the Job → it moves; a
  linked material moves with it (stays consistent).
- [ ] **Permissions:** a worker can submit/view their own but **can't
  edit/delete**; financials can edit/delete any.

## 6. The freezes — don't skip these

- [ ] **Invoiced-freeze:** put a material-less expense on an invoice (§7), then
  try to **edit or delete** it → **blocked** ("on an invoice; remove it first").
  Remove from the invoice → editable again. An expense whose **material** is on
  an invoice is likewise frozen.
- [ ] **Reimbursed money-lock:** batch a personal expense (§8), then try to change
  **amount / payment method / payment account / purchased-by** → **blocked**;
  **delete** → blocked. Editing **description** is still allowed. Unwind the batch
  → fully editable again.

## 7. Billing — the invoice wizard (Part B)

Open the invoice wizard for the job.

- [ ] A **material-less** job expense appears in an **"Expenses"** group in the
  source pool, labeled `[expense]`.
- [ ] A **material-linked** expense does **not** appear (bills through its
  material — no double-billing).
- [ ] An **overhead** (no-job) expense **never** appears.
- [ ] Select an expense atom → line item at **pass-through cost** (qty 1 ×
  amount). Then **edit the line's price** to set what the customer's charged.
- [ ] Once on a non-cancelled invoice, the pool shows it as **claimed** (greyed,
  "→ line N"), not offered again.

## 8. Reimbursement cycle (personal)

- [ ] Submit a **personal** expense → `submitted`.
- [ ] As financials, batch it into a **Reimbursement** → `reimbursed`.
- [ ] Confirm the **money-lock** (§6) now applies.
- [ ] **Unwind** the reimbursement → back to `submitted`, editable again.

## 9. Reject (personal)

- [ ] As financials, **reject** a submitted personal expense → `rejected`. A
  linked material's earmark/ad-hoc receipt is unwound and the material deleted;
  rejection is **refused** if that material was already `consumed`.

---

## Coverage matrix

| Dimension | Cases |
|---|---|
| Attachment | overhead · job-only · link existing material · new material |
| Payment | personal (purchased-by) · company (QBO push) |
| Persona | worker (no picker, own-only) · financials (picker, full CRUD, reject, batch) |
| Cost | link sets cost · freeform cost disabled · unlink resets · clobber blocked |
| Freezes | invoiced (self + via material) · reimbursed money-lock |
| Billing | material-less offered · material-linked not · overhead never · pass-through then edit price · claimed state |

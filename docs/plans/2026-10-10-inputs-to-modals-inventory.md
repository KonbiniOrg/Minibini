# Non-modal input surfaces → modal candidates

Working inventory for the `feature/ui` branch (2026-10-10). Every `<input>`,
`<textarea>` and `<select>` in the SPA that is **not** already rendered inside
`components/Modal.svelte`, grouped by the kind of surface it lives on.

**Decision** column: `YES` = move into a modal, `NO` = stays in-page,
`DECIDE` = RM to call. Suggested leanings are in the Notes; RM overrides.

Disposable — delete when the work ships.

---

## A. Full-page create/edit forms (own route)

Whole pages whose only job is a form. Job edit, duplicate, and the inventory
item form already moved to modals, so these are the stragglers.

| # | Route | Component(s) | Fields | Decision | Notes |
|---|---|---|---|---|---|
| A1 | `#/contacts/new`, `#/contacts/:id/edit` | `routes/contacts/ContactFormPage.svelte` → `components/contacts/ContactForm.svelte` | name ×3, email, 3 phones, address ×6, business picker |yes | Already hosts `DuplicateContactModal` — would become modal-over-modal |
| A2 | `#/businesses/new`, `#/businesses/:id/edit` | `BusinessFormPage.svelte` → `components/contacts/BusinessForm.svelte` | name, phone, address, website, tax fields, terms, default contact, inline "new contact" sub-form | yes| Same duplicate-modal nesting concern as A1 |
| A3 | `#/jobs/new` | `routes/jobs/JobFormPage.svelte` → `components/jobs/JobForm.svelte` | contact picker, name, description, due date, customer PO, PM | yes| Edit + duplicate are already `JobEditModal` / `DuplicateJobModal`; create is the odd one out |
| A4 | `#/purchase-orders/new`, `/:id/edit` | `PurchaseOrderFormPage.svelte` → `components/purchaseorders/PurchaseOrderForm.svelte` | vendor picker, contact, requested date | PARKED | Small form — PO process session |
| A5 | `#/users/new` | `routes/users/UserCreatePage.svelte` | username, email, names, password ×2 | yes| |
| A6 | `#/email/:id/create-job` | `routes/email/EmailCreateJobPage.svelte` + `components/email/SenderResolutionForm.svelte` | job name, description, sender resolution (existing/new contact, phones, business choice) | yes| Launched from email detail; modal would keep the email visible behind |
| A7 | `#/email/:id/create-po` | `EmailCreatePOPage.svelte` + `SenderResolutionForm.svelte` | sender-resolution block | PARKED | Pair with A6 — PO process session |
| A8 | `#/email/:id/associate`, `/associate-po` | `EmailAssociatePage.svelte`, `EmailAssociatePOPage.svelte` | one job / PO picker + submit | yes| Tiny — natural modal |
| A9 | `#/estimates/:id/send`, `#/change-orders/:id/send`, `#/purchase-orders/:id/send`, `#/invoices/:id/send` | `components/email/DocumentSendForm.svelte` | to/cc/bcc, subject, body, attachments | yes| CLAUDE.md already records "the email step is slated to become a modal" (the standing links-vs-buttons exception) |

## B. Inline show/hide forms on list or detail pages

A button toggles a bordered box or fieldset open in the page flow. This is the
pattern `CatalogInventoryPage` explicitly abandoned ("so editing a row far down
a long catalog doesn't jump the user to a top-of-page form").

| # | Where | Component / line | Fields | Decision | Notes |
|---|---|---|---|---|---|
| B1 | Expenses list | `routes/expenses/ExpenseListPage.svelte:122` | `ExpenseForm` new/edit | yes| `ExpenseModal.svelte` already wraps the same form for task pages — one-line switch |
| B2 | Home → expenses | `components/home/ExpensesList.svelte:59` | `ExpenseForm` "Submit new expense" | yes| Same as B1 |
| B3 | Catalog → merge items | `routes/catalog/CatalogInventoryPage.svelte:165` | keep / discard selects | yes |  |
| B4 | Catalog → write-off | `CatalogInventoryPage.svelte:187` | qty, reason | yes | Irreversible action; `StockOrderDialog` next to it is already a modal |
| B5 | PO detail → add line item | `components/purchaseorders/LineItemForm.svelte` | manual/inventory mode, qty, description, units, price, category, job + task-link pickers | PARKED | Estimate/CO/invoice add-line forms are all modals — PO process session |
| B6 | PO detail → receive items | `components/purchaseorders/ReceiveItemsForm.svelte` | per-line qty receiving + note | PARKED | Per-line table; modal would need width — PO process session |
| B7 | PO detail → reconciliation | `components/purchaseorders/ReconciliationSection.svelte` | bill total, vendor ref, per-line final prices, extra-lines table | PARKED | Large; may want to stay a page section — PO process session |
| B8 | Catalog → service items | `components/ServiceItemManager.svelte:228` | name, description, rate scheme, flat-fee amount, modifiers, active | yes| |
| B9 | Settings → accounting categories | `components/settings/AccountingCategories.svelte:231` | code, name, taxable, deposit, default description, active |yes | Sibling `RateSchemeManager` form is already a modal|
| B10 | Reimbursement batch pay | `components/expenses/UserReimbursementPanel.svelte:204` | paid-on, payment account, reference, notes | yes | Opens after selecting expenses in the table above it — modal carries selected count/total |
| B11 | Email detail → reply | `components/email/EmailReplyComposer.svelte` | `DocumentSendForm` inline for Reply / Reply All | yes| Pair with A9 |

## C. Inline row editing in tables

Fields appear inside a `<tr>` on Edit, or are always-live cells.

| # | Where | Component / line | Fields | Decision | Notes |
|---|---|---|---|---|---|
| C1 | PO line items | `components/purchaseorders/PurchaseOrderDetail.svelte:240` | description, qty, units, price swap into the row | PARKED | Estimate/invoice line edit uses `LineItemModal` — PO process session |
| C2 | Change-order deliverables | `components/changeorders/CODeliverablesSection.svelte:206,241,292,329` | qty, units, description edit rows + inline new row | yes | Estimate-side equivalent already uses `DeliverablesEditModal` — consistency with estimate side |
| C3 | Shipments grid | `components/shipments/ShipmentsPanel.svelte:340` | live qty cell per deliverable × shipment | no | Spreadsheet-style; likely stays |
| C4 | Settings → QBO account names | `routes/SettingsPage.svelte:103` | editable display-name column + Save | no |  |
| C5 | QBO import previews | `components/qboimport/{Categories,Inventory,Schemes,ServiceItems}ImportPanel.svelte` | editable preview tables before import | no | Bulk preview; likely stays |
| C6 | Accounting category QBO mapping | `components/settings/AccountingCategories.svelte:183,195` | two selects per row, save-on-change | no | Save-on-change select (see Saves-are-explicit convention) |

## D. Small single-field "add" affordances

One input + an Add button embedded in a larger view.

| # | Where | Component / line | Fields | Decision | Notes |
|---|---|---|---|---|---|
| D1 | History notes | `components/HistoryPanel.svelte:34` (contact, business, PO) and `components/jobs/JobHistorySection.svelte:180` (job) | textarea + Add Note | no |  |
| D2 | Tags | `components/TagEditor.svelte:102` (contact, business detail) | input + suggestions | no |  |
| D3 | Units list | `components/UnitsManager.svelte:93` (settings) | "New unit name" + Add | no |  |
| D4 | Task actual qty | `routes/jobs/TaskDetailPage.svelte:352` | "+ / −" chip input in stats row | no | `ActualQtyModal` already exists for the task-list path |
| D5 | Default rate scheme | `components/RateSchemeManager.svelte:267` (settings) | one select |no | |

## E. Settings page fieldsets

Always visible on `#/settings`, each with its own Save. Configuration panels
rather than records.

| # | Component | Fields | Decision | Notes |
|---|---|---|---|---|
| E1 | `GeneralSettings.svelte` | estimate expiry, board retention, labor cost, job + PO number patterns |no | |
| E2 | `BusinessSettings.svelte` | notification email, public URL, email domain | no| |
| E3 | `EmailAccountSettings.svelte` | address, password, IMAP, SMTP host + port | no| |
| E4 | `EmailTemplates.svelte` | retention days, display limit, subject/body per template | no| |
| E5 | `ScheduleSettings.svelte` | buffer, horizon, activity days, minimum session, default envelope grid | no| |
| E6 | `MaterialMarkupSetting`, `FallbackCategorySetting`, `DefaultDepositCategorySetting`, `DefaultMaterialCategorySetting` | one field each |no | |
| E7 | `components/schedule/EnvelopeEditor.svelte` | time inputs per day; inline on settings, `UserDetailPage.svelte:339`, and home via `MyEnvelopeEditor.svelte` | no| |

## F. Profile and user admin pages

| # | Where | Component | Fields | Decision | Notes |
|---|---|---|---|---|---|
| F1 | Home → profile tab | `components/home/ProfilePanel.svelte` | email/name form; change-password form ×3 | password only | Change-password form → modal behind a button (security-notable); email/name stays inline |
| F2 | User detail | `routes/users/UserDetailPage.svelte` | profile, permissions checkboxes, reset password ×2, schedule envelope — four inline forms | password only | Reset-password form → modal behind a button; profile, permissions, envelope stay inline |

## G. Filters and search (expected to stay in-page)

Listed for completeness.

| # | Where | Fields |
|---|---|---|
| G1 | `components/Sidebar.svelte` | global search box |
| G2 | `routes/Search.svelte` | search-within, category, date ranges, price min/max |
| G3 | `routes/contacts/ContactListPage.svelte` | search box |
| G4 | `routes/expenses/ExpenseListPage.svelte` | status, QBO sync, payment, date range |
| G5 | `routes/invoices/InvoiceListPage.svelte` | status, sort, due range, customer picker |
| G6 | `routes/purchaseorders/PurchaseOrderListPage.svelte` | status, sort |
| G7 | `routes/catalog/CatalogInventoryPage.svelte:215` | search |
| G8 | `InventoryImportPanel`, `ServiceItemsImportPanel` | filter boxes |
| G9 | `components/users/PayrollReport.svelte` | date range |
| G10 | `components/jobs/JobHeader.svelte:238`, `components/estimates/EstimatePanel.svelte:411` | status-change selects used as action menus, not data entry |

## H. Out of scope but present

| # | Where | Fields |
|---|---|---|
| H1 | `routes/LoginPage.svelte` | username, password |
| H2 | `components/PortalDocument.svelte` | customer portal "what would you like changed" / reject-reason textareas (separate app shell) |

## Already modal (no action)

Work items (`WorkItemForm`), estimate/CO/invoice add-line forms, `LineItemModal`,
`MaterialModal`, job edit / duplicate / hold-reason, `DeliverablesEditModal`,
`InventoryItemForm` (catalog), `StockOrderDialog`, rate scheme form,
`PaymentTermsManager`, `BlepEditModal` / `TimeEditModal`, `ActualQtyModal`,
`AssignModal`, `AdjustmentModal`, `DepositInvoiceModal`, `BundleModal` /
`DriftModal`, `ExpenseModal` (task pages), duplicate contact / business,
`WorkerTimePromptModal`, material fulfillment and sever dialogs,
`StartWorkConflictModal`, and the pickers rendered inside those modals.

---

## Cross-cutting questions to settle before implementing

- **Modal-over-modal.** DECIDED 2026-10-10: use the sub-state pattern the
  shell already documents (a modal with internal sub-states passes an
  `onCancel` that backs out one level). Duplicate detection (A1, A2, A6, A7)
  renders inside the create modal in place of the form; `DuplicateContactModal`
  / `DuplicateBusinessModal` become plain fragments. No stacking contract in
  `Modal.svelte` for now — revisit if more nested prompts appear. (Note: the
  `ContactPicker` in `JobForm` is a type-ahead dropdown, not a modal, and
  already runs inside `JobEditModal`, so A3 has no nesting.)
- **PO process (A4, B5, B6, B7, C1)** is parked for its own session — not in
  this pass.
- **Routes.** DECIDED 2026-10-10: the modal opens over whatever page the
  user is on (the page behind stays visible for reference). Every current
  `<a href="#/…/new">` becomes a `<button>` that opens the modal in place;
  query-string prefills (`?contact=`, `?business=`) become props. The old
  `/new` and `/edit` routes get a redirect stub (the `JobRedirectToOverview`
  precedent) for stale bookmarks.
  - **On save of a NEW object:** navigate to the new object's detail page
    (matches what every create page does today). RM wants to run through
    this a few times before treating it as final.
  - **On save of an EDIT:** stay (the user is already on the detail page).
  - **On cancel:** stay.
  - Send forms (A9, B11) mount beside their document panel; the estimate/CO
    deliverables-gate handoff is a modal→modal handoff the shell supports.
- **Password forms (F1, F2).** Fix the browser "Save password?" prompt: add a
  read-only username field with `autocomplete="username"` to each password
  form and `name` attributes on the password inputs so managers offer
  "Update password" instead of filing a new credential. Also add
  `autocomplete`/`name` to `LoginPage.svelte`, which has none. On the admin
  reset (F2) the username is the target user's; the admin's browser may
  offer to update that account — accepted.
- **E2E coverage.** Every moved form has e2e specs keyed to its page route;
  those move with it (Definition of Done).

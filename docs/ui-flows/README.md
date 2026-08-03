# UI flows

From-the-user's-perspective walkthroughs of how each feature behaves in the SPA.

**Two audiences, one document:**
- **Manual / user testing** — a checklist you can run top-to-bottom in the browser
  without missing edge cases or permission variations.
- **The automated UI test platform** (planned) — each `[ ]` step is written to map
  to a single assertion, so these docs seed test cases rather than being rewritten.

These describe **built behavior**, like `docs/designs/` — keep them current when
the UI changes. They differ from `docs/designs/` (which explains *how/why the
system works*, for developers) by being *scripts a user or test runner follows*.
They are not disposable like `docs/plans/`.

## One file per feature flow

- `Expenses.md`, `Invoicing.md`, … — title-case feature name. Start a new file
  when a flow is substantial enough to test on its own; cross-link rather than
  duplicate where flows meet (e.g. Expenses §7 references the invoice wizard).

## Coverage map

The whole-app inventory: every SPA surface (from `App.svelte`'s route
table) mapped to its flow doc and e2e spec directory
(`e2e/specs/<dir>/`). **Keep this current** — when a route, doc, or spec
is added, update its row; a surface with no doc is an explicitly open
gap, not an oversight. Goal state: every row has a doc and a spec dir,
except flows that genuinely can't run in e2e (live QBO exchanges).

### Covered by a flow doc

| Surface | Routes | Flow doc | E2E specs |
|---|---|---|---|
| Job overview | `/jobs/:id` | Job-Overview.md | — |
| Estimate & work authoring | `/jobs/:id/estimate`, task-list Add Work, wizard | Add-Line-and-Work-Authoring.md | `add-line-and-work-authoring/` |
| Change orders | `/jobs/:id/change-order/:coId`, `/change-orders/:id/send` | Change-Orders.md | — |
| Invoice seeding & send | `/jobs/:id/invoice`, `/invoices/*` | Invoice-Seeding-and-Send.md | — |
| Bills & payments | `/bills/*` | Bills.md | — |
| Expenses & reimbursements | `/expenses`, `/reimbursements/:id` | Expenses.md | `expenses/` (§1 only) |
| Inventory | `/catalog`, `/catalog/earmarks` (§7 only) | Inventory.md | — |
| Rate schemes & adjustments | `/catalog/service-items`, adjustments in estimate/invoice | Services-and-Adjustments.md | `settings/` (rate-scheme-modal, rate-scheme-presets — §1/§2 only) |
| QuickBooks sync | payments/expenses sync, Settings §1 | QuickBooks-Sync.md | — (mostly not e2e-able) |
| Deletion & retirement | cross-cutting | Deletion-and-Retirement.md | — |
| Production lifecycle (job status × inventory × time) | spans job detail, task list/detail, catalog | Production-Lifecycle.md | — |
| Settings — Accounting Categories delete guard | `/settings` (Accounting tab) | Settings.md (§1 only) | `settings/` |

### No flow doc yet (the gap list)

| Surface | Routes | Notes |
|---|---|---|
| Time tracking (shifts & timeslips) | shift/timeslip bands (every page), timeslips on task detail | The core daily loop: clock in/out, start/stop/settle a timeslip, 24h own-edit window, `can_manage_time` edits. (Blep→actuals math belongs to Production-Lifecycle.md.) |
| Tasks — list & detail lifecycle | `/jobs/:id/tasklist`, `/jobs/:jobId/tasks/:taskId` | Statuses, queue/reorder, blocked reason, complete, mark-all-done. (Add/delete live in Add-Line & Deletion docs; start-guards and the completion cascade belong to Production lifecycle.) |
| Jobs — list, board, creation | `/jobs`, `/jobs/board` | Board columns/retention, accent colors, job create, hold/resume. |
| Schedule | `/schedule` | Per-worker bars, forecast cascade, envelope config. |
| Home & cards | `/`, `/profile`, `/help` | My-Expenses card (locked-to-self form), lists, first-login → Help. |
| Login & session | login form, logout, expiry notice | Personas land here via auth.setup; guards + session-expired path. Post-login/logout landing is already covered by `e2e/specs/auth/session-landing.spec.js` (see users-and-permissions.md → Login flow); the rest of the surface is uncovered. |
| Contacts | `/contacts`, `/contacts/new`, `:id`, `:id/edit` | CRUD, notes, delete impact counts. |
| Businesses | `/businesses`, `/businesses/new`, `:id`, `:id/edit` | CRUD, payment terms, contact association. |
| Purchase orders | `/purchase-orders/*`, `/jobs/:id/pos` | Create/edit/send/receive; Bills.md covers only the bill side of linking. |
| Deliverables & shipments | `/jobs/:jobId/shipments`, `/shipments/:sid/print` | Deliverable states, shipment build, packing-list print. |
| Estimate lifecycle (beyond authoring) | `/estimates/:id`, `/estimates/:id/send` | Send + PDF, accept/reject, revision/supersede, expiry. Authoring is Add-Line's. |
| Email inbox & email-to-X | `/email`, `/email/:id/*` | Inbox, detail, create-job/PO/bill, associate flows. Bills §9 covers one path. |
| Job history & notes | `/jobs/:id/history` | Note box, summary rows, partitioned history tabs. |
| Activity | `/activity` | Cross-user activity feed. |
| Search | `/search` + navbar search | Cross-entity search + result navigation. |
| Users admin & profile | `/users`, `/users/new`, `/users/:id`, profile tab | Atom assignment, deactivation, password self-service. |
| Settings (non-QBO) | `/settings` | Numbering, units, retention, email templates, board config. Accounting Categories CRUD beyond the delete guard (see Settings.md §1) is still uncovered. |
| View-mode & sidebar | cross-cutting | FULL/LITE toggle, sidebar behavior — probably steps inside other docs rather than its own. |

## House shape

Keep every doc in the same structure so the test platform can parse them
predictably:

1. **`# <Feature> — UI flow`** + a one-paragraph **Purpose**.
2. **Personas** — the user variants whose behavior differs (by permission atom,
   ownership, etc.). Most flows need at least a low-privilege and a high-privilege
   persona.
3. **Dev notes** (optional) — environment caveats that look like bugs but aren't
   (e.g. "company expenses need QBO connected").
4. **Numbered flow sections** — each a short scenario, its steps as GFM task-list
   checkboxes:
   - `- [ ] **Label:** action → expected result.`
   - One observable assertion per box. Name the route (`#/jobs/{id}/tasklist`) and
     the button/field text so a step is reproducible by a person *or* a script.
   - Call out *guards* (things that should be blocked) as their own boxes —
     they're the most-missed and the highest-value to automate.
5. **Coverage matrix** — a table of the orthogonal dimensions (attachment,
   payment, persona, permission, state-guards, …) × the cases to hit, so gaps are
   visible at a glance.

## Writing the steps

- **Observable, not internal.** Assert what the user sees ("Spent rises by the
  amount", "the field is disabled"), not service internals.
- **Reproducible.** Include the entry point and the control's visible label.
- **Permission-explicit.** When a step depends on a persona, say which.
- **Honest expectations.** If a step's result looks surprising but is correct,
  say so — and tell the tester to report deviations as likely bugs.

See `Expenses.md` as the reference implementation of this shape.

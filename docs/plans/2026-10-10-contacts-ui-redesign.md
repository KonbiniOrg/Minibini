# Contact and Business detail pages — redesign spec

**Date:** 2026-10-10 · **Branch:** `feature/ui` · **Status:** awaiting RM review
**Mockup:** `docs/plans/2026-10-10-contacts-ui-mockup.html` (also published as a
private artifact). Pin numbers below refer to the orange pins in the mockup.

## 1. Goal

Make `/contacts/:id` and `/businesses/:id` read like records instead of
field dumps, and put the day-to-day actions where they are reached for:
New Job, Edit, and (soon) Deactivate in the banner; contacts, recent jobs
and open invoices in a two-column body modelled on the job pages' banner
vocabulary. FULL density is the target. LITE trimming is a later pass.

## 2. Decisions already made (RM, 2026-10-10)

- FULL density only for this work. The two detail components stop reading
  `$viewMode` and stop using `<FullOnly>`; the "show N completed / paid"
  toggle replaces the closed-row hiding in both modes. (The yellow FULL
  body tint is being retired app-wide; that is a separate change and this
  work does not touch `body[data-view-mode="full"]`.)
- No QuickBooks state anywhere on either page.
- Banner actions: **New Job** as the one real button; **Edit** and
  **Deactivate** as quiet links, larger than the job header's edit links.
  **Delete…** replaces Deactivate only when the record is deletable (§4.3).
- **Deactivate is a placeholder**: the word is rendered, disabled, with a
  "not available yet" title. The feature (active flag on Business and
  Contact, pickers and lists skipping inactive rows, Reactivate) is tracked
  in the external issue tracker, not in `LATER.md`.
- Section names: **Contacts**, **Recent Jobs**, **Open Invoices**,
  **Purchase orders**, **History & notes**. The identity panels are
  **Contact**, **Billing** (business only), **Business** (contact only),
  **Tags**.
- "show N completed" / "show N paid" extends the table in place and pushes
  the page down. No pagination; if a customer ever outgrows this it becomes
  a separate Job History tab.
- Contacts table: per-row **New job** and **Set as default**; no job count.

## 3. Backend changes

No model changes. No migrations.

### 3.1 `JobSummarySerializer` (`apps/api/jobs/serializers.py`)

Add `contact` (pk), `contact_name`, `start_date`, `created_date`,
`estimated_amount`. `estimated_amount` reuses the same per-job financials
helper `JobSerializer` uses (`compute_job_financials` → `estimated`,
stringified); a per-serializer cache keyed by pk, as `JobSerializer` does,
so each job is computed once per response. Consumers today are the two
contact-side detail serializers and `apps/api/search/views.py`; the extra
fields are additive and harmless there.

Cost note: a business with dozens of jobs computes dozens of financials per
page load. Acceptable at current scale; if it hurts, the fix is a
`?summary=` style opt-in, not dropping the column.

### 3.2 `ContactSummarySerializer` (`apps/api/contacts/serializers.py`)

Add `work_number` so the Contacts table can show mobile with a work-number
fallback.

### 3.3 Financials endpoints

`GET /api/contacts/{id}/financials/` and `GET /api/businesses/{id}/financials/`
keep `invoiced` and `profit` and add:

| key | meaning |
|---|---|
| `open_jobs` | count of scoped jobs whose status is not completed / rejected / cancelled |
| `outstanding` | sum of `total - amount_paid` over scoped invoices whose status is in `UNPAID_STATUSES` (open, partly-paid, defaulted), as a 2-dp string; reuse the annotations `InvoiceViewSet.get_queryset` already defines rather than re-deriving balance |
| `first_job_date` | min `created_date` of scoped jobs, ISO date or `null` ("Customer since …") |
| `last_job_start` | max of (`start_date` or `created_date`) over scoped jobs, ISO date or `null` ("Last job started …") |

Scope is `contact=X` for contacts and `contact__business=X` for businesses,
same as today.

### 3.4 Existing endpoints relied on, unchanged

- `PATCH /api/businesses/{id}/` with `default_contact_id` → Set as default.
- Two-phase `DELETE` on both viewsets (first call returns `impact`, second
  with `?confirm=true` executes). The business impact payload's `bills`
  key is no longer rendered; leave the payload alone.
- `GET /api/contacts/?business={id}&page_size=100` (sibling contacts) and
  `GET /api/businesses/{id}/` (the contact page now also fetches its
  business's detail payload, see §4.5).

## 4. Frontend

Files: `routes/contacts/{Contact,Business}DetailPage.svelte`,
`components/contacts/{CustomerHeader,ContactDetail,BusinessDetail}.svelte`,
plus one new shared component. Tests alongside in `frontend/tests/`.

### 4.1 `CustomerHeader.svelte` (pins 1, 2, 8, 9)

Same red-950 full-bleed banner. Props become:

- `name`, `kind` (`'contact' | 'business'`), `business`, `defaultContact`,
  `isDefaultContact` (contact pages: renders the yellow "default contact"
  chip in the subtitle), `contactCount` (business pages: "· 3 contacts").
- `financials` in the new §3.3 shape → numbers box: **Open jobs**,
  **Outstanding** (amber), **Invoiced** (green), **Profit** (green/red).
  Facts line above it: "Customer since {Mon YYYY} · Last job started
  {Mon D} · {terms}" for businesses; "Contact since … · Last job started …"
  for contacts. Each fragment is omitted when its value is null.
- `actions` snippet, rendered in the status row: the page passes
  `<button class="banner-btn">New Job</button>`, Edit, and Delete… /
  Deactivate. Button and link styles live in `CustomerHeader`'s scoped
  style (`banner-btn`; the links reuse `.edit-link .header-action` from
  `app.css` with a local 14px / 0.75-opacity override, as the job header
  already overrides sizing locally).

The banner no longer has the job header's fixed 110px height; the title still
truncates to one line.

**Job header parity (RM, 2026-10-10):** the job header's quiet links (Edit,
Duplicate…) grow to the same 14px / 0.75-opacity size. Since `.edit-link`
in `app.css` is the shared rule, change it there rather than overriding in
two places.

### 4.2 Body layout (pins 3, 4, 10, 11)

Both `*Detail.svelte` components render a two-column grid:
`300px minmax(0, 1fr)`, gap 18px, stacking to one column at
`PHONE_MAX_WIDTH` (720px). Left column is the identity stack of `.panel`s
(the `app.css` panel vocabulary); right column is `CustomerActivity`.

Business identity panels:
- **Contact**: Phone, Web (link, `https://` prefixed if missing), Address
  (`preserve-breaks`).
- **Billing**: Ref, Terms, Tax ("Exempt · {number}" or "Not exempt"),
  Multiplier ("full rate" when null).
- **Tags**: existing `TagEditor`.

Contact identity panels:
- **Contact**: Email as `mailto:` plus a copy button (clipboard write,
  falls back to selecting the text); Mobile / Work / Home as `tel:` links,
  each row omitted when blank; Address block.
- **Business** (omitted for individuals): business name link, one muted line
  "{phone} · {terms} · tax exempt|taxed", then **Also here**: the other
  contacts at the business with their job counts, computed client-side from
  the business detail payload (`business.contacts` × `business.jobs[].contact`).
- **Tags**: existing `TagEditor`.

The old Name, Reference Code and "Business Details" rows are gone.

### 4.3 Banner actions and the delete / deactivate rule (pins 1, 9)

- **New Job** → `JobCreateModal`. Business page: `defaultContactId` = the
  business's default contact. Contact page: this contact. The modal still
  lets the user change the contact.
- **Edit** → existing `ContactFormModal` / `BusinessFormModal`.
- `canDelete` is derived in the page from data already loaded:
  - business: `jobs.length === 0 && poCount === 0 && contacts.length <= 1`
  - contact: `jobs.length === 0 && !(business && siblingCount === 0)` (today's
    service rule: a contact with jobs, or the only contact of a business,
    cannot be deleted)
- `canDelete` → **Delete…** opens a `Modal` ("Delete {name}?") listing the
  impact counts from the first-phase DELETE response (contacts, jobs,
  purchase orders; no bills line). Confirm runs the second phase and
  navigates to `/contacts`. This replaces the inline "Are you sure?" paragraph.
- otherwise → **Deactivate**, rendered disabled with
  `title="Not available yet"`. No handler.
- All three actions are gated on `$canManageJobs` as today.

### 4.4 `CustomerActivity.svelte` (new; pins 4, 5, 6, 7, 12)

One component for the right column of both pages. Props: `jobs`,
`invoices`, `purchaseOrders` (arrays), `contacts` + `defaultContactId` +
`onSetDefault` + `onNewJobFor` (business page only; omitted on contact
pages), `showContactColumn`, `newPOHref`, `history`, `onAddNote`.

Sections, in order:

1. **Contacts** (business only). `DataTable` columns: Name (link, yellow
   "default" chip on the default), Email (`mailto:`), Phone (mobile, else
   work), actions cell with **New job** (opens `JobCreateModal` for that
   contact) and **Set as default** (disabled on the current default;
   otherwise PATCHes and reloads; no confirm, it is reversible). Section
   head carries the **New contact** action-link (`ContactFormModal` with
   `defaultBusinessId`).
2. **Recent Jobs**. Columns: Job # (link, `JOB-` prefix stripped as the job
   header does), Name, Contact (business page only), Status (pill +
   human label, same label map as `JobHeader`), Started (`start_date`,
   else `created_date`, muted), Estimate (right-aligned money).
   Rows with status completed / rejected / cancelled are hidden behind
   **show N completed**, which toggles to **hide N completed**. The link is
   absent when N is 0.
3. **Open Invoices**. Columns: Invoice #, Job, Status pill, Sent
   (`sent_date` from the summary payload, "—" when null), Total, Paid,
   Balance. Hidden set: paid / cancelled / superseded → **show N paid**.
4. **Purchase orders**. Columns: PO #, Status pill, Issued (`issued_date`,
   else `created_date`, muted). Hidden set: received_in_full / cancelled →
   **show N closed**.
5. **History & notes**: the existing `HistoryPanel` inside a `.panel`
   (it keeps its own lite/full rule).

A section whose total row count is zero renders as the dashed one-line
**collapsed section** ("Purchase orders · none") carrying its action link
(New purchase order, when `$canManageFinancials`). Sections order themselves
so populated sections precede collapsed ones; among populated sections the
order above holds.

The pure parts (hidden-set membership, section ordering, label text) live
in `lib/customerActivity.js` so they are unit-testable without mounting.

### 4.5 Page loaders

- `BusinessDetailPage`: business detail, invoices (`?business=&summary=true&page_size=100`),
  POs (`?business=&page_size=100`), financials, history. Pager controls
  are removed; 100 is the documented ceiling for these tables.
- `ContactDetailPage`: contact detail, its business detail (when it has
  one), invoices and POs scoped by `contact=` with `page_size=100`,
  financials, history.
- Both reload everything after Set as default, Edit save, note add.

### 4.6 Removed

`FullOnly` imports and `$viewMode` reads in `ContactDetail.svelte` /
`BusinessDetail.svelte`; the Previous/Next pager paragraphs; the bottom
Edit/Delete buttons and "Back to list" link (the sidebar is the way back);
the inline delete confirmation.

## 5. Tests

Backend (`tests/`), TDD:
- `test_api_contacts.py`: financials returns the four new keys with correct
  values for a contact and a business that have an open job, a closed job,
  an unpaid and a paid invoice; `open_jobs` excludes completed / rejected /
  cancelled; `outstanding` ignores paid / draft / cancelled / superseded.
- Job summary payload on `/api/contacts/{id}/` and `/api/businesses/{id}/`
  carries `contact`, `contact_name`, `start_date`, `created_date`,
  `estimated_amount`; business `contacts[]` carries `work_number`.

Vitest (`frontend/tests/`):
- `lib/customerActivity.test.js`: hidden sets, labels, section ordering,
  collapsed detection.
- `components/contacts/CustomerHeader.test.js`: numbers box renders the new
  keys; facts line omits nulls; actions snippet renders.
- `components/contacts/CustomerActivity.test.js`: show/hide toggle reveals
  rows; collapsed line for empty sections; Set as default disabled on the
  default and calls `onSetDefault` otherwise; Contact column only when asked.
- `routes/contacts/*DetailPage.test.js` (or component-level): Delete… vs
  Deactivate decision; delete modal flow; contact page fetches business
  detail and lists siblings with job counts.

E2E (`e2e/specs/contacts/`, persona `finjobs`):
- `business-detail.spec.js`: banner shows New Job / Edit / Deactivate on a
  seeded business with jobs; Contacts table lists its contacts with the
  default chip; Set as default moves the chip; New job from a row opens the
  modal with that contact preselected; "show N completed" reveals rows.
- `contact-detail.spec.js`: banner chip for a default contact; Contact
  panel shows mailto / tel links; Business panel lists siblings; a freshly
  created contact with no jobs shows Delete… and the delete modal deletes
  it and lands on `/contacts`.

## 6. Docs to update in the same session

- `docs/designs/contacts-and-businesses.md` → "Frontend › Detail pages"
  (layout, sections, show-completed rule, delete/deactivate rule, the
  100-row ceiling) and the financials rollup paragraph (new keys).
- `docs/designs/architecture-and-conventions.md` §6.2 seam 1: the two
  detail components are no longer `<FullOnly>` consumers (note whether any
  consumer remains).
- Delete `docs/plans/2026-10-10-contacts-ui-mockup.html` and this spec
  once shipped.

## 7. Out of scope

Deactivate behaviour; LITE trimming of these pages; retiring the FULL body
tint; emails by contact; a job-style nav rail / Job History tab;
list-page changes; QBO anything.

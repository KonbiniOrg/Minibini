# Job Detail View Redesign

## Summary

Redesign the Svelte SPA Job detail view from a flat key-value layout to a status-aware page with color-coded accordion sections for each document type, a history timeline with inline email previews, and a reusable accordion component.

## Target

Svelte SPA only (`frontend/src/`). Django HTML template is not modified.

## Site Header

A site-wide header with navigation and user info will be added to the app, but has not been designed yet. The Job detail layout should reserve space for it at the top of the page (e.g., a placeholder div or slot). Design and implementation of the site header is a separate effort.

## Job Header

- Title: `JOB #NUMBER: Job Name` (single line, large)
- Subtitle: `for [Contact Name], at [Business Name]` with links to contact and business detail pages
- Status badge (colored pill) + key dates on one line: start date, due date (and completed date when applicable)
- Display `customer_po_number` if present (e.g., after the dates)

## Description + History Layout

Description and history sit side by side in a flex row.

**Description** (left, flex: 1):
- Light background card with "DESCRIPTION" label
- Generous min-height — descriptions are expected to grow larger than current dataset
- Full width of remaining space after history panel

**History panel** (right, fixed width ~320px):
- "HISTORY" header, independent scroll
- Max height constrained; scrolls independently from page
- Entries in reverse chronological order (newest first)
- "Add Note" textarea and button at top of panel (preserving existing functionality from HistoryPanel.svelte)
- Entry types:
  - **Status changes / actions**: date, user, action text
  - **Notes**: date, user, italic note text
  - **Emails**: blue `@` icon, clickable subject line, sender. Clicking subject slides open an inline preview (same grid-template-rows animation as accordions) showing recipient and date from TempEmail fields, and "View full email" link to email detail page. No body/snippet is available from TempEmail (it stores only metadata). See "Email Data" under Prerequisites for availability and degradation.

## Accordion Document Sections

All document types appear as collapsible accordion bars below the description/history area. Bars are always visible regardless of whether data exists (empty state shown when no data).

### Reusable Accordion Component

Build a generic `Accordion.svelte` component for reuse across the app. Props:
- `title` — bar label (e.g., "Work Order")
- `meta` — secondary text on the bar (e.g., "Cabinet Refinishing Standard · Incomplete")
- `open` — whether expanded by default
- `colorScheme` — theme object or CSS class controlling header background, border, row tints

Animation: CSS `grid-template-rows` transition (0fr ↔ 1fr), ~200ms ease. Arrow icon (▶) rotates 90° when open.

### Color Scheme Per Document Type

Each accordion bar has a distinct color scheme applied to its header, border, thead, and alternating row backgrounds. Row backgrounds are light tints of the section color, not the dark header color.

| Document Type   | Header Color | Row Tint Family |
|-----------------|-------------|-----------------|
| Worksheet       | Teal        | Light teal      |
| Estimate        | Indigo      | Light indigo    |
| Work Order      | Amber       | Light amber     |
| Invoice         | Green       | Light green     |
| Purchase Orders | Slate       | Light slate     |

Exact color values to be finalized during implementation (user wants to tune these).

### Status Pills

Task/item statuses use light pastel pill badges that are visually distinct from both the header bar and from each other:

| Status      | Background | Text Color |
|-------------|-----------|------------|
| Complete    | Light blue | Blue       |
| In Progress | Light amber | Amber     |
| Pending     | Light purple | Purple   |
| Final       | Light indigo | Indigo   |

### Bar Order and Default Open State

Bars appear in workflow order: Worksheet → Estimate → Work Order → Invoices → Purchase Orders.

The **default open** bar depends on job status and available data (the "furthest along" document):
- Job is complete → Invoice bar open
- Job has a Work Order → Work Order bar open
- Job has an Estimate but no Work Order → Estimate bar open
- Job has only a Worksheet → Worksheet bar open
- Early status (draft) → Worksheet bar open (or first bar with data)

All other bars are collapsed but expandable. User can open/close any bar at any time.

### Multiple Documents Per Type

A job can have multiple worksheets, estimates, work orders, or invoices. Each accordion bar represents the **document type**, not a single document. Within the bar:

- **Worksheets**: Show the latest (highest version) worksheet's tasks. If multiple worksheets exist, include a link/label showing count (e.g., "(2 worksheets)") with navigation to older versions.
- **Estimates**: Show the current (non-superseded) estimate's line items. Meta text includes "(N previous)" count with a link to view superseded estimates.
- **Work Orders**: Show the current work order's tasks. If multiple work orders exist, list them all in the table with a separator or sub-headers.
- **Invoices**: List all invoices for the job in a summary table (invoice #, status, total). Individual line items shown on the invoice detail page.

### Content Per Section

**Worksheet bar**:
- Meta text: `v{version} · {Status}` (e.g., "v2 · Final")
- Table: Task name, Status (pill)

**Estimate bar**:
- Meta text: `{estimate_number} · v{version} · {Status}` with `(N previous)` count
- Table: line #, description, qty, unit price, total (computed client-side: qty × price)
- Footer row with computed grand total
- Link to previous estimates inside the expanded content

**Work Order bar**:
- Meta text: template name (if from template), status
- Table: Task name (linked to task detail), Assigned (display name), Status (pill)
- In-progress row gets a highlighted background

**Invoice bar**:
- Meta text: invoice number, status (or "None yet")
- Table: invoice #, customer PO, status, total — one row per invoice, linked to detail
- Empty state message when no invoices

**Purchase Orders bar**:
- Meta text: PO number, count (or "None")
- Table: PO # (linked), Vendor, Total, Status (pill)
- If a PO has line items associated with other jobs (not just this one), those line items are visually distinguished (e.g., muted/grayed row styling) to indicate they belong to a different job. This helps the user understand they're seeing a shared PO.

## View Modes

This design is the **Full** view. A **Lite** view will be defined later — it will hide or simplify some elements, but the specifics are not yet determined. The implementation should use the existing `viewMode` store to conditionally render, leaving Lite behavior as a follow-up.

## Prerequisites (API/Backend Changes)

These changes are required before or during implementation of the UI:

### Purchase Order Data

The current API does not support fetching POs by job:
- **PO ViewSet**: Add `?job=` filter parameter to `PurchaseOrderViewSet.get_queryset()`. Note: `PurchaseOrder` has no direct `job` FK — the link is through `PurchaseOrderLineItem.job`. Filter via `qs.filter(purchaseorderlineitem__job=job_id).distinct()`
- **PO Serializer**: Add a read-only `business_name` field (from `business.name`) so the "Vendor" column can display a name, not just an ID
- **JobDetailPage.svelte**: Add API call to fetch `/api/purchase-orders/?job={id}`

### Task Assignee Display Name

The Task serializer returns `assignee` as a user ID. For the "Assigned" column:
- Add a read-only `assignee_name` field to `TaskSerializer` (e.g., `user.get_short_name()` or `user.first_name + last initial`)

### Email Data

The `EmailRecord` model stores only `message_id` and job link. `TempEmail` caches metadata (subject, from_email, date_sent) but is cleaned up after a retention period.

**Minimum viable approach**: Show emails in the history timeline using whatever `TempEmail` data is available. If `TempEmail` has been cleaned up, the email entry still appears but shows only "Email (details no longer cached)" with a "View full email" link (which would require IMAP access or the user's email client). The expandable inline preview only renders when `TempEmail` data exists.

**Future improvement**: Persist subject/sender/snippet permanently on `EmailRecord` itself so previews survive cleanup. This is out of scope for this spec.

## Loading and Error States

Use the existing loading/error patterns from `JobDetailPage.svelte`. No changes to the loading UX are in scope — the page shows a loading state until all data is fetched, then renders the full view.

## Mockups

Interactive mockups are in `.superpowers/brainstorm/1604-1774208657/`:
- `job-detail-emails.html` — final version with all features (history + emails + accordions)
- Earlier iterations show design evolution

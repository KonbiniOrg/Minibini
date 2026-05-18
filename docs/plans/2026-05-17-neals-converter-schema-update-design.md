# Neal's Data Converter — Schema Update & Kanban CSV Integration

**Status:** Design — approved for spec review
**Date:** 2026-05-17

## 1. Background & goal

`nealsdata/convert_neals_data.py` turns a FreeAgent Excel export into a Django
`loaddata` fixture JSON used as realistic test data. The script targets an
obsolete data model: it emits `jobs.workorder` (a model that no longer exists),
puts a raw `rate`/`units` on `Task` (gone — `Task` now needs a `rate_scheme`
FK), sets a dead `task` field on line items, and produces ~47k records from
builders that have drifted well past the intended scope.

This project re-targets the converter to the **current** Minibini schema
(per `docs/designs/data-constraints.md`) and integrates a second input — a
Kanban board CSV export (`nealsdata/datasets/neals kanban.csv`) — which becomes
the spine that defines which Jobs exist.

**Inputs (current files):**
- `nealsdata/datasets/company-export-220382-2026-05-18-02-19.xlsx` — FreeAgent export
- `nealsdata/datasets/neals kanban.csv` — Kanban board export (tab-delimited despite the extension)

## 2. Approach

**Targeted rewrite (Approach C).** Keep the data-shape-tuned parsing
primitives (Excel loader, line-item header-row detection, contact-mismatch
handler, date/decimal/revision parsers). Rewrite only the model-building and
reconciliation layer — the part that is actually wrong — and add the CSV path.
Builders that produced the bloat (`_build_implicit_jobs`,
`_build_recent_unlinked_estimates`) and the obsolete WorkOrder path are deleted.

## 3. File structure

```
nealsdata/
  convert_neals_data.py    # thin CLI entry (argparse -> orchestrator)
  converter/
    __init__.py            # empty (per CLAUDE.md __init__ rule)
    loaders.py             # ExcelDataLoader (kept ~as-is) + new KanbanCsvLoader
    parsing.py             # date/decimal/name/revision-suffix helpers,
                           #   line-item header-row detection, ContactMismatchHandler
    build.py               # model builders, rewritten against current schema
    reconcile.py           # cross-model status/date reconciliation
    orchestrator.py        # NealsDataConverter — wires phases together
```

`loaders.py` and `parsing.py` are lifted from the existing script with minimal
change. `build.py` and `reconcile.py` are the rewrite.

## 4. Model mapping

Models the rebuilt converter **emits**:

| Source | Minibini model(s) | Notes |
|---|---|---|
| Kanban CSV card | `jobs.job` | spine — one Job per matched recent card (≈100) |
| distinct `(algorithm, rate, unit_label, AC)` | `jobs.ratescheme` | derived from estimate line items (§8) |
| estimate line items (labor-classified) | `jobs.task` | copied; estimate keeps its line items |
| estimate line items (material-classified) | `inventory.material` | copied; estimate keeps its line items |
| estimate line items (finished-goods) | `deliverables.deliverable` | synthesized (§7) |
| Estimates | `estimates.estimate` + `estimatelineitem` | matched Estimate + its version chain |
| Invoices | `invoicing.invoice` + `invoicelineitem` | via project-name link |
| Bills | `purchasing.bill` + `billlineitem` + `purchaseorder` + `purchaseorderlineitem` | via project-name link |
| Price List Items | `inventory.pricelistitem` | full catalog |
| Contacts (referenced only) | `contacts.business` + `contacts.contact` | trimmed |
| — | `core.user`, `core.configuration`, `core.accountingcategory` | base set |

**Not emitted** (lean scope): `jobs.workorder` (removed from the system),
`EstWorksheet`, `PlanTask`, `PlanMaterial`, `Earmark`, `Shipment`/`ShipmentItem`,
the `EstimateLineItemSource`/`InvoiceLineItemSource` polymorphic tables,
`HistoryEntry`, and `jobs.blep`.

**Dropped builders / sheets:** Projects→Job, WorkOrder, the FreeAgent `Tasks`
and `Timeslips` sheets (they only ever linked to Projects, which are old and
not converted), `_build_implicit_jobs`, `_build_recent_unlinked_estimates`.
The `Projects` sheet is still *read* — purely as the name key that links
Estimates ↔ Invoices ↔ Bills.

## 5. The Kanban CSV spine

`KanbanCsvLoader` reads the tab-delimited file (skipping the leading `sep=\t`
line). The CSV columns are: `Name`, `Card type`, `Card color`, `Description`,
`Due date`, `External ID`, `Notes`, `est *cut* time`, `est ASS time`, `est $`,
`Created at`, `Archived at`, `Block reason`.

Process:

1. Sort cards by `Created at`, newest first.
2. For each card: `External ID` → match a FreeAgent **Estimate** by estimate
   number (`Reference`). No match → discard the card.
3. Validate the CSV `Name` (a `Business`, `Contact`, or `Business (Contact)`
   string) against the matched estimate's project client org/name. Mismatch →
   discard the card.
4. Create a **Job** for the matched estimate. Its required `contact` FK is
   resolved from the estimate's project client (org + name) via the existing
   contact-resolution logic; the CSV `Name` is the validation check in step 3,
   not the primary contact source. Stop after ≈100 successful Jobs
   (`--limit`, default 100).
5. Attach to the Job: the matched Estimate and its version chain; and via the
   estimate's project name, the related Invoices and Bills.

CSV field application on a matched Job:

| CSV column | Effect |
|---|---|
| `Due date` | → `Job.due_date` |
| `Description` + `Notes` (joined) | → `Job.description` (overrides FreeAgent value) |
| `Archived at` | → `Job.completed_date` (only when the Job is in a terminal status) |
| `est *cut* time` | → `est_worker_time` on the first Task whose name contains `cut` (hours → Duration) |
| `est ASS time` | → `est_worker_time` on the first Task whose name contains `assemb`/`ass` |
| `Created at` | cross-checked against the estimate's created date; not written |
| `est $`, `Card type`, `Card color` | ignored |

If a cut/assembly time has no matching Task by name substring, that number is
discarded; the converter reports a tally of discards.

## 6. Estimate line items: filtering

Every estimate line item carries an **`Item Type`** column. Observed values:
`-no unit-` (bulk), `Hours`, `Days`, `Comment`, `Products`, `Services`,
`Expenses`, `Discount`, `Credit`.

- **`Comment` line items are skipped entirely.** These are boilerplate
  disclaimers and customer-provided-material notes — not billable lines. They
  are not copied to the estimate, a Task, a Material, or a Deliverable.

The estimate retains all of its **non-Comment** line items unchanged. Tasks,
Materials, and Deliverables are *copies* derived from them — the line items
themselves are never moved or deleted. Invoices are not used for this carry-over.

## 7. Estimate line items → Tasks / Materials / Deliverables

### Classification

Each non-Comment estimate line item is classified, `Item Type` first:

| `Item Type` | Classified as |
|---|---|
| `Hours`, `Days` | Task (`algorithm=elapsed_time`) |
| `Services` | Task (`algorithm=flat_fee`) |
| `Products` | Material |
| `Expenses` | Material |
| `Discount`, `Credit` | line item only — no Task/Material (negative price) |
| `-no unit-` | **keyword heuristic** (below) |

`-no unit-` is the vast majority of line items, so the keyword heuristic
carries most of the classification load:

- **Material** if the description hits a material keyword (`plywood`, `acrylic`,
  `MDF`, `sheet`, `hardwood`, `melamine`, `Sintra`, `aluminum`, `board feet`,
  `lumber`, `plastic`, `steel`, … — list refined during implementation) or the
  units read as raw stock.
- **Task** otherwise (job-shop estimate lines are mostly labor/charges, so
  unmatched lines default to Task).

### Task fields (copied from a line item)

`job`, `rate_scheme` (§8), `name` = line description truncated to 255,
`description` = full line text, `est_qty` = line `Quantity`,
`est_worker_time` = from a CSV cut/assembly match if any, `active_modifiers` = [],
`status` from Job state (§10), `sort_order` sequential per Job.

### Material fields (copied from a line item)

`job`, `description`, `quantity` = line `Quantity`, `units`, `sell_price` =
line `Price`, `unit_cost` = 0, `accounting_category` = line's AC or a default
`MAT` category, `consumption_state` = `pending`, `price_list_item` = None,
`source_plan_material` = None, `po_line_item` = None.

**Task link:** if the Job has a Cut Task (the first Task whose name contains
`cut`), set `Material.task` to it; otherwise leave `task` null (the Material
floats on the Job).

### Deliverables

A second pass over the same non-Comment line items picks those that read as
finished goods (countable `Quantity`, not raw material, not pure labor) and
emits a `deliverables.deliverable` (`description`, `qty_ordered` = Quantity,
`units`, `sort_order`). One line item may inform a Task/Material **and** a
Deliverable.

If a Job ends up with **zero** Deliverables, synthesize one with
`description = "Fake Deliverable"`, `qty_ordered = 1`, `units = each` — so the
data-constraints §2.12 invariant (a non-draft estimate's Job has ≥1 Deliverable)
holds. The `"Fake Deliverable"` label is deliberate, flagging it for review.

## 8. RateScheme derivation

`Task` requires a non-null `rate_scheme` FK. Each Task-classified line item
yields a RateScheme, deduped on `(algorithm, rate, unit_label, accounting_category)`:

- `rate` = the line item unit `Price`
- `algorithm` = `elapsed_time` if `Item Type` is `Hours`/`Days` or units ≈
  `hours`; `entered_qty` if units is a count (`each`/`ea`/`pcs`/numeric);
  otherwise `flat_fee`
- `unit_label` = the line's units (fallback `hours`)
- `accounting_category` = the line's AC, or a default service category
- `name` = generated unique, e.g. `"Elapsed $95.00/hours"`
- `modifiers` = []
- `replaced_by` / `replaced_at` = null

RateSchemes are built before Tasks so every Task can reference one.

## 9. Filtering & scope

- **Spine:** Kanban cards newest-first; build Jobs until ≈100 succeed
  (`--limit`, default 100).
- **Per Job pulled in:** the matched Estimate + its version chain;
  project-linked Invoices; project-linked Bills (each Bill also produces a
  PurchaseOrder + line items).
- **Contacts / Businesses:** emitted only when referenced by a kept Job or
  Bill (down from ~870 businesses / ~962 contacts in the raw sheet).
- **Price List Items, Accounting Categories:** kept whole (small catalog data).
- **Users, Configuration:** base set (document-numbering keys, units list,
  retention keys, a `system` user, etc.).

## 10. Reconciliation

After all objects are built, `reconcile.py` enforces cross-model consistency:

- **Status maps** — Estimate `Draft/Sent/Approved/Rejected` →
  `draft/open/accepted/rejected`; Job `Completed/Active/Cancelled` →
  `completed/approved/cancelled`.
- **Estimate expiry** — an `open` estimate created more than 30 days ago →
  `expired`; when it is the latest/only estimate on its Job, the Job →
  `rejected`.
- **Versioned estimates** — a `-v1`/`-v2`/etc. suffix in the reference marks a
  version chain: older versions → `superseded`, `parent` FK linked, timestamps
  ordered.
- **Job dates** — `created_date` from the estimate; `due_date` and
  `completed_date` from the CSV; `start_date` per the original convert.md
  rules (explicit start, else V1 estimate date for approved, else created_date
  for completed-without-estimates).
- **Task status** — derived from Job status (completed Job → all Tasks
  `complete`; otherwise `pending`).
- **Invoiced-work rule** — a Job with both an estimate and a non-draft invoice
  whose totals (Σ qty×price) are within 10% → its Tasks marked `complete`.
- **Document numbers** — `job_number` `J{year}-{counter:04d}`; estimate,
  invoice, and PO numbers generated by the same pattern.

## 11. Output & testing

- **Output:** Django `loaddata` fixture JSON — the `[{model, pk, fields}]`
  shape — written to `--output` (default `nealsdata/datasets/converted.json`).
- **Testing:** a Django test that runs `loaddata` on the generated fixture
  **into the test database** (never the dev DB — per CLAUDE.md) and asserts
  row counts and FK integrity. This is the verification that the rebuilt
  converter produces loadable, self-consistent data.

## 12. Out of scope (possible future work)

- The planning layer (`EstWorksheet`, `PlanTask`, `PlanMaterial`) and the
  estimate-acceptance carry-over story.
- `Earmark` inventory side effects, `Shipment`/`ShipmentItem`.
- `HistoryEntry` audit-trail generation.
- The new `Expenses` sheet and the `Category Name` / `Stock Item Code` columns
  on estimate line items.
- A standalone `validate_data.py`.

## 13. Open items for post-load review (by the user)

After the fixture loads into the Konbini app, the user will review and likely
adjust:

- RateScheme groupings and rates.
- Material vs Task classification of `-no unit-` line items (keyword heuristic).
- Deliverable detection — especially any `"Fake Deliverable"` placeholders.

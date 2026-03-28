# Model Inventory — Proposed App Placement

**Date:** 2026-03-07
**Purpose:** Reference for app reorganization planning

MOVED items marked with <--
NEW items marked with ++
UNPLACED items at the bottom

---

## apps/core

    Model                   Abstract?   Inherits
    User                    no          AbstractUser
    Configuration           no          Model
    EmailRecord             no          Model
    TempEmail               no          Model
    LineItemType            no          Model
    BaseLineItem            yes         Model
    AbstractWorkContainer   yes         Model              <-- from jobs
    Unit                    no          Model              ++
    HistoryEntry            no          Model              ++

## apps/jobs

    Model                   Abstract?   Inherits
    Job                     no          Model
    WorkOrder               no          AbstractWorkContainer
    Task                    no          Model
    TaskBundle              no          Model
    Blep                    no          Model
    Shift                   no          Model              ++

## apps/estimates

    Model                   Abstract?   Inherits
    Estimate                no          Model              <-- from jobs
    EstWorksheet            no          AbstractWorkContainer  <-- from jobs
    EstimateLineItem        no          BaseLineItem       <-- from jobs
    WorkOrderTemplate       no          Model              <-- from jobs
    TaskTemplate            no          Model              <-- from jobs
    TemplateBundle          no          Model              <-- from jobs
    TemplateTaskAssociation no          Model              <-- from jobs

## apps/contacts

    Model                   Abstract?   Inherits
    Contact                 no          Model
    Business                no          Model
    PaymentTerms            no          Model
    Tag                     no          Model              ++

## apps/invoicing

    Model                   Abstract?   Inherits
    Invoice                 no          Model
    InvoiceLineItem         no          BaseLineItem

## apps/purchasing

    Model                   Abstract?   Inherits
    PurchaseOrder           no          Model
    Bill                    no          Model
    PurchaseOrderLineItem   no          BaseLineItem
    BillLineItem            no          BaseLineItem
    Expense                 no          Model              ++

## apps/inventory

    Model                   Abstract?   Inherits
    Earmark                 no          Model
    InventoryAdjustment     no          Model
    PriceListItem           no          Model              <-- from invoicing
    Material                no          Model              <-- from jobs

## apps/search

    No models.

---

## Unplaced new models

    Payment                 no          Model              ++ TBD (placeholder, Stripe)

## Model changes needed

    EmailRecord             Add FKs to PurchaseOrder and Bill (currently only Job)

## Design decisions

    EmailTemplate           Stored as Configuration key/value pairs, not a separate model
    AuditEntry              Combined with user notes into HistoryEntry (in core)

---

Totals: 33 concrete, 3 abstract, 7 apps (estimates is new)

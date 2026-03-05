# Materials & Inventory Design

**Date:** 2026-03-04
**Status:** Early thinking

## Core Idea: Separate Materials from Tasks

Currently tasks handle both labor and materials, and the mapping to estimate/invoice line items is awkward because they're fundamentally different things. Proposed separation:

- **Tasks** = labor only. Hours, rate, assignment, time tracking (bleps). Becomes labor line items on estimates/invoices.
- **Materials** = physical stuff consumed by a task. Each material is attached to a task. Becomes material line items on estimates/invoices.

### Material Model

```
Material:
  task           (FK, required) — which task consumes this
  inventory_item (FK, optional) — linked to inventory, or NULL for one-offs
  description    — auto-filled from inventory item if linked, freeform if not
  quantity
  unit_cost
  markup / sell_price
```

Not all materials are inventory items. One-off purchases (bought specifically for one job, never stocked) have no inventory link — just a description, quantity, and cost. The inventory integration (QOH tracking, availability, earmarking) only kicks in when `inventory_item` is populated.

### Impact on Estimates & Invoices

Estimate/invoice line items come from two sources:
- **Labor line items** ← tasks (hours × rate)
- **Material line items** ← materials (quantity × sell_price)

Worksheet → estimate generation becomes two straightforward mappings instead of one complex one.

### Impact on Work Orders

The work order gets a clear "materials list" / pull list — what needs to come out of inventory (or be purchased) for this job. Separate from the task list which is about labor scheduling.

---

## Inventory: Automatic QOH Updates

QOH should update automatically on receive and on consumption, not just by hand.

### QOH Increases — PO Receipt

When a PO is received (`POST /api/purchase-orders/{id}/receive/`), QOH should increase for any PO line items linked to inventory items. This is a side effect of the existing receive action.

**Requires:** A link between PO line items and inventory items (optional FK or matching mechanism).

### QOH Decreases — Consumption

With the materials model, consumption is tied to materials that reference inventory items. When a material is consumed (task completion or explicit action), QOH decreases for linked inventory items. Materials without an inventory link have no QOH side effects.

### Manual Adjustments

Waste, damage, stock count corrections. A dedicated adjustment endpoint provides audit trail:
- `POST /api/inventory-items/{id}/adjust/` — `{quantity_change, reason}`

Better than raw PATCH on QOH because it captures why.

---

## PO-to-Job Linking

Currently a PO links to 0 or 1 jobs. Real-world purchasing often involves one PO with items for multiple jobs:

> "Buy 20 sheets of plywood X (for Job A), 10 sheets of plywood Y (for Job B), and 5 of plywood Z (for Job C)" — all on one PO to one vendor.

The job association needs to move from the PO level to the **PO line item level**. Each line item could optionally be earmarked for a specific job.

### Implications

- PO line item gets an optional `job` FK
- A PO's associated jobs become derived (the set of jobs referenced by its line items)
- The PO-level `job` FK may still be useful as a "primary job" or could be dropped entirely in favor of line-item associations
- Job detail view (rich response) would need to pull POs where *any* line item references the job, not just POs directly linked
- Received inventory items earmarked for a job could be flagged/reserved in inventory

---

## Inventory-Integrated Workflow

### The Full Chain

```
Estimate worksheet material: "20 sheets Plywood X"
  → links to inventory item "Plywood X"
  → system shows: 3 available in stock, 17 needed
  → user can generate PO for the shortfall (17)

Job approved:
  → 3 available sheets become "earmarked for Job A"
  → PO for 17 is linked to Job A at line-item level

PO received:
  → 17 sheets added to QOH, immediately earmarked for Job A

Work order task: "Install plywood shelving"
  → has material: inventory item "Plywood X", qty 20
  → when consumed (task complete or explicit action), earmarked → consumed, QOH decreases
```

### Inventory Quantities

Rather than a single QOH, track:
- **QOH (total)** — physically in the shop
- **Available** — QOH minus earmarked (what can be used for new jobs)
- **Earmarked** — reserved for specific jobs, with job reference

### Estimate → Inventory → PO Flow

When adding a material to an estimate worksheet that references an inventory item:
1. System checks available QOH
2. Shows shortfall if any
3. Offers to create/add to a PO for the shortfall
4. PO line items are linked to the inventory item and earmarked for the job

This is a front-end UX flow backed by API endpoints — probably:
- `GET /api/inventory-items/{id}/availability/` — returns QOH, available, earmarked breakdown
- Existing PO creation endpoints handle the rest

---

## Open Questions

- Does the PO-level job FK stay (as a convenience/default) or go away?
- Can earmarked items be reassigned to a different job if plans change?
- What triggers consumption — task completion, explicit "consume" action, or both?
- How to handle partial consumption (used 15 of 20 earmarked sheets)?
- Should earmarking happen at job approval, or when the work order is created?

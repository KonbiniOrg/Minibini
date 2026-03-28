# Material-to-PriceListItem Lifecycle

## Decision Date: 2026-03-06

## Problem

Materials on tasks can be "freeform" (no PriceListItem link) or PLI-linked. Freeform
materials lack a `line_item_type`, which is required for estimate line items and invoicing.
The question: should we force all materials to have a PLI, and if so, when?

## Decision

Materials do NOT require a PLI at creation time. PLI linkage is deferred to the WorkOrder
phase, and enforced at invoicing. The lifecycle follows the existing document pipeline:

### Phase 1: Worksheet (Estimating)

Material is a **planning sketch**. The user may not know the exact product, supplier, or
cost yet. Fields available:

- `description` (free text)
- `quantity` (estimated)
- `unit_cost` / `sell_price` (rough estimates, may be zero)
- `line_item_type` (required -- needed for estimate line item generation)
- `price_list_item` (optional -- linked if selecting from catalog)

No PLI is required. No PLI is auto-created. This keeps estimating fast and friction-free.

### Phase 2: Estimate Generated

`EstimateGenerationService` creates `EstimateLineItem` records from materials:

- PLI-linked materials: `line_item_type` comes from `material.price_list_item.line_item_type`
- Freeform materials: `line_item_type` comes from `material.line_item_type` directly

**Bundle material breakout:** Materials on bundled tasks are currently rolled into the
bundle's single line item price. However, the user may want specific materials to appear
as separate line items on the estimate (e.g., an expensive sheet good that should be
visible to the customer, while fasteners stay bundled). This requires a per-material flag
(e.g., `separate_line_item` boolean on Material) that tells `EstimateGenerationService` to
pull that material out of the bundle total and create its own `EstimateLineItem`, similar
to how direct-task materials work. The bundle price is reduced accordingly.

### Phase 3: Estimate Accepted, WorkOrder Created

Tasks and their materials are copied to the work order. Materials are still sketches at
this point, but now the job is real.

### Phase 4: WorkOrder Being Worked

This is where materials get firmed up. The system flags materials without PLI links:

- User links to an existing PLI, or
- User creates a new PLI inline (with option to keep it active in the catalog or mark
  inactive as a one-off)

At this point, costs are finalized and POs can be created against the PLI.

### Phase 5: WorkOrder to Invoice

Invoice line items require PLI-backed materials. A material without a PLI cannot be
invoiced. This is the hard gate -- no nagging earlier in the pipeline, just enforcement
at the end.

This parallels the Estimate/Worksheet <-> Invoice/WorkOrder symmetry:
- Worksheet is the planning scratchpad for an Estimate
- WorkOrder is the execution context for an Invoice

## Why Not Require PLI Earlier?

- **Estimating friction**: Creating a PLI requires code, description, prices, units,
  line_item_type. Too much ceremony for "I think we'll need some brackets."
- **PLI table clutter**: Creating PLIs for rejected estimates wastes catalog space.
  Deferring to acceptance means only real work creates records.
- **Cost uncertainty**: At worksheet time, you often don't know the actual cost. PLI
  prices should reflect real purchase/sell prices, not rough guesses.

## Implementation Steps

1. **Now**: Add `line_item_type` FK to Material model. Wire it through
   `EstimateGenerationService._create_material_line_item()` as secondary source
   (after PLI). Update material forms to include the field.
2. **Soon**: When WorkOrder is created from accepted estimate, copy Materials to WO tasks.
3. **Later**: WO material view flags unlinked materials. Inline PLI creation flow.
   Invoice generation gate requiring PLI on all materials.

## Related

- `docs/2026-03-04-materials-and-inventory-design.md` -- original materials design
- `docs/plans/2026-03-04-materials-inventory-implementation.md` -- implementation plan

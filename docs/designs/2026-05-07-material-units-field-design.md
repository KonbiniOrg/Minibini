# `units` field on Material

## Motivation

`MaterialBase` (abstract, `apps/inventory/models.py:95`) defines `description`,
`quantity`, `unit_cost`, `sell_price`, `price_list_item`, and
`accounting_category` — but no `units` field. The three concrete subclasses
(`PlanMaterial`, `TemplateMaterial`, `Material`) inherit this gap.

Meanwhile every neighbour that quantifies stuff carries `units`:

- `PriceListItem.units` — `CharField(max_length=50, default='none')`
  (`apps/inventory/models.py:39`)
- `BaseLineItem.units` — same shape, with `_populate_from_pli` copying it
  from the linked PLI (`apps/core/models.py:213, 255-265`)
- `Task.units`, `TaskTemplate.units` — covered by the configurable-units
  rollout (`docs/designs/2026-03-30-configurable-units.md`)

Today a Material like `quantity=10, unit_cost=5.00, sell_price=8.00`
records "ten of *something*" — it could be 10 hours, 10 sheets, 10 boxes,
the system can't tell. The unit context is recovered downstream only when
a code path re-reads from the linked PriceListItem. Two examples in the
current codebase:

- `EstimateWizardService._atom_units` (`apps/estimates/services.py:599-613`)
  defensively walks `plan_material.price_list_item.units`, falling back to
  `'none'` if there's no PLI link. Freeform PlanMaterials (legitimate per
  the materials-on-jobs design) lose units entirely.
- `EstimateGenerationService._create_material_line_item` (around
  `apps/estimates/services.py:224-232`) builds an EstimateLineItem with
  `units=pli.units`, which means any user-visible unit override on the
  PlanMaterial would be silently re-derived from the PLI.

The `2026-03-30-configurable-units` design enumerates the models that
carry `units` and Material is conspicuously absent — this appears to be
an oversight rather than a deliberate exclusion. This doc proposes adding
the field, mirroring the BaseLineItem pattern.

## Scope

**In scope:**

- Add `units = CharField(max_length=50, default='none')` to `MaterialBase`,
  propagating to `PlanMaterial`, `TemplateMaterial`, `Material`.
- Extend `MaterialBase._populate_from_pli` to copy `units` from the linked
  PriceListItem.
- Validate against the configured `units_list` (per the configurable-units
  design).
- Update API serializers (`MaterialSerializer`, `MaterialWriteSerializer`,
  `PlanMaterialSerializer`, `PlanMaterialWriteSerializer`, the
  yet-to-be-written `TemplateMaterialSerializer`) and any forms.
- Update carry-over paths so `units` rides along with the other
  `MaterialBase` fields.
- Update fixtures and add tests.

**Out of scope:**

- Units divisibility (whole-number-only enforcement). Tracked separately
  per `project_units_divisibility` memo.
- Backfilling units onto historical Materials beyond fixture cleanup —
  pre-production, no real data to migrate.
- Any change to `BaseLineItem.units` semantics or the `units_list`
  Configuration entry. Both are assumed to be in place.

## Schema change

One migration touches three tables (`plan_materials`, `template_materials`,
`materials`) by adding `units` to the abstract base:

```python
# apps/inventory/models.py — MaterialBase
class MaterialBase(models.Model):
    description = models.CharField(max_length=255, blank=True, default='')
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    units = models.CharField(max_length=50, default='none')   # ← NEW
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    sell_price = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    price_list_item = models.ForeignKey(...)
    accounting_category = models.ForeignKey(...)

    class Meta:
        abstract = True
```

Default `'none'` matches the rest of the codebase. Pre-production: no
RunPython data step needed; existing rows get `'none'` automatically and
fixture rows are updated by hand (see Fixtures below).

## Service-layer changes

### `_populate_from_pli`

```python
def _populate_from_pli(self):
    if self.price_list_item:
        if not self.description:
            self.description = self.price_list_item.description[:255]
        if self.units == 'none' or not self.units:                 # ← NEW
            self.units = self.price_list_item.units                 # ← NEW
        if self.unit_cost == Decimal('0.00'):
            self.unit_cost = self.price_list_item.purchase_price
        if self.sell_price == Decimal('0.00'):
            self.sell_price = self.price_list_item.selling_price
        if not self.accounting_category:
            self.accounting_category = self.price_list_item.accounting_category
```

The `'none' or not` guard matches `BaseLineItem._populate_from_pli`
(`apps/core/models.py:264`) verbatim — user-set values survive, the
default is treated as unset.

### Validation

The shared `validate_units` validator in `apps.core` (per the
configurable-units design) runs at the serializer layer. Model field has
no `validators=[...]` attached, again matching `BaseLineItem.units`. This
keeps fixture loading and admin work flexible while guarding the API
boundary where it matters.

### `EstimateWizardService._atom_units`

Currently reaches through to `plan_material.price_list_item.units`. Change
to read `plan_material.units` directly:

```python
if isinstance(atom_instance, PlanMaterial):
    return atom_instance.units    # was: atom_instance.price_list_item.units (if PLI) else 'none'
```

The PLI-derivation behaviour is now baked into the field itself via
`_populate_from_pli`, so reading the field is sufficient and additionally
respects user overrides. Same change applies anywhere else that reaches
through `material.price_list_item.units` for display.

### `EstimateGenerationService._create_material_line_item`

Currently sets `units=pli.units` when generating an `EstimateLineItem`
from a PlanMaterial. Change to `units=plan_material.units` so that user
overrides on the PlanMaterial flow through to the line item rather than
being silently re-derived. (See **Open question 1** below — this is one
side of a design decision.)

## API changes

### Serializers

Add `units` to the field lists in:

- `apps/api/tasks/serializers.py` — `MaterialSerializer` (read),
  `MaterialWriteSerializer` (write).
- `apps/api/worksheets/serializers.py` — `PlanMaterialSerializer` (read),
  `PlanMaterialWriteSerializer` (write).
- The TemplateMaterial serializer (location TBD when that endpoint
  lands; the materials-on-jobs design specifies
  `GET/POST/PATCH/DELETE /api/work-templates/{id}/materials/`).

Each write serializer validates `units` against `units_list`.

### Endpoints affected (no new endpoints)

- `POST /api/jobs/{id}/materials/` — accepts `units` on creation.
- `POST /api/est-worksheets/{id}/plan-materials/` — accepts `units`.
- `POST /api/work-templates/{id}/materials/` — accepts `units`.
- `PATCH /api/materials/{id}/` — currently description-only per the
  materials-on-jobs design. **See Open question 2** for whether `units`
  joins the editable-after-creation set.

The new `GET /api/settings/units/` endpoint already exists for the SPA
to fetch the configured list.

## Frontend changes

Material-related Svelte forms become a units `<select>` populated from
the `units_list` store. Surfaces to update:

- The Add-material form on `JobDetail` (or wherever task-less Material
  creation lives once the materials-on-jobs work lands).
- The PlanMaterial form on the worksheet UI.
- The TemplateMaterial form on the WorkTemplate admin surface.
- Display surfaces that currently render `qty: 5` (e.g. Material list rows,
  the worksheet material list, expense-bound material display) — append
  the units label so they read `5 sheets`.
- `Material.__str__` and `PlanMaterial.__str__` are used in admin and
  shell debugging. Worth updating to include units for consistency.

## Carry-over paths

Every place where one Material-flavoured row is built from another needs
to copy `units` alongside the existing `MaterialBase` fields:

| Path | Source → Target |
|---|---|
| `JobService.copy_from_worksheet` | PlanMaterial → Material (both task-attached and task-less) |
| `Job.populate_from_estimate` | EstimateLineItem-sourced PlanMaterial → Material |
| `WorkTemplate.generate_materials_for_worksheet` | TemplateMaterial → PlanMaterial |
| `WorkTemplate.generate_materials_for_job` | TemplateMaterial → Material |
| `EstimateGenerationService._create_material_line_item` | PlanMaterial → EstimateLineItem |
| `MaterialService.create_on_job` | request payload → Material (units accepted as input) |
| `EstimateWizardService.get_source_pool` / `_atom_units` | PlanMaterial → atom display |

Each is mechanical: where the existing code copies `description`/`qty`/
`unit_cost`/`sell_price`, it now also copies `units`.

## Fixtures

Material rows in fixtures need a `units` value. Affected files (subset of
those listed in the materials-on-jobs design — the ones that actually
contain material rows):

- `fixtures/unit_test_data.json`
- `fixtures/workorder_from_estimate.json`
- `fixtures/mixed_lineitems.json`
- `fixtures/invoicing_data.json`
- `fixtures/large_datasets/nealseed.json`
- any `nealseed*.json` at repo root

Default `'none'` is a valid Configuration `units_list` entry, so fixture
rows that don't care about units can simply leave the field defaulted
(or set it explicitly for clarity). PLI-linked material fixtures should
mirror the PLI's units to model the populate behaviour realistically.

## Tests

New tests in (or extending) `tests/test_material_fields.py`:

- `units` defaults to `'none'` on all three concrete models.
- `_populate_from_pli` copies `units` from the PLI when the material
  has the default value, and respects an explicit override.
- API write serializers reject a `units` value that isn't in
  `units_list`.
- PlanMaterial → Material carry-over preserves `units`
  (`JobService.copy_from_worksheet`).
- TemplateMaterial → PlanMaterial / TemplateMaterial → Material
  carry-over preserves `units` (template generation paths).
- PlanMaterial → EstimateLineItem carry-over preserves `units`,
  including the override case (`_create_material_line_item`).
- `EstimateWizardService._atom_units(plan_material)` returns the
  PlanMaterial's units field (not the PLI's), including the
  freeform-no-PLI case where the field carries the user's chosen unit.

Per `CLAUDE.md`: TDD — write the failing tests first.

## Resolved: PLI-linked rows are immutable, with a pricing carve-out

This is the core rule that drops out of the units-drift concern, and it
expands the original scope of this feature. Worth stating up front.

### The invariant

A Material (or PlanMaterial or TemplateMaterial) with a non-null
`price_list_item` is a faithful instance of that PLI. The labelling and
categorization fields — `description`, `units`, `accounting_category` —
are populated from the PLI at create time and locked thereafter. To
customize any of those values, the user deletes the row and re-adds it
as a freeform Material (no PLI link).

**Pricing fields (`unit_cost`, `sell_price`) are an exception** — see
the next subsection. Pricing on a PLI-linked Material can be edited
in-place because, unlike units, a pricing override doesn't corrupt the
inventory math (which is quantity-based, not price-based). A real shop
flow needs this: when a vendor invoices a different price than the
catalog suggests, the user wants to capture that on the Material *and*
optionally push the new price back to the PLI for future reference.

**Why this is necessary, not just nice.** Without the invariant, a user
could edit `material.units` from `"sheets"` to `"lbs"` on a
PLI-linked-and-inventoried Material whose PLI is in `"sheets"`. Then
`MaterialService.consume(material)` would do
`pli.qty_on_hand -= material.quantity` — decrementing
sheets-of-stock by a quantity-of-pounds. Garbage data with no path to
detect or recover. The inventory math only works if the Material's units
match the PLI's.

The same reasoning extends to non-inventoried PLI-linked Materials and
to PlanMaterial / TemplateMaterial: the PLI link semantically declares
"this *is* that product," and overrides break that meaning.

### What this changes

This tightens the materials-on-jobs design
(`docs/designs/2026-04-14-materials-on-jobs-design.md`) on three
endpoints:

| Endpoint | Old rule | New rule |
|---|---|---|
| `POST /api/jobs/{id}/materials/` | accepts `{description, quantity, unit_cost, sell_price, price_list_item?, accounting_category?}` | freeform create accepts `{description, units, quantity, unit_cost, sell_price, accounting_category?}`; PLI-linked create accepts only `{price_list_item, quantity}` and copies the rest from the current PLI |
| `PATCH /api/materials/{id}/` | description-only edit | freeform: allows `description` + `units` + `unit_cost` + `sell_price`; PLI-linked: allows `unit_cost` + `sell_price` (with optional `propagate_to_pli` flag, see below). All other field edits on PLI-linked rows return 400 with "PLI-linked materials are immutable except for pricing; delete and re-add as freeform to change other fields" |
| `POST /api/est-worksheets/{id}/plan-materials/` | (same shape as `/jobs/.../materials/`) | (same split) |
| `PATCH /api/plan-materials/{id}/` (or equivalent) | (same as `/materials/{id}/`) | (same split) |
| Template materials endpoint (`POST/PATCH /api/work-templates/{id}/materials/`) | accepts the full body | freeform: full body. PLI-linked create accepts only `{price_list_item, quantity, sort_order}`. PLI-linked PATCH: 400 — TemplateMaterial has no price-edit carve-out (see TemplateMaterial section below for why) |

State-machine ops (Consume, Restock, Draw-more) are unaffected — they
remain available on PLI-linked Materials and operate on `quantity` /
`consumption_state` / `restocked_qty` only, which aren't part of the
invariant.

### Pricing carve-out: edit + propagate-to-PLI flow

Pricing fields (`unit_cost`, `sell_price`) on Material and PlanMaterial
are editable in-place even when the PLI link is set. Both fields can
move independently.

The PATCH body accepts an optional `propagate_to_pli` flag:

```
PATCH /api/materials/{id}/
{
  "unit_cost": "52.00",
  "sell_price": "78.00",
  "propagate_to_pli": true   // optional, default false
}
```

When `propagate_to_pli` is true and the PLI link is set, the same
transaction also updates the linked PLI's `purchase_price` (from
`unit_cost`) and `selling_price` (from `sell_price`) — only the fields
that actually changed get propagated. Atomic; no two-step race.

**No permission check.** The propagate-to-PLI action is open to any
authenticated user, even though general PriceListItem CRUD requires
`can_manage_financials`. This is a deliberate carve-out: capturing a
just-observed vendor price as you process a Material is a small
convenient action, not catalog management. It's not the only such
carve-out the system will need; a broader permissions rework is on the
roadmap, and we're treating this as one of several similar
narrowly-scoped exceptions.

**Frontend prompt.** After the user edits a price field on a PLI-linked
Material's edit form and clicks save, if either price differs from the
linked PLI's current `purchase_price` / `selling_price`, the form shows
one prompt: *"Update PLI with the new values?"* Yes → PATCH with
`propagate_to_pli: true`. No → PATCH with the flag false. The prompt is
the same regardless of which field(s) changed. Users without
`can_manage_financials` see the same prompt — the carve-out makes the
action universally available.

**No retroactive propagation.** Updating the PLI does not retroactively
touch other Materials currently linked to the same PLI. Each Material
keeps its captured price (some may differ from the new PLI value;
that's expected — they captured a different observation at a different
time). New Materials created after the PLI update pick up the new
price via `_populate_from_pli`.

**Edge cases:**

- Both prices identical to PLI's current values, `propagate_to_pli` set
  → silent no-op; the flag has nothing to do.
- Only one price changed → propagate that one field, leave the other
  side of the PLI alone.
- PLI is `is_active=False` → propagation still allowed; no point
  guarding catalog updates on a soft-deleted catalog item.

### TemplateMaterial: pricing pulled fresh from PLI at generation time

TemplateMaterial is a special case worth calling out separately because
its lifecycle is different from Material/PlanMaterial.

**How TemplateMaterial works today** (per the materials-on-jobs design):
TemplateMaterial lives on a `WorkTemplate`. When a user creates a
worksheet or job from that template,
`WorkTemplate.generate_materials_for_worksheet(...)` and
`generate_materials_for_job(...)` (defined at `apps/estimates/models.py:344-371`)
iterate `self.materials.all()` and create a PlanMaterial or Material for
each one, copying `description`, `quantity`, `unit_cost`, `sell_price`,
`price_list_item`, and `accounting_category` verbatim.

**The problem:** templates are reused for months or years. PLI prices
shift over that span. Today, a TemplateMaterial set up with
`unit_cost=40.00` keeps injecting `40.00` into every generated row even
after the linked PLI's `purchase_price` has been updated to `52.00`.
The template carries stale catalog data forward.

**The fix:** at generation time, branch on whether the TemplateMaterial
has a PLI link.

```python
def generate_materials_for_worksheet(self, worksheet, quantity=1):
    from apps.inventory.models import PlanMaterial
    for tm in self.materials.all():
        for _ in range(quantity):
            if tm.price_list_item_id:
                # PLI-linked: only carry quantity + PLI link.
                # _populate_from_pli fills description, units, pricing,
                # accounting_category from the *current* PLI.
                PlanMaterial.objects.create(
                    est_worksheet=worksheet,
                    plan_task=None,
                    quantity=tm.quantity,
                    price_list_item=tm.price_list_item,
                )
            else:
                # Freeform: template carries the explicit values.
                PlanMaterial.objects.create(
                    est_worksheet=worksheet,
                    plan_task=None,
                    description=tm.description,
                    quantity=tm.quantity,
                    units=tm.units,
                    unit_cost=tm.unit_cost,
                    sell_price=tm.sell_price,
                    accounting_category=tm.accounting_category,
                )
```

`generate_materials_for_job` gets the same branch.

**Consequences:**

- **PLI-linked TemplateMaterials don't need editable pricing fields.**
  The columns still exist on `template_materials` (inherited from
  `MaterialBase`), but they sit at 0.00 forever and nothing reads them.
  The TemplateMaterial editor in the WorkTemplate admin surface should
  hide the unit_cost/sell_price/units fields when a PLI is selected,
  showing only quantity (and sort_order).
- **Freeform TemplateMaterials still carry their pricing.** No PLI to
  pull from, so the template is the source of truth. The editor
  exposes all `MaterialBase` fields as today.
- **No price-edit carve-out on PLI-linked TemplateMaterial.** Unlike
  Material and PlanMaterial, TemplateMaterials are catalog
  configuration, not "I just observed this vendor price" instances.
  If the template's pricing is wrong, the user updates the underlying
  PLI directly (which then flows through to the next template
  generation). The PATCH endpoint for PLI-linked TemplateMaterial
  accepts only `quantity` and `sort_order`.

This change runs slightly outside the strict scope of "add units to
Material" but lives in the same code path and resolves the same class
of bug (stale snapshot data leaking forward in time). Worth doing
together.

### What this *doesn't* change

- No "unlink PLI" action. To customize a PLI-linked Material, the user
  deletes it and re-adds as freeform. Inventoried Materials release
  their earmark on delete (via `MaterialService._delete_internal` /
  full-Restock); freeform re-add carries no earmark — accounting stays
  consistent.
- Expense-bound Materials are still user-undeletable per the
  materials-on-jobs design. They're always PLI-linked (expenses with
  inventoried PLIs), so this restriction simply means: "expense-bound
  Materials are immutable by both rules at once." That's already the
  effective behaviour today.
- `BaseLineItem`-derived line items (`EstimateLineItem`, `InvoiceLineItem`,
  etc.) keep their existing override-friendly semantics. Line items are
  the historical record of what was sold; their units can legitimately
  diverge from the current PLI's units. This rule applies *only* to the
  three Material-flavoured rows.

### Enforcement

- **API serializer layer.** `MaterialWriteSerializer.update()` (and the
  PlanMaterial equivalent) on a PLI-linked instance accepts only
  `unit_cost`, `sell_price`, and `propagate_to_pli`. Any other field in
  the PATCH body returns 400. `create()` validates the body shape
  against PLI presence (freeform path requires labelling + pricing;
  PLI-linked path requires only `price_list_item` + `quantity`). The
  TemplateMaterial serializer is stricter on PATCH — PLI-linked rows
  accept only `quantity` and `sort_order`, no pricing.
- **Service layer.** `MaterialService.update(...)` (new, or extension
  of an existing edit path) handles the PLI propagation: when the
  request specifies `propagate_to_pli=true` and prices have actually
  changed, it updates the PLI's `purchase_price` / `selling_price` in
  the same transaction. No permission check required — the action is
  open to any authenticated user (see permissions carve-out above).
- **Model `clean()`.** Optional defence-in-depth: on a non-new
  PLI-linked instance, raise if any locked `MaterialBase` field
  (everything except `unit_cost` / `sell_price`) has changed from its
  loaded value. Implementation needs `_loaded_values` tracking on
  `__init__` / `from_db`. Worth doing if cheap; not blocking.
- **Frontend.** Material edit form, when PLI-linked, disables
  description / units / accounting_category and the linked PLI itself,
  but leaves unit_cost and sell_price editable. Banner: *"Linked to
  {pli.code} — {pli.description} ({pli.units}). Delete and re-add as
  freeform to change other fields."* On price edit + save, if either
  price differs from the linked PLI's current values, show the modal
  *"Update PLI with the new values?"* with Yes/No → translates to
  `propagate_to_pli=true|false` on the PATCH. Restock / Draw-more /
  Consume buttons remain.

### Consequences for `_populate_from_pli`

Once PLI-linked rows are locked (except for pricing), the "only fill if
unset" guards stay useful — they make `Material.objects.create(...)` in
tests, fixtures, and migrations forgiving of partial input. The API
layer enforces the create-body shape; `_populate_from_pli` does the
actual filling.

The TemplateMaterial generation refactor (above) leans on the existing
"fill if unset" semantics: by passing only `quantity` and
`price_list_item` to `PlanMaterial.objects.create`, the rest of the
fields default and `_populate_from_pli` pulls fresh values from the
current PLI.

There's a minor philosophical choice: should `_populate_from_pli`
*overwrite* on every save when the PLI is linked, propagating PLI
catalog updates to existing Materials? My read: **no.** That would
retroactively change historical Materials when the catalog changes,
breaking the same audit-trail expectation that BaseLineItem honours.
Keep the current "fill once at create" semantics. The propagate-to-PLI
flow goes the *other* direction (Material → PLI) deliberately, and is
explicit user action.

## Open questions / decisions to discuss

The remaining open items are smaller now that the immutability rule is
settled.

### 1. Display: Material lists, `__str__` formatting

Two minor formatting decisions:

- **Material list rendering.** Today: `5` or `qty: 5`. After: `5 sheets`
  / `qty: 5 sheets`. When `units == 'none'`, render bare (`5` /
  `qty: 5`) — that's the convention `BaseLineItem`-rendered tables
  already use.
- **`Material.__str__` and `PlanMaterial.__str__`.** Currently:
  `f"{self.description} (qty: {self.quantity})"`. Update to
  `f"{self.description} (qty: {self.quantity} {self.units})"` —
  same `'none'` suppression.

These are uncontroversial; flagging only because they're easy to miss.

**Question:** any preference on the `'none'` suppression rule, or is
the BaseLineItem precedent fine?

### 2. Migration ordering vs. the materials-on-jobs refactor

The materials-on-jobs design (`2026-04-14`) is a substantial refactor
that adds `consumption_state`, `restocked_qty`, the `job` FK, the
`TemplateMaterial` model, etc. Status of that work matters here:

- **If materials-on-jobs has landed:** this `units` change is a
  straightforward additive migration on top, and the immutability rule
  is a tightening of that design's PATCH endpoints.
- **If it hasn't landed:** we have a choice — wait for it, or land
  `units` first as a smaller independent change. The two refactors
  don't conflict on the schema side; `units` is purely additive on
  `MaterialBase`. But the immutability rule *does* depend on the
  materials-on-jobs API surface (the create / PATCH endpoints described
  there) being in place. If materials-on-jobs is still pending, the
  immutability rule lands as part of that work, and this design becomes
  "add the field" plus a note in the materials-on-jobs design pointing
  at the tightened rule.

**Question:** what's the current state of the materials-on-jobs work,
and which order do you want?

## Follow-on items (surfaced during implementation / smoke testing)

- **TemplateMaterials should be attachable to TaskTemplates.**
  PlanMaterial already supports both `plan_task=None` (task-less,
  worksheet-level) and `plan_task=<PlanTask>` (task-attached). The
  parallel pattern doesn't exist on the template side: TemplateMaterial
  only links to WorkTemplate, so every PlanMaterial generated from a
  template is task-less. This loses information — a template might
  legitimately want to say "this material belongs to *that* task."
  Extension: add an optional `task_template` FK to TemplateMaterial
  (or a TemplateTaskMaterialAssociation row, paralleling
  TemplateTaskAssociation), then update `generate_materials_for_*`
  to attach the new PlanMaterial/Material to the matching generated
  PlanTask/Task. Out of scope for this branch.

- **Simplify the edit affordances on real Materials.**
  Surfaced during smoke testing on 2026-05-08: the row currently
  exposes several overlapping controls — the edit modal (which on
  PLI-linked Materials can only edit pricing), plus separate buttons
  for Restock, Draw more, and Consume. Quantity changes have to go
  through Restock/Draw-more (the modal had to disable quantity input
  in edit mode to stop silently dropping the user's typed value), and
  PLI-linked Materials have most of the modal disabled. A simpler
  single-surface design would make the model clearer to the user.
  Out of scope for this branch; flagged for a follow-on UX pass.

- **`accounting_category` is optional on freeform Material creation.**
  Discovered during the post-implementation smoke test on 2026-05-08:
  the Add-Material form accepts a freeform Material without an
  `accounting_category` selection. Likely a pre-existing gap (the
  field is `null=True, blank=True` on `MaterialBase`) but worth a
  separate investigation — should freeform Materials be required to
  carry a category for tax/accounting consistency? Out of scope for
  this branch; tracked here for follow-on work.

## Implementation order (once questions are resolved)

1. **Schema.** Add `units` to `MaterialBase`, generate the migration.
   *Don't run `migrate` — that's the user's job per `CLAUDE.md`.*
2. **`_populate_from_pli`.** Add the `units` copy line, mirroring
   `BaseLineItem._populate_from_pli`.
3. **Fixtures.** Set `units` on PLI-linked material rows to match the
   linked PLI; leave freeform rows defaulted or set explicitly. Zero
   out `unit_cost` / `sell_price` on PLI-linked TemplateMaterial rows
   (they'll be re-derived from PLI at generation time after step 7).
4. **API serializers.**
   - Add `units` to read/write field lists across MaterialSerializer,
     MaterialWriteSerializer, PlanMaterialSerializer,
     PlanMaterialWriteSerializer, and the TemplateMaterial serializer.
   - Tighten `update()`: PLI-linked Material/PlanMaterial accepts only
     `unit_cost`, `sell_price`, `propagate_to_pli`. PLI-linked
     TemplateMaterial accepts only `quantity`, `sort_order`. Freeform
     rows accept the labelling/pricing field set.
   - Tighten `create()`: freeform-vs-PLI body shape validation as
     described in the API table.
5. **Service layer.** `MaterialService.update(...)` (new or extended)
   handles the PLI propagation: when `propagate_to_pli=true` and prices
   have changed, update the linked PLI's `purchase_price` /
   `selling_price` in the same transaction. No permission check.
6. **Optional: `Material.clean()` defence-in-depth.** Track loaded
   values; raise if a PLI-linked instance has any locked
   `MaterialBase` field changed (i.e., any field except
   `unit_cost`/`sell_price`).
7. **TemplateMaterial generation refactor.** Rewrite
   `generate_materials_for_worksheet` and `generate_materials_for_job`
   in `apps/estimates/models.py` to branch on `tm.price_list_item_id`:
   PLI-linked path passes only `quantity` + `price_list_item`; freeform
   path passes the full field set. This resolves the stale-pricing bug
   for PLI-linked TemplateMaterials.
8. **Tests** (TDD: failing tests first). New cases:
   - `units` field defaults and PLI auto-fill.
   - PATCH rejects locked fields on PLI-linked rows.
   - PATCH allows pricing on PLI-linked Material/PlanMaterial.
   - `propagate_to_pli=true` updates the PLI in the same transaction.
   - `propagate_to_pli=true` from a non-financials user still works
     (carve-out test).
   - TemplateMaterial generation: PLI-linked row pulls current PLI
     pricing (not the stale template value).
   - PlanMaterial → Material carry-over preserves `units`.
   - PlanMaterial → EstimateLineItem carry-over preserves `units`.
9. **Carry-over paths.** Update `copy_from_worksheet`,
   `_create_material_line_item`, and `_atom_units` to copy/read
   `units` consistently.
10. **Svelte forms.**
    - Material create: freeform path exposes units dropdown +
      pricing; PLI-linked path takes only PLI + quantity.
    - Material edit: PLI-linked disables description/units/category
      and shows banner; pricing fields stay editable; on save with
      changed prices, modal *"Update PLI with the new values?"*.
    - PlanMaterial create / edit: same pattern as Material.
    - TemplateMaterial editor: PLI-linked hides all
      pricing/description/units fields, shows only quantity (and
      sort_order); freeform shows the full field set.
11. **Display surfaces.** Update `Material.__str__`,
    `PlanMaterial.__str__`, list rows, and any "qty: 5" renderings to
    include units (suppress the label when `'none'`, matching
    BaseLineItem precedent).
12. **Manual smoke test.**
    - Freeform Material create with `units=hours` — persists and
      displays.
    - PLI-linked Material create — units/description/pricing all
      auto-fill from the PLI.
    - PATCH a PLI-linked Material's description → 400 with the
      "immutable except for pricing" message.
    - PATCH a PLI-linked Material's `unit_cost` only, accept the
      *"Update PLI?"* prompt; verify the PLI's `purchase_price`
      updated and `selling_price` did not.
    - PATCH a PLI-linked Material's pricing as a worker-tier user
      (no `can_manage_financials`); verify the prompt appears and the
      PLI update succeeds (carve-out works).
    - Delete and re-add a PLI-linked Material as freeform with
      different units; earmark released, re-creation with no earmark
      succeeds.
    - Edit a TemplateMaterial that's PLI-linked: verify pricing
      fields aren't shown in the editor. Update the linked PLI's
      `purchase_price`. Generate a worksheet from the template;
      verify the new PlanMaterial reflects the *current* PLI price,
      not whatever was on the TemplateMaterial.
    - Generate an estimate from a worksheet containing a freeform
      PlanMaterial with `units=lbs`; verify the EstimateLineItem
      carries `units=lbs`.

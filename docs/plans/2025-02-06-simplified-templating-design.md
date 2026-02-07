# Simplified Templating System Design

## Problem Statement

The current templating system has accumulated complexity:
- **TaskMapping** is a separate model attached to TaskTemplate, but bundling behavior should be context-specific (same TaskTemplate may bundle differently in different WorkOrderTemplates)
- **step_type** and **product_type** fields serve overlapping purposes with LineItemType and template names
- **BundlingRule** uses category-based filtering (include_materials, include_labor) which is redundant when bundles are explicitly defined

## Design Goals

1. Bundling configuration lives at the WorkOrderTemplate level, not on TaskTemplate
2. TaskTemplate has a direct `line_item_type` (no indirection through TaskMapping)
3. Eliminate `step_type` and `product_type` - replaced by explicit bundle names and LineItemType
4. Simpler mental model: fewer objects, clearer ownership

---

## New Model Structure

### TaskTemplate
Defines a reusable task. Knows what type of line item it produces.

```python
class TaskTemplate(models.Model):
    template_name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    line_item_type = models.ForeignKey(LineItemType, on_delete=models.PROTECT)  # NEW - required
    base_price = models.DecimalField(...)
    is_active = models.BooleanField(default=True)
    # ... other existing fields
```

**Removed:** `task_mapping` FK (the mapping relationship goes away)

### WorkOrderTemplate
A recipe for creating work orders. Contains task templates via associations.

```python
class WorkOrderTemplate(models.Model):
    template_name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    base_price = models.DecimalField(...)
    is_active = models.BooleanField(default=True)
    # ... other existing fields
```

**Removed:** `product_type`, `template_type` (replaced by template name and structure)

### TemplateBundle (NEW)
A named grouping within a WorkOrderTemplate that becomes one line item on the estimate.

**Important:** A TemplateBundle does not directly contain TaskTemplates. Instead, TemplateTaskAssociations point *to* the bundle. The bundle's contents are defined by which associations reference it.

```python
class TemplateBundle(models.Model):
    work_order_template = models.ForeignKey(WorkOrderTemplate, on_delete=models.CASCADE, related_name='bundles')
    name = models.CharField(max_length=100)  # e.g., "Prep Work", "Finishing"
    description = models.TextField(blank=True)  # Optional description for the line item
    line_item_type = models.ForeignKey(LineItemType, on_delete=models.PROTECT)
    sort_order = models.IntegerField(default=0)

    class Meta:
        unique_together = ['work_order_template', 'name']
        ordering = ['sort_order', 'name']
```

**Relationship diagram:**

```
TemplateBundle "Prep Work"
       ↑
       │ (FKs pointing to it)
       │
┌──────┴──────┬─────────────┐
│             │             │
Assoc #1      Assoc #2      Assoc #3
(Sand)        (Clean)       (Prime)
   │             │             │
   ↓             ↓             ↓
TaskTemplate  TaskTemplate  TaskTemplate
```

To query "what's in this bundle": `TemplateTaskAssociation.objects.filter(bundle=prep_work_bundle)`

### TemplateTaskAssociation
The join table between WorkOrderTemplate and TaskTemplate. Every TaskTemplate in a WorkOrderTemplate gets one association row. The association also holds the mapping configuration - how this task (in this context) becomes a line item.

For bundled tasks, the association points to a TemplateBundle. Multiple associations can point to the same bundle, which is how tasks are grouped together.

```python
class TemplateTaskAssociation(models.Model):
    work_order_template = models.ForeignKey(WorkOrderTemplate, on_delete=models.CASCADE)
    task_template = models.ForeignKey(TaskTemplate, on_delete=models.CASCADE)

    # Quantity
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    sort_order = models.IntegerField(default=0)

    # Mapping configuration (NEW - moved from TaskMapping)
    MAPPING_CHOICES = [
        ('direct', 'Direct - becomes its own line item'),
        ('bundle', 'Bundle - part of a bundled line item'),
        ('exclude', 'Exclude - internal only, not on estimate'),
    ]
    mapping_strategy = models.CharField(max_length=20, choices=MAPPING_CHOICES, default='direct')
    bundle = models.ForeignKey(TemplateBundle, on_delete=models.SET_NULL, null=True, blank=True, related_name='associations')

    class Meta:
        unique_together = ['work_order_template', 'task_template']
        ordering = ['sort_order']

    def clean(self):
        if self.bundle and self.bundle.work_order_template != self.work_order_template:
            raise ValidationError("Bundle must belong to the same WorkOrderTemplate")
```

**Note on dual FK:** A bundled association has two paths to WorkOrderTemplate (directly, and through bundle). This redundancy is intentional - it keeps ordering flat across all associations regardless of bundling. The `clean()` validation ensures consistency.

**Key insight:**
- If `mapping_strategy='direct'` → line item type comes from `task_template.line_item_type`
- If `mapping_strategy='bundle'` → line item type comes from `bundle.line_item_type`
- If `mapping_strategy='exclude'` → no line item created

**Example: Same TaskTemplate, different behavior**

The "Sand Surface" TaskTemplate (line_item_type: Labor) is used in two WorkOrderTemplates:

```
WorkOrderTemplate: "Full Refinish"
├── TemplateBundle: "Prep Work" (line_item_type: Labor)
│   └── TemplateTaskAssociation: Sand Surface, mapping_strategy=bundle, bundle=Prep Work
│   └── TemplateTaskAssociation: Clean Surface, mapping_strategy=bundle, bundle=Prep Work
└── TemplateTaskAssociation: Apply Finish, mapping_strategy=direct

WorkOrderTemplate: "Quick Touch-Up"
└── TemplateTaskAssociation: Sand Surface, mapping_strategy=direct  ← same TaskTemplate, different config
└── TemplateTaskAssociation: Apply Finish, mapping_strategy=direct
```

In "Full Refinish", Sand Surface bundles with Clean Surface into one "Prep Work" line item.
In "Quick Touch-Up", Sand Surface becomes its own line item.

---

## Models to Remove/Simplify

### TaskMapping - DELETE
No longer needed. Its responsibilities are absorbed:
- `mapping_strategy` → TemplateTaskAssociation
- `step_type` → eliminated (LineItemType serves this purpose)
- `default_product_type` → eliminated (bundle names serve this purpose)
- `output_line_item_type` → TaskTemplate.line_item_type or TemplateBundle.line_item_type

### BundlingRule - DELETE
With explicit bundles, BundlingRule is no longer needed:
- `include_materials`, `include_labor`, `include_overhead` → eliminated (you explicitly choose what's in a bundle)
- `output_line_item_type` → now on TemplateBundle.line_item_type
- `pricing_method` → for now, always sum of components (user can edit resulting line item)
- `combine_instances` → **DECISION NEEDED** (see Open Questions)

### TaskInstanceMapping - DELETE
Work tracking is batch-level, not per-instance. Edge cases (e.g., one chair needs repair while others proceed) are handled via notes in the Job, not structured instance tracking. This model is no longer needed.

---

## Data Flow

### Creating a WorkOrderTemplate (UX Flow)

1. User creates WorkOrderTemplate with name and description
2. User creates bundles: "Prep Work" (Labor), "Finishing" (Labor), "Materials" (Materials)
3. User adds TaskTemplates to the template:
   - Assign to a bundle → mapping_strategy='bundle', bundle=selected bundle
   - Or mark as direct → mapping_strategy='direct', bundle=null
   - Or mark as internal → mapping_strategy='exclude', bundle=null
4. UI can suggest LineItemType for bundles based on component tasks (if all match)

### Generating Tasks from Template

When a WorkOrder is created from a WorkOrderTemplate:
1. For each TemplateTaskAssociation, create Task(s) based on quantity
2. Task stores reference to its association's mapping config (or copy the values)

### Generating Estimate Line Items

When generating an estimate from tasks:
1. **Direct tasks:** One line item per task, type from TaskTemplate.line_item_type
2. **Bundled tasks:** Group by TemplateBundle, one line item per bundle, type from TemplateBundle.line_item_type
3. **Excluded tasks:** Skip

---

## Migration Path

### Phase 1: Add new structures
- Add `line_item_type` to TaskTemplate (nullable initially)
- Create TemplateBundle model
- Add `mapping_strategy` and `bundle` to TemplateTaskAssociation

### Phase 2: Migrate data
- Copy TaskMapping.output_line_item_type to TaskTemplate.line_item_type (or assign defaults)
- Create TemplateBundles for existing bundled configurations
- Update TemplateTaskAssociations with mapping data

### Phase 3: Update services
- EstimateGenerationService uses new structure
- Remove references to TaskMapping, step_type, product_type

### Phase 4: Cleanup
- Remove TaskMapping model
- Remove BundlingRule model
- Remove TaskInstanceMapping model
- Remove step_type, product_type fields

---

## Open Questions

### 1. Combining instances within a quantity - DEFERRED

If a user orders 4 chairs from a WorkOrderTemplate that has a "Prep Work" bundle:

- **Combined:** One "Prep Work" line item for all 4 chairs (price = 4x component sum)
- **Separate:** Four "Prep Work" line items, one per chair

This is fundamentally a **UX question**: do users think in per-item quantities or batch quantities? Some people think one way, some the other.

**Deferred to UI design phase.** The data model should be able to support either approach - the question is how we present and collect the information.

### 2. TaskInstanceMapping - DECIDED: DELETE

Work tracking is batch-level. A worker can sand 3 of 4 chairs, log a Blep, and finish the 4th the next day - but the Task is just "sanding" for the batch. Edge cases (broken chair falls behind) are handled via notes in the Job. No per-instance tracking needed.

### 3. Descriptions - DECIDED: Keep simple

TemplateBundle.name becomes the line item description. User can edit the resulting line item if they want more detail. Iterate after user testing.

---

## Benefits

- **Clearer mental model:** TaskTemplate knows its type, bundles are explicit objects
- **Context-specific bundling:** Same TaskTemplate can behave differently in different WorkOrderTemplates
- **Fewer models:** TaskMapping, BundlingRule, TaskInstanceMapping eliminated
- **No string interpolation:** No fragile `{placeholder}` templates
- **Type lives in one place:** Direct → TaskTemplate, Bundle → TemplateBundle
- **Flat ordering:** All task associations ordered at one level regardless of bundling

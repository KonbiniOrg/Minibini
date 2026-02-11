# Instance-Level Bundling Design

## Status: Brainstorming (not yet implemented)

## Problem

The template system now has TemplateBundle and mapping config on TemplateTaskAssociation. But when tasks are instantiated into an EstWorksheet or WorkOrder, the bundling information is lost. The instance-level objects (Task) have no bundling of their own.

We need instance-level bundling that:
- Carries over from templates when generated from one
- Can diverge from the template on a per-job basis
- Works for manually-created worksheets/work orders that have no template
- Drives estimate line item generation

## Current State

### What exists (template level - implemented)

```
WorkOrderTemplate
  ├── TemplateBundle (name, line_item_type, sort_order)
  │     ↑ pointed to by associations
  └── TemplateTaskAssociation (mapping_strategy, bundle FK, sort_order, est_qty)
        └── TaskTemplate
```

- `mapping_strategy`: direct / bundle / exclude
- Interleaved container-level ordering (bundles and unbundled tasks share sort_order space)
- Within-bundle ordering (tasks have sort_order relative to siblings)
- Auto-dissolution of single-task bundles

### What exists (instance level - current)

```
EstWorksheet / WorkOrder
  └── Task (name, units, rate, est_qty, line_number, template FK)
```

- Task has `line_number` (auto-generated per container)
- Task has nullable FK to TaskTemplate (for traceability)
- No mapping_strategy, no bundle, no grouping
- EstimateGenerationService currently reaches back to the *template* to find mapping config

### The problem with reaching back to templates

`EstimateGenerationService._get_mapping_strategy()` looks up the Task's template FK, then finds the TemplateTaskAssociation in the worksheet's template. This breaks when:
- The worksheet has no template (manually created)
- The user wants to change bundling for this specific job
- Tasks were added manually after template generation
- The template has been edited since the worksheet was created

## Proposed Design

### New Model: TaskBundle

Parallel to TemplateBundle, but lives on the instance container.

```python
class TaskBundle(models.Model):
    # One of these will be set (like Task's dual FK pattern)
    est_worksheet = models.ForeignKey(EstWorksheet, null=True, blank=True,
                                      on_delete=models.CASCADE, related_name='bundles')
    work_order = models.ForeignKey(WorkOrder, null=True, blank=True,
                                   on_delete=models.CASCADE, related_name='bundles')

    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    line_item_type = models.ForeignKey(LineItemType, on_delete=models.PROTECT)
    sort_order = models.IntegerField(default=0)

    # Traceability (optional)
    source_template_bundle = models.ForeignKey(TemplateBundle, null=True, blank=True,
                                                on_delete=models.SET_NULL)

    def get_container(self):
        return self.est_worksheet or self.work_order

    def clean(self):
        # Must belong to exactly one container
        if bool(self.est_worksheet) == bool(self.work_order):
            raise ValidationError("TaskBundle must belong to exactly one container")
```

### Task Model Changes

Add mapping fields directly to Task (parallel to TemplateTaskAssociation):

```python
class Task(models.Model):
    # ... existing fields ...

    # Mapping config (NEW)
    MAPPING_CHOICES = [
        ('direct', 'Direct'),
        ('bundle', 'Bundle'),
        ('exclude', 'Exclude'),
    ]
    mapping_strategy = models.CharField(max_length=20, choices=MAPPING_CHOICES, default='direct')
    bundle = models.ForeignKey(TaskBundle, null=True, blank=True,
                               on_delete=models.SET_NULL, related_name='tasks')
```

### Ordering Model

Same two-level ordering as templates:
- **Container level**: TaskBundles and unbundled Tasks share `sort_order` / `line_number` space
- **Within-bundle**: Tasks have their own `line_number` relative to bundle siblings

Open question: Do we use `line_number` for both levels, or add a separate `sort_order` field? Currently `line_number` is auto-generated sequentially. We may need to revisit auto-generation to support interleaved ordering.

### Relationship Diagram

```
EstWorksheet (or WorkOrder)
  ├── TaskBundle "Prep Work" (line_item_type=Labor, sort_order=1)
  │     ↑
  │     ├── Task: Sand Floor (mapping_strategy=bundle, bundle=Prep Work)
  │     └── Task: Clean Floor (mapping_strategy=bundle, bundle=Prep Work)
  │
  ├── Task: Apply Finish (mapping_strategy=direct, sort_order=2)
  │
  └── Task: Quality Check (mapping_strategy=exclude, sort_order=3)
```

## Data Flow

### Template to Instance (generate tasks from template)

When creating an EstWorksheet or WorkOrder from a WorkOrderTemplate:

1. For each TemplateBundle, create a corresponding TaskBundle:
   - Copy name, description, line_item_type
   - Set source_template_bundle FK for traceability
   - Assign container-level sort_order

2. For each TemplateTaskAssociation:
   - Create Task with name/units/rate/est_qty from TaskTemplate
   - Copy mapping_strategy from association
   - If bundled: set bundle FK to the corresponding TaskBundle
   - Assign appropriate line_number/sort_order

3. Result: Instance has its own complete bundling config, independent of template

### Instance to Estimate (generate line items)

EstimateGenerationService changes to read from instance-level data:

1. **Direct tasks**: One line item per task, type from task.template.line_item_type
2. **Bundled tasks**: Group by TaskBundle, one line item per bundle, type from TaskBundle.line_item_type
3. **Excluded tasks**: Skip

No more reaching back to templates. Everything needed is on the instance.

### Manual editing (post-generation)

Users can:
- Create bundles on worksheets that have no template
- Add/remove tasks from bundles
- Change mapping_strategy on individual tasks
- Reorder tasks and bundles
- All changes are local to this worksheet/work order

## AbstractWorkContainer Consideration

EstWorksheet and WorkOrder are structurally very similar:
- Both contain Tasks
- Both would contain TaskBundles
- Both have a job FK
- Both have an optional template FK

They could share an abstract base:

```python
class AbstractWorkContainer(models.Model):
    job = models.ForeignKey(Job, on_delete=models.CASCADE)
    template = models.ForeignKey(WorkOrderTemplate, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        abstract = True
```

This already exists partially. The TaskBundle dual-FK pattern mirrors how Task already has dual FKs to both containers. An alternative would be GenericForeignKey, but the dual-FK pattern is already established in this codebase and is simpler to query.

## Migration Considerations

- Task model gets two new nullable fields (mapping_strategy with default='direct', bundle FK)
- TaskBundle is a new model
- Existing tasks default to mapping_strategy='direct' (backward compatible)
- EstimateGenerationService switches from template-lookup to instance-lookup
- Template-to-instance generation logic updated to copy bundling config

## What This Enables

- Worksheets/work orders are self-contained (no template dependency for estimate generation)
- Users can customize bundling per job
- Manually created worksheets get full bundling support
- Template changes don't retroactively affect existing worksheets
- Clear separation: templates are recipes, instances are the actual work

## Open Questions

1. **line_number vs sort_order for instances**: Templates use `sort_order` (internal). Instances currently use `line_number` (user-visible, auto-generated). Do we add a separate `sort_order` to Task for container-level ordering, or repurpose `line_number`?

--
The term "line number" makes the most sense for line items, less so for Tasks. If it's not difficult to use sort_order for Tasks, that seems better, but if line_number is the property of a base object let's just note that and come back later.  My current thinking is that Tasks and TaskTemplates get sort orders and Line Item Types get line numbers, but I'm open to changing my mind.
--

2. **WorkOrder bundling UI**: WorkOrders are created from estimates. The bundling info would need to carry through: Template → Worksheet → Estimate → WorkOrder. Or should WorkOrder bundling be independent?

--
I anticipate WorkOrders to be generated directly from Worksheets where a Worksheet exists, in which case bundling would be copied and be editable in the WorkOrder independently.  For Jobs without Worksheets, a WorkOrder can be started from an Estimate, but will often need considerable editing by a user.  Bundling will need to be available there - I expect Invoices to be generated from WorkOrders as Estimates are generated from Worksheets.  (But not yet.)
--

3. **Estimate revision**: When a worksheet is revised (new version), the bundling config should copy over with the tasks. The existing `create_new_version()` method copies tasks but would need to also copy TaskBundles.

--
Yes.
--

4. **Bundle editing UI for worksheets**: Similar to template detail page, but on the worksheet detail page. Checkboxes, bundle creation form, unbundle/remove buttons, reorder arrows. Can likely reuse patterns from the template UI.

--
Yes let's reuse that code as much as possible.
--

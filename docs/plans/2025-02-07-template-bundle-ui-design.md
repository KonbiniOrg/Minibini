# Template Bundle UI Design

## Overview

Add UI for creating TemplateBundles within WorkOrderTemplates. Users can select multiple TaskTemplates and bundle them into a single line item for estimate generation.

## User Workflow

1. User views WorkOrderTemplate detail page
2. TaskTemplates are listed with checkboxes
3. User selects multiple tasks they want bundled
4. User fills in bundle details (name, description, line item type)
5. User clicks "Bundle Selected Tasks"
6. Selected tasks now appear visually grouped, showing the bundle name

## UI Design

### WorkOrderTemplate Detail Page

**Task Template Table:**

| ☐ | Task Name | Description | Units | Rate | Est Qty | Mapping |
|---|-----------|-------------|-------|------|---------|---------|

- Checkbox column on left for multi-select
- New "Mapping" column showing: bundle name, "Direct", or "Exclude (internal)"
- Bundled tasks visually grouped with light background and left border
- Excluded tasks appear dimmed/greyed

**Visual Grouping Example:**

```
[ ] Sand Floor          hours   $50    2.00   Direct
[ ] Stain Floor         hours   $75    1.00   Direct

┌─ Bundle: "Cabinet Install" (Material) ──────────┐
│ [ ] Install Uppers    hours   $60    3.00      │
│ [ ] Install Lowers    hours   $60    4.00      │
│ [ ] Install Hardware  each    $5     24.00     │
└─────────────────────────────────────────────────┘

[ ] Quality Check       hours   $0     1.00   Exclude (internal)  ← dimmed
```

**Bundle Creation Form (always visible below list):**

```
Create Bundle from Selected Tasks:

Bundle Name: [____________]
Description: [________________________] (optional)
Line Item Type: [▼ Select type ]

[Bundle Selected Tasks]
```

- Button disabled when no checkboxes selected
- Creates TemplateBundle and updates selected associations

**Display Ordering:**
- Bundled tasks grouped together by bundle
- Direct tasks follow
- Excluded tasks last
- Within groups, maintain sort_order

## Data Model

Already implemented:

- **TemplateBundle** - name, description, line_item_type, sort_order, FK to WorkOrderTemplate
- **TemplateTaskAssociation** - mapping_strategy (direct/bundle/exclude), optional FK to TemplateBundle

No model changes required.

## View Changes

**work_order_template_detail view:**

1. Add `bundles` to template context (template.bundles.all())
2. Handle new POST action `bundle_tasks`:
   - Validate: at least 2 tasks selected, all required fields provided
   - Create TemplateBundle from form fields
   - Update selected TemplateTaskAssociations: set mapping_strategy='bundle', set bundle FK
   - Redirect back to detail page with success message
3. Query associations with select_related('bundle') for efficient display
4. Group associations by bundle for template rendering

## Implementation Scope

**In scope:**

1. Update `work_order_template_detail.html`:
   - Checkbox column on task template rows
   - "Mapping" column showing bundle name, "Direct", or "Exclude (internal)"
   - Visual grouping (background/border) for bundled tasks
   - Bundle creation form (name, description, line_item_type)
   - "Bundle Selected Tasks" button

2. Update `work_order_template_detail` view:
   - Handle `bundle_tasks` POST action
   - Group associations by bundle for template context

3. Update test fixtures:
   - Add TemplateBundle records to relevant fixtures
   - Update TemplateTaskAssociation records with mapping_strategy and bundle references
   - Include at least one example of bundled tasks

**Implemented (2025-02-09):**

- Unbundling tasks (Remove button on bundled tasks unbundles; click again to remove from template)
- Adding more tasks to existing bundle (use same bundle name)
- Bundles auto-dissolve when reduced to 1 or 0 tasks
- Interleaved ordering with up/down arrows (container-level and within-bundle)

**Known UX issue:**

- Combining tasks from an existing bundle with non-bundled tasks has minor confusing UI behaviors. Needs a closer look later.

**Deferred:**

- Changing mapping strategy after initial assignment
- EstWorksheet bundling (needs separate model and UI design)
- Setting "Exclude" mapping strategy via UI

## EstWorksheet Bundling (Placeholder)

The EstWorksheet needs its own bundling model separate from TemplateBundle, because:
- Users must be able to edit bundling for specific jobs
- Worksheet bundling can diverge from what the template specified
- Tasks can be added/removed from bundles on a per-job basis

This requires a separate design iteration with its own models (e.g., WorksheetBundle) and UI.

# API Gaps

Tracked issues discovered while building the seed data script and frontend.

## Open

### 1. Work Order Template — no endpoint for task associations
**Found:** seed_data.sh template associations
**Workaround:** POST to HTML form view (`/estimates/templates/<id>/`) with `associate_task`, `task_template_id`, `est_qty` form fields.
**Fix:** Add an `associations` action to `WorkOrderTemplateViewSet` (POST to add, DELETE to remove).

### 2. Worksheet from template doesn't populate tasks
**Found:** seed_data.sh creating worksheet with `template` param
`WorksheetService.create_worksheet(job_pk, template=...)` stores the template FK but does not copy the template's task associations into the worksheet as tasks.
**Workaround:** Create worksheet without template, then add tasks manually via the tasks endpoint.
**Fix:** `create_worksheet` should iterate `TemplateTaskAssociation` entries and call `add_task_from_template` for each.

### 3. Business creation required `default_contact_id` field
**Found:** seed_data.sh business creation
`BusinessSerializer` had `default_contact` as read-only (nested serializer) with no writable counterpart. `perform_create` tried to pop `default_contact` from validated data but it was never there.
**Fix applied:** Added `default_contact_id` write-only `PrimaryKeyRelatedField` to `BusinessSerializer`, updated `perform_create` to use `create_business_for_contact`.

### 4. Payment Terms — read-only API, stub model
**Found:** seed_data.sh
`PaymentTermsViewSet` is `ReadOnlyModelViewSet`. The `PaymentTerms` model only has a PK field (`term_id`) with no other fields (name, days, etc.).
**Workaround:** Omit payment terms from seed data.
**Fix:** Add fields to `PaymentTerms` model, switch viewset to full `ModelViewSet`.

### 5. No task-level completion or work order auto-complete
**Found:** seed_data.sh completing a work order
Work orders can be marked complete directly without completing individual tasks. There's no task status or completion tracking, and no auto-complete when all tasks are done.
**Workaround:** Call `/api/work-orders/<id>/complete/` directly.
**Note:** User filed a separate bug for this.

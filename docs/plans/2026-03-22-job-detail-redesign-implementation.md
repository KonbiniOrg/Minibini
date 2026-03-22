# Job Detail View Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the Svelte SPA Job detail page with color-coded accordion document sections, a history timeline with inline email previews, and a reusable Accordion component.

**Architecture:** Backend prerequisites first (API filters, serializer fields), then build the reusable Accordion component, then rebuild the Job detail page section by section. Each task produces a working, testable increment.

**Tech Stack:** Django REST Framework (backend), Svelte 5 with runes (frontend), CSS grid-template-rows animation, session-based auth.

**Spec:** `docs/plans/2026-03-22-job-detail-redesign.md`

---

## File Structure

### Backend (API changes)
- Modify: `apps/api/purchasing/views.py` — add `?job=` filter to PurchaseOrderViewSet
- Modify: `apps/api/purchasing/serializers.py` — add `business_name` to PurchaseOrderSerializer
- Modify: `apps/api/worksheets/serializers.py` — add `assignee_name` to TaskSerializer, add `version` to EstWorksheetSerializer
- Modify: `apps/api/email/views.py` — add `?job=` filter to email_list
- Modify: `apps/api/work_orders/serializers.py` — add `template_name` to WorkOrderSerializer

### Frontend (new files)
- Create: `frontend/src/components/Accordion.svelte` — reusable accordion component
- Create: `frontend/src/css/accordion.css` — accordion styles (shared, importable)

### Frontend (modified files)
- Modify: `frontend/src/components/jobs/JobDetail.svelte` — complete rewrite
- Modify: `frontend/src/routes/jobs/JobDetailPage.svelte` — add PO + email fetching
- Modify: `frontend/src/components/HistoryPanel.svelte` — add email entries with expandable previews

### Tests
- Modify: `tests/test_api_purchasing.py` — add PO `?job=` filter test, `business_name` serializer test
- Modify: `tests/test_api_work_orders.py` — add `assignee_name` and `template_name` tests
- Modify: `tests/test_api_email.py` — add `?job=` filter test

---

## Task 1: Add `?job=` filter to PurchaseOrderViewSet

**Files:**
- Modify: `apps/api/purchasing/views.py:28-36`
- Test: `tests/test_api_purchasing.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_api_purchasing.py`, add to `PurchaseOrderAPITest`:

```python
def test_filter_purchase_orders_by_job(self):
    """POs can be filtered by job via line item linkage."""
    from apps.contacts.models import Business
    from apps.jobs.models import Job
    from apps.purchasing.models import PurchaseOrderLineItem
    business = Business.objects.first()
    job = Job.objects.first()

    # Create a PO with a line item linked to the job
    po = PurchaseOrder.objects.create(
        business=business,
        po_number='PO-TEST-FILTER',
    )
    PurchaseOrderLineItem.objects.create(
        purchase_order=po,
        job=job,
        description='Test item',
        qty=1,
        price=100,
    )
    # Create another PO with no job linkage
    po2 = PurchaseOrder.objects.create(
        business=business,
        po_number='PO-TEST-NOJOB',
    )
    PurchaseOrderLineItem.objects.create(
        purchase_order=po2,
        description='Unlinked item',
        qty=1,
        price=50,
    )

    response = self.client.get(f'/api/purchase-orders/?job={job.job_id}')
    self.assertEqual(response.status_code, 200)
    po_ids = [r['po_id'] for r in response.data['results']]
    self.assertIn(po.po_id, po_ids)
    self.assertNotIn(po2.po_id, po_ids)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_api_purchasing.PurchaseOrderAPITest.test_filter_purchase_orders_by_job -v 2`
Expected: FAIL — filter not implemented, both POs returned.

- [ ] **Step 3: Implement the filter**

In `apps/api/purchasing/views.py`, add to `get_queryset()` after the existing `contact` filter:

```python
job = self.request.query_params.get('job')
if job:
    qs = qs.filter(purchaseorderlineitem__job=job).distinct()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test tests.test_api_purchasing.PurchaseOrderAPITest.test_filter_purchase_orders_by_job -v 2`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/api/purchasing/views.py tests/test_api.py
git commit -m "feat(api): add ?job= filter to PurchaseOrderViewSet"
```

---

## Task 2: Add `business_name` to PurchaseOrderSerializer

**Files:**
- Modify: `apps/api/purchasing/serializers.py:28-40`
- Test: `tests/test_api_purchasing.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_api_purchasing.py`, add to `PurchaseOrderAPITest`:

```python
def test_purchase_order_serializer_includes_business_name(self):
    """PO API response includes business_name field."""
    from apps.contacts.models import Business
    business = Business.objects.first()
    po = PurchaseOrder.objects.create(
        business=business,
        po_number='PO-TEST-BIZNAME',
    )
    response = self.client.get(f'/api/purchase-orders/{po.po_id}/')
    self.assertEqual(response.status_code, 200)
    self.assertIn('business_name', response.data)
    self.assertEqual(response.data['business_name'], business.business_name)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_api_purchasing.PurchaseOrderAPITest.test_purchase_order_serializer_includes_business_name -v 2`
Expected: FAIL — `business_name` not in response.

- [ ] **Step 3: Add business_name to serializer**

In `apps/api/purchasing/serializers.py`, modify `PurchaseOrderSerializer`:

```python
class PurchaseOrderSerializer(serializers.ModelSerializer):
    line_items = POLineItemSerializer(
        source='purchaseorderlineitem_set', many=True, read_only=True
    )
    business_name = serializers.CharField(source='business.business_name', read_only=True)

    class Meta:
        model = PurchaseOrder
        fields = [
            'po_id', 'business', 'business_name', 'contact', 'po_number', 'status',
            'created_date', 'requested_date', 'issued_date',
            'received_date', 'cancel_date', 'line_items',
        ]
        read_only_fields = ['po_id', 'po_number', 'created_date']
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test tests.test_api -k test_purchase_order_serializer_includes_business_name -v 2`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/api/purchasing/serializers.py tests/test_api.py
git commit -m "feat(api): add business_name to PurchaseOrderSerializer"
```

---

## Task 3: Add `assignee_name` to TaskSerializer, `version` to EstWorksheetSerializer, `template_name` to WorkOrderSerializer

**Files:**
- Modify: `apps/api/worksheets/serializers.py:6-14` (TaskSerializer) and `:29-39` (EstWorksheetSerializer)
- Modify: `apps/api/work_orders/serializers.py:13-23` (WorkOrderSerializer)
- Test: `tests/test_api_work_orders.py`

- [ ] **Step 1: Write the failing test for assignee_name**

In `tests/test_api_work_orders.py`, add:

```python
def test_task_serializer_includes_assignee_name(self):
    """Task API response includes assignee_name when assignee is set."""
    from apps.jobs.models import WorkOrder, Task, Job
    job = Job.objects.first()
    wo = WorkOrder.objects.create(job=job, status='draft')
    task = Task.objects.create(
        work_order=wo,
        name='Test task',
        assignee=self.user,
    )
    response = self.client.get(f'/api/work-orders/{wo.work_order_id}/')
    self.assertEqual(response.status_code, 200)
    task_data = response.data['tasks'][0]
    self.assertIn('assignee_name', task_data)
    self.assertTrue(len(task_data['assignee_name']) > 0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_api_work_orders -k test_task_serializer_includes_assignee_name -v 2`
Expected: FAIL — `assignee_name` not in response.

- [ ] **Step 3: Add assignee_name to serializer**

In `apps/api/worksheets/serializers.py`, modify `TaskSerializer`:

```python
class TaskSerializer(serializers.ModelSerializer):
    assignee_name = serializers.SerializerMethodField()

    class Meta:
        model = Task
        fields = [
            'task_id', 'name', 'description', 'sort_order', 'status',
            'units', 'rate', 'est_qty', 'line_item_type',
            'mapping_strategy', 'bundle', 'parent_task', 'assignee',
            'assignee_name',
        ]
        read_only_fields = ['task_id', 'sort_order', 'status']

    def get_assignee_name(self, obj):
        if obj.assignee:
            name = obj.assignee.get_full_name()
            return name if name else obj.assignee.username
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test tests.test_api_work_orders -k test_task_serializer_includes_assignee_name -v 2`
Expected: PASS

- [ ] **Step 5: Add `version` to EstWorksheetSerializer**

In `apps/api/worksheets/serializers.py`, add `'version'` to `EstWorksheetSerializer.Meta.fields`:

```python
fields = [
    'est_worksheet_id', 'job', 'template', 'estimate',
    'status', 'version', 'parent', 'created_date', 'tasks', 'bundles',
]
```

- [ ] **Step 6: Add `template_name` to WorkOrderSerializer**

In `apps/api/work_orders/serializers.py`, add a read-only field for the template name. The `template` field is a FK to `WorkOrderTemplate`. Add:

```python
class WorkOrderSerializer(serializers.ModelSerializer):
    tasks = TaskSerializer(source='task_set', many=True, read_only=True)
    bundles = TaskBundleSerializer(source='taskbundle_set', many=True, read_only=True)
    template_name = serializers.CharField(source='template.name', read_only=True, default=None)

    class Meta:
        model = WorkOrder
        fields = [
            'work_order_id', 'job', 'template', 'template_name', 'status',
            'tasks', 'bundles',
        ]
        read_only_fields = ['work_order_id']
```

- [ ] **Step 7: Commit**

```bash
git add apps/api/worksheets/serializers.py apps/api/work_orders/serializers.py tests/test_api_work_orders.py
git commit -m "feat(api): add assignee_name, version, template_name to serializers"
```

---

## Task 4: Add `?job=` filter to email_list endpoint

**Files:**
- Modify: `apps/api/email/views.py:13-19`
- Test: `tests/test_api_email.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_api_email.py`, add:

```python
def test_filter_emails_by_job(self):
    """Emails can be filtered by job."""
    from apps.core.models import EmailRecord
    from apps.jobs.models import Job
    job = Job.objects.first()
    # Create an email linked to the job
    email1 = EmailRecord.objects.create(message_id='test-filter-1@example.com', job=job)
    # Create an email not linked to any job
    email2 = EmailRecord.objects.create(message_id='test-filter-2@example.com')

    response = self.client.get(f'/api/emails/?job={job.job_id}')
    self.assertEqual(response.status_code, 200)
    email_ids = [r['email_record_id'] for r in response.data['results']]
    self.assertIn(email1.email_record_id, email_ids)
    self.assertNotIn(email2.email_record_id, email_ids)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_api_email -k test_filter_emails_by_job -v 2`
Expected: FAIL — no filter, both emails returned.

- [ ] **Step 3: Implement the filter**

In `apps/api/email/views.py`, update `email_list`:

```python
def email_list(request):
    emails = EmailRecord.objects.select_related('temp_data').order_by('-created_at')
    job = request.query_params.get('job')
    if job:
        emails = emails.filter(job=job)
    from apps.api.pagination import StandardPagination
    paginator = StandardPagination()
    page = paginator.paginate_queryset(emails, request)
    serializer = EmailRecordSerializer(page, many=True)
    return paginator.get_paginated_response(serializer.data)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test tests.test_api_email -k test_filter_emails_by_job -v 2`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/api/email/views.py tests/test_api_email.py
git commit -m "feat(api): add ?job= filter to email list endpoint"
```

---

## Task 5: Create reusable Accordion component

**Files:**
- Create: `frontend/src/css/accordion.css`
- Create: `frontend/src/components/Accordion.svelte`

- [ ] **Step 1: Create accordion CSS**

Create `frontend/src/css/accordion.css` with the shared accordion styles. This file is imported by `Accordion.svelte` and also by pages that need section-specific color overrides.

```css
/* Accordion base styles */
.accordion-bar {
  margin-bottom: 4px;
  border-radius: 6px;
  overflow: hidden;
}

.accordion-header {
  color: #fff;
  padding: 10px 16px;
  cursor: pointer;
  display: flex;
  justify-content: space-between;
  align-items: center;
  user-select: none;
}

.accordion-header .accordion-title {
  font-size: 15px;
  font-weight: 600;
}

.accordion-header .accordion-meta {
  opacity: 0.8;
  margin-left: 10px;
  font-size: 13px;
}

.accordion-header .accordion-meta-dim {
  opacity: 0.6;
  margin-left: 8px;
  font-size: 12px;
}

.accordion-icon {
  font-size: 18px;
  transition: transform 0.15s ease;
}

.accordion-icon.open {
  transform: rotate(90deg);
}

.accordion-content {
  display: grid;
  grid-template-rows: 0fr;
  transition: grid-template-rows 0.2s ease;
}

.accordion-content.open {
  grid-template-rows: 1fr;
}

.accordion-inner {
  overflow: hidden;
}
```

- [ ] **Step 2: Create Accordion.svelte component**

Create `frontend/src/components/Accordion.svelte`:

```svelte
<script>
  import '../css/accordion.css';

  let {
    title,
    meta = '',
    metaDim = '',
    open = false,
    headerBg = '#475569',
    borderColor = '#cbd5e1',
    children,
  } = $props();

  let isOpen = $state(open);

  function toggle() {
    isOpen = !isOpen;
  }
</script>

<div class="accordion-bar" style="border: 1px solid {borderColor};">
  <div
    class="accordion-header"
    style="background-color: {headerBg};"
    onclick={toggle}
    onkeydown={(e) => e.key === 'Enter' && toggle()}
    role="button"
    tabindex="0"
  >
    <div>
      <span class="accordion-title">{title}</span>
      {#if meta}
        <span class="accordion-meta">{meta}</span>
      {/if}
      {#if metaDim}
        <span class="accordion-meta-dim">{metaDim}</span>
      {/if}
    </div>
    <span class="accordion-icon" class:open={isOpen}>&#9654;</span>
  </div>
  <div class="accordion-content" class:open={isOpen}>
    <div class="accordion-inner" style="border-top: 1px solid {borderColor};">
      {@render children()}
    </div>
  </div>
</div>
```

- [ ] **Step 3: Verify it renders**

Start the dev server (`cd frontend && npm run dev`), then temporarily import and use `<Accordion title="Test" open={true}>Content</Accordion>` in any existing page to verify it opens/closes with animation. Remove the test usage afterward.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/css/accordion.css frontend/src/components/Accordion.svelte
git commit -m "feat: add reusable Accordion component with CSS animation"
```

---

## Task 6: Update JobDetailPage to fetch POs and emails

**Files:**
- Modify: `frontend/src/routes/jobs/JobDetailPage.svelte`

- [ ] **Step 1: Add purchaseOrders and emails state variables**

In `JobDetailPage.svelte`, add after the existing state declarations (around line 16):

```javascript
let purchaseOrders = $state(null);
let emails = $state(null);
```

- [ ] **Step 2: Add API calls to loadJob()**

In the `Promise.all` block inside `loadJob()` (around line 27), add two more parallel calls:

```javascript
const [contactData, estData, wsData, woData, invData, histData, poData, emailData] = await Promise.all([
  api.get(`/api/contacts/${data.contact}/`),
  api.get(`/api/estimates/?job=${params.id}`),
  api.get(`/api/est-worksheets/?job=${params.id}`),
  api.get(`/api/work-orders/?job=${params.id}`),
  api.get(`/api/invoices/?job=${params.id}`),
  api.get(`/api/jobs/${params.id}/history/`),
  api.get(`/api/purchase-orders/?job=${params.id}`),
  api.get(`/api/emails/?job=${params.id}`),
]);
```

Assign the new results:
```javascript
purchaseOrders = poData;
emails = emailData;
```

- [ ] **Step 3: Pass new props to JobDetail**

Update the `<JobDetail>` usage to include the new props:

```svelte
<JobDetail
  {job}
  {contact}
  {estimates}
  {worksheets}
  {workOrders}
  {invoices}
  {purchaseOrders}
  {emails}
  {history}
  onAddNote={handleAddNote}
/>
```

- [ ] **Step 4: Verify page still loads**

Start the dev server, navigate to a job detail page. Verify it loads without errors (the new props won't be used in JobDetail yet, but the page should not break). Check browser console for any fetch errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/routes/jobs/JobDetailPage.svelte
git commit -m "feat: fetch POs and emails in JobDetailPage"
```

---

## Task 7: Update HistoryPanel with email entries

**Files:**
- Modify: `frontend/src/components/HistoryPanel.svelte`

- [ ] **Step 1: Add emails prop and merge into timeline**

Add `emails` prop and merge email entries into the history timeline, sorted by date:

```svelte
<script>
  import { viewMode } from '../stores/viewMode.js';

  let {
    history = null,
    emails = null,
    onAddNote = null,
  } = $props();

  let noteText = $state('');
  let expandedEmails = $state({});

  function toggleEmail(id) {
    expandedEmails = { ...expandedEmails, [id]: !expandedEmails[id] };
  }

  // Merge history entries and email entries into a single timeline
  let timeline = $derived.by(() => {
    const entries = [];

    // Add history entries
    const histResults = history?.results || [];
    for (const h of histResults) {
      entries.push({ type: 'history', data: h, date: new Date(h.timestamp) });
    }

    // Add email entries (from EmailRecord with nested temp_email)
    const emailResults = emails?.results || [];
    for (const e of emailResults) {
      const tempEmail = e.temp_email;
      const date = tempEmail?.date_sent ? new Date(tempEmail.date_sent) : new Date(e.created_at);
      entries.push({ type: 'email', data: e, date });
    }

    // Sort newest first
    entries.sort((a, b) => b.date - a.date);

    // Apply view mode filtering (lite: notes + emails only)
    if ($viewMode === 'lite') {
      return entries.filter(e => e.type === 'email' || (e.type === 'history' && e.data.text));
    }
    return entries;
  });

  async function submitNote() {
    if (!noteText.trim() || !onAddNote) return;
    await onAddNote(noteText.trim());
    noteText = '';
  }
</script>
```

- [ ] **Step 2: Update the template to render merged timeline**

Replace the existing history rendering with the merged timeline. History entries render as before. Email entries show with the `@` icon, clickable subject, and expandable preview:

```svelte
<h3>History</h3>

{#if onAddNote}
  <div>
    <textarea bind:value={noteText} rows="2" placeholder="Add a note..."></textarea>
    <button onclick={submitNote} disabled={!noteText.trim()}>Add Note</button>
  </div>
{/if}

<div class="history-scroll">
  {#if timeline.length > 0}
    {#each timeline as entry}
      {#if entry.type === 'history'}
        <!-- Existing history entry rendering (preserve current logic) -->
        <div class="history-entry">
          {#if entry.data.text}
            <small><strong>{entry.data.username || 'Unknown'}</strong>
            {new Date(entry.data.timestamp).toLocaleString()}</small>
            <p>{entry.data.text}</p>
            {#if entry.data.changes}
              <small>{Object.entries(entry.data.changes)
                .filter(([k]) => !k.startsWith('_'))
                .map(([k, v]) => `${k}: ${v.old} → ${v.new}`)
                .join(', ')}</small>
            {/if}
          {:else}
            <small>{entry.data.username || 'System'}
            {new Date(entry.data.timestamp).toLocaleString()}
            {entry.data.entry_type} {entry.data.object_type}</small>
            {#if entry.data.changes}
              {#if entry.data.changes._created}
                <small>created</small>
              {/if}
              {#if entry.data.changes._action}
                <small>{entry.data.changes._action}</small>
              {/if}
              <small>{Object.entries(entry.data.changes)
                .filter(([k]) => !k.startsWith('_'))
                .map(([k, v]) => `${k}: ${v.old} → ${v.new}`)
                .join(', ')}</small>
            {/if}
          {/if}
        </div>
      {:else if entry.type === 'email'}
        {@const email = entry.data}
        {@const temp = email.temp_email}
        <div class="history-email">
          <small class="history-date">{entry.date.toLocaleString()}</small>
          {#if temp}
            <div>
              <span class="email-icon">@</span>
              <span class="email-subject" onclick={() => toggleEmail(email.email_record_id)}
                    role="button" tabindex="0"
                    onkeydown={(e) => e.key === 'Enter' && toggleEmail(email.email_record_id)}>
                {temp.subject || '(no subject)'}
              </span>
            </div>
            <div class="email-from">{temp.from_email}</div>
            <div class="email-preview-container" class:open={expandedEmails[email.email_record_id]}>
              <div class="email-preview-inner">
                <div class="email-preview">
                  <div class="ep-header">To: {temp.to_email} · {entry.date.toLocaleString()}</div>
                  <div><a href="/core/email/{email.email_record_id}/">View full email</a></div>
                </div>
              </div>
            </div>
          {:else}
            <div>
              <span class="email-icon">@</span>
              <span>Email (details no longer cached)</span>
            </div>
            <div><a href="/core/email/{email.email_record_id}/">View full email</a></div>
          {/if}
        </div>
      {/if}
    {/each}
  {:else}
    <p>No history.</p>
  {/if}
</div>
```

- [ ] **Step 3: Add email-specific styles**

Add a `<style>` block to `HistoryPanel.svelte`:

```css
.history-scroll {
  overflow-y: auto;
  max-height: 280px;
}

.history-entry, .history-email {
  padding: 6px 0;
  border-bottom: 1px solid #f0f0f0;
  font-size: 13px;
  line-height: 1.4;
}

.history-date { color: #999; font-size: 11px; }

.email-icon {
  display: inline-block;
  width: 16px; height: 16px;
  background: #dbeafe;
  border-radius: 3px;
  text-align: center;
  line-height: 16px;
  font-size: 10px;
  color: #2563eb;
  margin-right: 4px;
  vertical-align: middle;
}

.email-subject {
  color: #2563eb;
  cursor: pointer;
  font-weight: 500;
}
.email-subject:hover { text-decoration: underline; }

.email-from { color: #666; font-size: 12px; }

.email-preview-container {
  display: grid;
  grid-template-rows: 0fr;
  transition: grid-template-rows 0.2s ease;
}
.email-preview-container.open {
  grid-template-rows: 1fr;
}
.email-preview-inner { overflow: hidden; }

.email-preview {
  margin-top: 6px;
  padding: 8px 10px;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 4px;
  font-size: 12px;
  line-height: 1.5;
}
.ep-header { color: #888; font-size: 11px; margin-bottom: 4px; }
```

- [ ] **Step 4: Verify emails appear in history**

Navigate to a job detail page. If the job has associated EmailRecords, they should appear in the history timeline sorted by date. If no emails exist, the panel should still render normally with just history entries.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/HistoryPanel.svelte
git commit -m "feat: add email entries to HistoryPanel timeline"
```

---

## Task 8: Rewrite JobDetail with new header and layout

**Files:**
- Modify: `frontend/src/components/jobs/JobDetail.svelte`

This is the main rewrite. Do it in stages — this task covers the header, description, and history layout. Accordion sections come in the next tasks.

- [ ] **Step 1: Update props to include new data**

```javascript
const {
  job,
  contact = null,
  estimates = null,
  worksheets = null,
  workOrders = null,
  invoices = null,
  purchaseOrders = null,
  emails = null,
  history = null,
  onAddNote = null,
} = $props();
```

- [ ] **Step 2: Build the new header template**

Replace the existing `<dl>` header with:

```svelte
<div class="job-header">
  <h1>JOB #{job.job_number.replace(/^JOB-/, '')}: {job.name || '(untitled)'}</h1>
  <p class="customer-line">
    {#if contact}
      for <a href="#/contacts/{contact.contact_id}">{contact.name}</a>{#if contact.business}, at <a href="#/businesses/{contact.business.business_id}">{contact.business.business_name}</a>{/if}
    {/if}
  </p>

  <div class="status-line">
    <span class="status-badge status-{job.status}">{job.status}</span>
    <span class="dates">
      {#if job.start_date}Started {new Date(job.start_date).toLocaleDateString()}{/if}
      {#if job.due_date}{job.start_date ? ' · ' : ''}Due {new Date(job.due_date).toLocaleDateString()}{/if}
      {#if job.completed_date}{(job.start_date || job.due_date) ? ' · ' : ''}Completed {new Date(job.completed_date).toLocaleDateString()}{/if}
      {#if job.customer_po_number}{(job.start_date || job.due_date || job.completed_date) ? ' · ' : ''}PO: {job.customer_po_number}{/if}
    </span>
  </div>
</div>
```

- [ ] **Step 3: Build the description + history side-by-side layout**

```svelte
<div class="desc-history">
  <div class="description">
    <div class="label">Description</div>
    <p>{job.description || 'No description.'}</p>
  </div>
  <div class="history-panel-container">
    <HistoryPanel {history} {emails} {onAddNote} />
  </div>
</div>
```

- [ ] **Step 4: Add component styles**

Add a `<style>` block:

```css
.job-header h1 { font-size: 26px; font-weight: 700; margin-bottom: 4px; }
.customer-line { font-size: 16px; color: #555; margin-bottom: 16px; }
.status-line { margin-bottom: 20px; }
.status-badge {
  padding: 4px 12px;
  border-radius: 12px;
  font-size: 13px;
  font-weight: 600;
  text-transform: capitalize;
}
.status-draft { background: #f3f4f6; color: #374151; }
.status-approved { background: #dcfce7; color: #166534; }
.status-complete, .status-completed { background: #dbeafe; color: #1e40af; }
.status-rejected { background: #fee2e2; color: #991b1b; }
.status-cancelled { background: #fef3c7; color: #92400e; }
.dates { color: #888; font-size: 13px; margin-left: 12px; }

.desc-history {
  display: flex;
  gap: 20px;
  margin-bottom: 28px;
  align-items: stretch;
}
.description {
  background: #f8f9fa;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  padding: 16px;
  min-height: 160px;
  flex: 1;
}
.description .label {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: #888;
  margin-bottom: 8px;
}
.description p { line-height: 1.6; color: #333; }

.history-panel-container {
  width: 320px;
  min-width: 320px;
}
```

- [ ] **Step 5: Verify header and layout render correctly**

Navigate to a job detail page. Verify: title format is `JOB #NUMBER: Name`, customer/business links work, status badge shows, description and history are side by side.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/jobs/JobDetail.svelte
git commit -m "feat: new Job detail header with description + history layout"
```

---

## Task 9: Add accordion sections to JobDetail

**Files:**
- Modify: `frontend/src/components/jobs/JobDetail.svelte`

- [ ] **Step 1: Add derived state for default-open logic and data**

```javascript
import Accordion from '../Accordion.svelte';

// Determine which accordion opens by default
let defaultOpen = $derived.by(() => {
  if (job.status === 'completed') {
    if (invoices?.results?.length > 0) return 'invoices';
  }
  if (workOrders?.results?.length > 0) return 'workorder';
  if (estimates?.results?.length > 0) return 'estimates';
  if (worksheets?.results?.length > 0) return 'worksheets';
  return 'worksheets';
});

// Current (non-superseded) estimate
let currentEstimate = $derived(
  estimates?.results?.find(e => e.status !== 'superseded') || estimates?.results?.[0] || null
);
let supersededCount = $derived(
  (estimates?.results?.filter(e => e.status === 'superseded') || []).length
);

// Latest worksheet (highest version)
let currentWorksheet = $derived.by(() => {
  const ws = worksheets?.results || [];
  if (ws.length === 0) return null;
  return ws.reduce((best, w) => (w.version > best.version ? w : best), ws[0]);
});
```

- [ ] **Step 2: Add Worksheet accordion section**

```svelte
<!-- Worksheet -->
<Accordion
  title="Worksheet"
  meta={currentWorksheet ? `v${currentWorksheet.version} · ${currentWorksheet.status}` : 'None'}
  metaDim={(worksheets?.results?.length || 0) > 1 ? `(${worksheets.results.length} worksheets)` : ''}
  open={defaultOpen === 'worksheets'}
  headerBg="#0d9488"
  borderColor="#99f6e4"
>
  {#if currentWorksheet?.tasks?.length > 0}
    <table class="ws-table">
      <thead><tr><th>Task</th><th class="text-center">Status</th></tr></thead>
      <tbody>
        {#each currentWorksheet.tasks as task}
          <tr>
            <td>{task.name}</td>
            <td class="text-center"><span class="pill pill-{task.status}">{task.status}</span></td>
          </tr>
        {/each}
      </tbody>
    </table>
  {:else}
    <p class="empty-msg">No worksheet data.</p>
  {/if}
</Accordion>
```

- [ ] **Step 3: Add Estimate accordion section**

```svelte
<!-- Estimate -->
<Accordion
  title="Estimate"
  meta={currentEstimate ? `${currentEstimate.estimate_number} · v${currentEstimate.version} · ${currentEstimate.status}` : 'None'}
  metaDim={supersededCount > 0 ? `(${supersededCount} previous)` : ''}
  open={defaultOpen === 'estimates'}
  headerBg="#4f46e5"
  borderColor="#c7d2fe"
>
  {#if currentEstimate?.line_items?.length > 0}
    <table class="est-table">
      <thead><tr>
        <th>#</th><th>Description</th>
        <th class="text-right">Qty</th><th class="text-right">Price</th><th class="text-right">Total</th>
      </tr></thead>
      <tbody>
        {#each currentEstimate.line_items as li}
          <tr>
            <td>{li.line_number}</td>
            <td>{li.description}</td>
            <td class="text-right">{li.qty} {li.units || ''}</td>
            <td class="text-right">${Number(li.price).toFixed(2)}</td>
            <td class="text-right">${(Number(li.qty) * Number(li.price)).toFixed(2)}</td>
          </tr>
        {/each}
      </tbody>
      <tfoot>
        <tr>
          <td colspan="4" class="text-right" style="font-weight:600;">Total</td>
          <td class="text-right" style="font-weight:700;">
            ${currentEstimate.line_items.reduce((sum, li) => sum + Number(li.qty) * Number(li.price), 0).toFixed(2)}
          </td>
        </tr>
      </tfoot>
    </table>
    {#if supersededCount > 0}
      <div class="prev-link">
        {#each estimates.results.filter(e => e.status === 'superseded') as prev}
          <a href="#/estimates/{prev.estimate_id}">{prev.estimate_number} (v{prev.version}, superseded)</a>
        {/each}
      </div>
    {/if}
  {:else if currentEstimate}
    <p class="empty-msg">Estimate has no line items.</p>
  {:else}
    <p class="empty-msg">No estimates yet.</p>
  {/if}
</Accordion>
```

- [ ] **Step 4: Add Work Order accordion section**

```svelte
<!-- Work Order -->
{@const wo = workOrders?.results?.[0] || null}
<Accordion
  title="Work Order"
  meta={wo ? `${wo.template_name ? wo.template_name + ' · ' : ''}${wo.status}` : 'None'}
  open={defaultOpen === 'workorder'}
  headerBg="#b45309"
  borderColor="#fbbf24"
>
  {#if wo?.tasks?.length > 0}
    <table class="wo-table">
      <thead><tr><th>Task</th><th>Assigned</th><th class="text-center">Status</th></tr></thead>
      <tbody>
        {#each wo.tasks as task}
          <tr class:row-active={task.status === 'in_progress'}>
            <td><a href="#/tasks/{task.task_id}">{task.name}</a></td>
            <td class="assigned">{task.assignee_name || '—'}</td>
            <td class="text-center"><span class="pill pill-{task.status}">{task.status}</span></td>
          </tr>
        {/each}
      </tbody>
    </table>
  {:else}
    <p class="empty-msg">No work orders yet.</p>
  {/if}
</Accordion>
```

- [ ] **Step 5: Add Invoice accordion section**

```svelte
<!-- Invoices -->
{@const invList = invoices?.results || []}
<Accordion
  title="Invoices"
  meta={invList.length > 0 ? `${invList[0].invoice_number} · ${invList.length} invoice${invList.length > 1 ? 's' : ''}` : 'None yet'}
  open={defaultOpen === 'invoices'}
  headerBg="#15803d"
  borderColor="#bbf7d0"
>
  {#if invList.length > 0}
    <table class="inv-table">
      <thead><tr><th>Invoice #</th><th>Status</th><th class="text-right">Total</th></tr></thead>
      <tbody>
        {#each invList as inv}
          <tr>
            <td><a href="#/invoices/{inv.invoice_id}">{inv.invoice_number}</a></td>
            <td><span class="pill pill-{inv.status}">{inv.status}</span></td>
            <td class="text-right">
              ${inv.line_items?.reduce((sum, li) => sum + Number(li.qty) * Number(li.price), 0).toFixed(2) || '0.00'}
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  {:else}
    <p class="empty-msg">No invoices created for this job yet.</p>
  {/if}
</Accordion>
```

- [ ] **Step 6: Add Purchase Orders accordion section**

```svelte
<!-- Purchase Orders -->
{@const poList = purchaseOrders?.results || []}
<Accordion
  title="Purchase Orders"
  meta={poList.length > 0 ? `${poList[0].po_number} · ${poList.length} order${poList.length > 1 ? 's' : ''}` : 'None'}
  open={false}
  headerBg="#475569"
  borderColor="#cbd5e1"
>
  {#if poList.length > 0}
    <table class="po-table">
      <thead><tr><th>PO #</th><th>Vendor</th><th class="text-right">Total</th><th class="text-center">Status</th></tr></thead>
      <tbody>
        {#each poList as po}
          <tr>
            <td><a href="#/purchase-orders/{po.po_id}">{po.po_number}</a></td>
            <td>{po.business_name}</td>
            <td class="text-right">
              ${po.line_items?.reduce((sum, li) => sum + Number(li.qty) * Number(li.price), 0).toFixed(2) || '0.00'}
            </td>
            <td class="text-center"><span class="pill pill-{po.status}">{po.status}</span></td>
          </tr>
        {/each}
      </tbody>
    </table>
  {:else}
    <p class="empty-msg">No purchase orders for this job.</p>
  {/if}
</Accordion>
```

- [ ] **Step 7: Add section-specific table styles and pill styles**

Add to the `<style>` block in `JobDetail.svelte`:

```css
/* Shared table styles */
table { width: 100%; border-collapse: collapse; font-size: 14px; border: none; }
th { text-align: left; padding: 8px 16px; font-weight: 600; }
td { padding: 8px 16px; }
.text-right { text-align: right; }
.text-center { text-align: center; }
.assigned { color: #555; }
.empty-msg { padding: 16px; color: #888; text-align: center; }
.prev-link { padding: 8px 16px 12px; font-size: 13px; }

/* Status pills */
.pill {
  padding: 2px 10px;
  border-radius: 10px;
  font-size: 12px;
  font-weight: 500;
  text-transform: capitalize;
}
.pill-complete { background: #e0f2fe; color: #0369a1; }
.pill-in_progress { background: #fef3c7; color: #92400e; }
.pill-pending { background: #f3e8ff; color: #7c3aed; }
.pill-draft { background: #f3f4f6; color: #6b7280; }
.pill-final { background: #e0e7ff; color: #4338ca; }
.pill-blocked { background: #fee2e2; color: #991b1b; }
.pill-cancelled { background: #fecaca; color: #991b1b; }
.pill-accepted { background: #dcfce7; color: #166534; }
.pill-open { background: #dbeafe; color: #1e40af; }
.pill-active { background: #dcfce7; color: #166534; }
.pill-received { background: #e0f2fe; color: #0369a1; }
.pill-issued { background: #dbeafe; color: #1e40af; }

/* Worksheet table colors */
.ws-table thead { background: #ccfbf1; }
.ws-table thead th { color: #115e59; }
.ws-table tbody tr { background: #f0fdfa; }
.ws-table tbody tr:nth-child(even) { background: #e6faf5; }
.ws-table tbody tr + tr { border-top: 1px solid #ccfbf1; }

/* Estimate table colors */
.est-table thead { background: #ddd6fe; }
.est-table thead th { color: #3730a3; }
.est-table tbody tr { background: #eef2ff; }
.est-table tbody tr:nth-child(even) { background: #e8e5ff; }
.est-table tbody tr + tr { border-top: 1px solid #ddd6fe; }
.est-table tfoot { background: #e0e7ff; border-top: 2px solid #c7d2fe; }
.est-table tfoot td { color: #3730a3; }

/* Work Order table colors */
.wo-table thead { background: #fde68a; }
.wo-table thead th { color: #78350f; }
.wo-table tbody tr { background: #fffbeb; }
.wo-table tbody tr:nth-child(even) { background: #fef3c7; }
.wo-table tbody tr + tr { border-top: 1px solid #fde68a; }
.wo-table .row-active { background: #fde68a; }

/* Invoice table colors */
.inv-table thead { background: #bbf7d0; }
.inv-table thead th { color: #14532d; }
.inv-table tbody tr { background: #f0fdf4; }
.inv-table tbody tr:nth-child(even) { background: #dcfce7; }
.inv-table tbody tr + tr { border-top: 1px solid #bbf7d0; }

/* PO table colors */
.po-table thead { background: #e2e8f0; }
.po-table thead th { color: #334155; }
.po-table tbody tr { background: #f8fafc; }
.po-table tbody tr:nth-child(even) { background: #f1f5f9; }
.po-table tbody tr + tr { border-top: 1px solid #e2e8f0; }
```

- [ ] **Step 8: Remove old sections and verify**

Remove any remaining old `<dl>` / table sections from the previous JobDetail implementation. The component should now render: header → description+history → accordion bars. Verify all five accordion sections render, default-open logic works, and the slide animation fires on click.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/components/jobs/JobDetail.svelte
git commit -m "feat: add accordion document sections to Job detail view"
```

---

## Task 10: PO line item job differentiation

**Files:**
- Modify: `frontend/src/components/jobs/JobDetail.svelte`

- [ ] **Step 1: Update PO section to show line items with job differentiation**

Replace the PO table body to expand line items per PO, graying out items linked to other jobs:

```svelte
{#each poList as po}
  <tr>
    <td><a href="#/purchase-orders/{po.po_id}">{po.po_number}</a></td>
    <td>{po.business_name}</td>
    <td class="text-right">
      ${po.line_items?.reduce((sum, li) => sum + Number(li.qty) * Number(li.price), 0).toFixed(2) || '0.00'}
    </td>
    <td class="text-center"><span class="pill pill-{po.status}">{po.status}</span></td>
  </tr>
  {#if po.line_items?.some(li => li.job && li.job !== job.job_id)}
    {#each po.line_items as li}
      <tr class:other-job={li.job && li.job !== job.job_id}>
        <td colspan="2" style="padding-left: 32px; font-size: 13px;">
          {li.description}
          {#if li.job && li.job !== job.job_id}
            <span class="other-job-label">(other job)</span>
          {/if}
        </td>
        <td class="text-right" style="font-size: 13px;">${(Number(li.qty) * Number(li.price)).toFixed(2)}</td>
        <td></td>
      </tr>
    {/each}
  {/if}
{/each}
```

- [ ] **Step 2: Add styles for other-job rows**

```css
.other-job {
  opacity: 0.5;
}
.other-job-label {
  font-size: 11px;
  color: #999;
  font-style: italic;
  margin-left: 4px;
}
```

- [ ] **Step 3: Verify with a PO that has mixed-job line items**

If test data exists with POs spanning multiple jobs, verify that line items for other jobs appear grayed out. If not, verify the normal case renders cleanly without the differentiation showing.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/jobs/JobDetail.svelte
git commit -m "feat: visually differentiate PO line items from other jobs"
```

---

## Task 11: Site header placeholder

**Files:**
- Modify: `frontend/src/App.svelte`

- [ ] **Step 1: Add a placeholder div for the future site header**

In `App.svelte`, above the `<Nav>` component, add a placeholder:

```svelte
<!-- Site header placeholder — will contain navigation and user info -->
<div class="site-header-placeholder">
  <Nav />
</div>
```

This wraps the existing `<Nav>` in a container that can later be replaced with the full site header without touching the rest of the layout.

- [ ] **Step 2: Commit**

```bash
git add frontend/src/App.svelte
git commit -m "feat: wrap Nav in site header placeholder for future redesign"
```

---

## Task 12: Final integration test

- [ ] **Step 1: Run all backend tests**

Run: `python manage.py test -v 2`
Expected: All tests pass, including new PO filter and serializer tests.

- [ ] **Step 2: Manual smoke test of the full flow**

With the dev server running (`python manage.py runserver` + `cd frontend && npm run dev`):

1. Navigate to a job with work orders → verify Work Order accordion is open by default
2. Navigate to a job with only estimates → verify Estimate accordion is open
3. Navigate to a draft job → verify Worksheet accordion is open
4. Click accordion bars to open/close → verify slide animation works
5. Verify history panel scrolls independently
6. Verify contact and business links in header work
7. Check the PO section renders (if job has POs)
8. Check browser console for any errors

- [ ] **Step 3: Commit any final fixes**

```bash
git add -A
git commit -m "fix: integration fixes for Job detail redesign"
```

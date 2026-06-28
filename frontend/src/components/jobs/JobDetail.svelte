<script>
  import EmailPanel from '../EmailPanel.svelte';
  import LinkifiedText from '../LinkifiedText.svelte';
  import TaskActivityIndicator from '../tasks/TaskActivityIndicator.svelte';
  import TaskTree from '../TaskTree.svelte';
  import DeliverablesSection from './DeliverablesSection.svelte';
  import ShipmentsPillar from './ShipmentsPillar.svelte';
  import { link } from 'svelte-spa-router';
  import JobHeader from './JobHeader.svelte';
  import { canManageFinancials as canManageFinancialsStore } from '../../stores/permissions.js';
  import { api } from '../../lib/api.js';

  const {
    job,
    contact = null,
    estimates = null,
    worksheets = null,
    invoices = null,
    purchaseOrders = null,
    emails = null,
    expenses = null,
    onStatusChange = null,
  } = $props();

  // Expenses on this job (list payload may be paginated or a bare array).
  let jobExpenses = $derived(
    expenses ? (expenses.results ?? expenses) : []
  );
  // Material-less expenses get their own rows; material-linked ones annotate
  // their material's row (cost lives on the material — avoids double-showing).
  let looseExpenses = $derived(jobExpenses.filter((e) => !e.material));
  let expenseByMaterial = $derived(
    Object.fromEntries(
      jobExpenses.filter((e) => e.material).map((e) => [e.material, e])
    )
  );
  function money(v) {
    return v != null && v !== '' ? `$${Number(v).toFixed(2)}` : '—';
  }

  // Permission check
  // Job-scoped management uses the per-object can_manage (atom-holder OR this
  // job's PM), already ANDed server-side. Financials stays on its global atom —
  // it's a separate permission, not part of PM access.
  let canManageJobs = $derived(job?.can_manage ?? false);
  let canManageFinancials = $derived($canManageFinancialsStore);

  // Estimate versions, sorted oldest first for left-to-right tabs
  let estimateList = $derived(
    [...(estimates?.results || [])].sort((a, b) => a.version - b.version)
  );
  // Current (non-superseded) estimate; falls back to most recent if all superseded
  let currentEstimate = $derived(
    estimateList.findLast(e => e.status !== 'superseded') || estimateList[estimateList.length - 1] || null
  );
  let supersededCount = $derived(
    estimateList.filter(e => e.status === 'superseded').length
  );

  // Unified version timeline: estimate versions (oldest→newest) then COs by number/id
  // selectedVersionKey is 'est-<id>' or 'co-<id>'
  let selectedVersionKey = $state(null);

  let sortedChangeOrders = $derived(
    [...(changeOrders || [])].sort((a, b) => {
      // Sort by change_order_number string if present; fall back to id
      if (a.change_order_number && b.change_order_number) {
        return a.change_order_number.localeCompare(b.change_order_number);
      }
      return (a.change_order_id ?? 0) - (b.change_order_id ?? 0);
    })
  );

  // Version timeline: estimate entries then CO entries
  let versionTimeline = $derived([
    ...estimateList.map(est => ({ kind: /** @type {'estimate'} */ ('estimate'), key: `est-${est.estimate_id}`, est })),
    ...sortedChangeOrders.map(co => ({ kind: /** @type {'co'} */ ('co'), key: `co-${co.change_order_id}`, co })),
  ]);

  // Default to latest CO if any exist, otherwise the current estimate
  let defaultVersionKey = $derived(
    sortedChangeOrders.length > 0
      ? `co-${sortedChangeOrders[sortedChangeOrders.length - 1].change_order_id}`
      : (currentEstimate ? `est-${currentEstimate.estimate_id}` : null)
  );

  let displayedVersion = $derived(
    versionTimeline.find(v => v.key === selectedVersionKey)
    || versionTimeline.find(v => v.key === defaultVersionKey)
    || versionTimeline[versionTimeline.length - 1]
    || null
  );

  // Convenience aliases to keep downstream template logic readable
  let displayedEstimate = $derived(
    displayedVersion?.kind === 'estimate' ? displayedVersion.est : null
  );
  let displayedCO = $derived(
    displayedVersion?.kind === 'co' ? displayedVersion.co : null
  );

  // Effective lines when a CO is displayed — multi-CO layering.
  //
  // How it works:
  //   1. Start from the base estimate's line items (the estimate the displayed CO
  //      belongs to, sorted by line_number).
  //   2. Collect every *accepted* CO on that same estimate, sorted by
  //      change_order_id ascending (agreement order). Layer each one's deltas onto
  //      the running set in order — remove drops a line, replace swaps content
  //      (tagging it with that CO's ordinal), add appends (tagged with its ordinal).
  //   3. Then layer the displayedCO on top, depending on its status:
  //        - 'accepted'  → already applied in step 2; nothing extra.
  //        - 'draft'/'open' → apply its deltas as a proposed view, tagging with its ordinal.
  //        - 'rejected'/'expired'/'superseded' → do NOT apply; effective view is
  //          the accepted agreement only (displayedCO's badge still shows its real status).
  //   4. Each output row carries:
  //        coTouched: 'changed' | 'added' | null  (drives row styling — unchanged)
  //        coOrdinal: number | null  (ordinal of the CO that most recently touched it;
  //                                   null for lines unchanged from the base estimate)
  //
  // Ordinal = 1-based position in the list of all COs on this estimate sorted by
  // change_order_id (not parsed from the CO number string).

  /** Apply one CO's deltas to a running line set, tagging touched lines with the given ordinal. */
  function applyCoDeltas(lines, coItems, ordinal) {
    const replaceByTarget = new Map();
    const removeByTarget  = new Map();
    const addItems = [];
    for (const ci of coItems) {
      if (ci.action === 'replace' && ci.target_line_item) {
        replaceByTarget.set(ci.target_line_item, ci);
      } else if (ci.action === 'remove' && ci.target_line_item) {
        removeByTarget.set(ci.target_line_item, ci);
      } else if (ci.action === 'add') {
        addItems.push(ci);
      }
    }
    const result = [];
    for (const el of lines) {
      if (removeByTarget.has(el.line_item_id)) {
        // Drop removed lines entirely
      } else if (replaceByTarget.has(el.line_item_id)) {
        const ci = replaceByTarget.get(el.line_item_id);
        result.push({
          line_item_id: el.line_item_id,
          line_number: el.line_number,
          description: ci.description,
          qty: ci.qty,
          units: ci.units,
          price: ci.price,
          coTouched: 'changed',
          coOrdinal: ordinal,
        });
      } else {
        result.push({ ...el });
      }
    }
    for (const ci of addItems) {
      result.push({
        line_item_id: null,
        line_number: ci.line_number,
        description: ci.description,
        qty: ci.qty,
        units: ci.units,
        price: ci.price,
        coTouched: 'added',
        coOrdinal: ordinal,
      });
    }
    return result;
  }

  let coEffectiveLines = $derived.by(() => {
    if (!displayedCO) return [];
    const co = displayedCO;
    const baseEst = estimateList.find(e => e.estimate_id === co.estimate);

    // Base lines from the estimate this CO targets
    let lines = (baseEst?.line_items || []).slice()
      .sort((a, b) => a.line_number - b.line_number)
      .map(el => ({
        line_item_id: el.line_item_id,
        line_number: el.line_number,
        description: el.description,
        qty: el.qty,
        units: el.units,
        price: el.price,
        coTouched: /** @type {null} */ (null),
        coOrdinal: /** @type {number|null} */ (null),
      }));

    // All COs on this estimate sorted by id (agreement order)
    const cosOnEst = (changeOrders || [])
      .filter(c => c.estimate === co.estimate)
      .slice()
      .sort((a, b) => a.change_order_id - b.change_order_id);

    // Ordinal map: change_order_id → 1-based position among all COs on this estimate
    const ordinalOf = new Map(cosOnEst.map((c, i) => [c.change_order_id, i + 1]));

    // Step 2: layer every accepted CO in agreement order
    for (const acceptedCo of cosOnEst) {
      if (acceptedCo.status !== 'accepted') continue;
      lines = applyCoDeltas(lines, acceptedCo.line_items || [], ordinalOf.get(acceptedCo.change_order_id));
    }

    // Step 3: layer displayedCO if it is in a proposed (not-yet-decided) state
    const PROPOSED = new Set(['draft', 'open']);
    if (PROPOSED.has(co.status)) {
      lines = applyCoDeltas(lines, co.line_items || [], ordinalOf.get(co.change_order_id));
    }
    // 'accepted' → already applied above; 'rejected'/'expired'/'superseded' → skip

    return lines;
  });

  // Footer total for the effective CO view
  let coEffectiveTotal = $derived(
    coEffectiveLines.reduce((s, li) => s + Number(li.qty || 0) * Number(li.price || 0), 0)
  );

  // Number of COs on the displayed CO's estimate — drives single vs. numbered badge
  let coCountOnEstimate = $derived(
    displayedCO
      ? (changeOrders || []).filter(c => c.estimate === displayedCO.estimate).length
      : 0
  );

  // Worksheet versions, sorted newest first
  let worksheetList = $derived(
    [...(worksheets?.results || [])].sort((a, b) => b.est_worksheet_id - a.est_worksheet_id)
  );
  // Latest worksheet (highest version)
  let currentWorksheet = $derived(worksheetList[0] || null);

  // Active worksheet shown in panel (user can click a tab to switch)
  let selectedWorksheetId = $state(null);
  let displayedWorksheet = $derived(
    worksheetList.find(w => w.est_worksheet_id === selectedWorksheetId) || currentWorksheet
  );

  // For each task: per-unit Price (amount / qty when qty > 0).
  function fmt(n) {
    if (n === null || n === undefined || n === '' || isNaN(Number(n))) return '—';
    return `$${Number(n).toFixed(2)}`;
  }
  function unitPrice(task) {
    const qty = Number(task.est_qty);
    const amount = Number(task.amount);
    if (!qty || isNaN(amount)) return null;
    return amount / qty;
  }
  function materialTotal(mat) {
    return (Number(mat.quantity) || 0) * (Number(mat.sell_price) || 0);
  }
  let worksheetGrandTotal = $derived.by(() => {
    if (!displayedWorksheet) return 0;
    let total = 0;
    for (const t of (displayedWorksheet.tasks || [])) {
      total += Number(t.amount) || 0;
      for (const m of (t.plan_materials || [])) total += materialTotal(m);
    }
    for (const m of (displayedWorksheet.taskless_materials || [])) {
      total += materialTotal(m);
    }
    return total;
  });

  // Job tasks (top-level), invoice list, PO list
  let jobTasks = $derived((job.tasks || []).filter(t => !t.parent_task));
  let hasTasks = $derived(jobTasks.length > 0);
  let invList = $derived(invoices?.results || []);
  let poList = $derived(purchaseOrders?.results || []);
  let draftInvoice = $derived(invList.find(inv => inv.status === 'draft') || null);

  // Shipments are managed on the dedicated Job Shipments page. Only count
  // is shown here for at-a-glance information on the accordion pillar.
  let shipmentCount = $state(0);
  let hasOutstandingDeliverables = $state(false);

  // Change orders
  let changeOrders = $state([]);
  let creatingCo = $state(false);
  let hasLiveChangeOrder = $derived(
    (changeOrders || []).some(co => co.status === 'draft' || co.status === 'open')
  );

  async function refreshShipmentCount() {
    try {
      const r = await api.get(`/api/shipments/?job=${job.job_id}`);
      const list = r?.results || r || [];
      shipmentCount = list.length;
    } catch {
      shipmentCount = 0;
    }
  }

  async function refreshDeliverableFulfillment() {
    try {
      const items = await api.get(`/api/jobs/${job.job_id}/deliverables/`);
      hasOutstandingDeliverables = (items || []).some(d => Number(d.qty_remaining) > 0);
    } catch {
      hasOutstandingDeliverables = false;
    }
  }

  async function refreshChangeOrders() {
    try {
      const r = await api.get(`/api/change-orders/?job=${job.job_id}`);
      changeOrders = r?.results || r || [];
    } catch {
      changeOrders = [];
    }
  }

  let canStartEstimate = $derived(
    canManageJobs &&
    (job.status === 'draft' || job.status === 'submitted') &&
    !currentWorksheet
  );

  let startingEstimate = $state(false);
  async function startEstimate() {
    startingEstimate = true;
    try {
      // Worksheet creation is idempotent (one Plan per job), so this is safe to
      // POST directly and land on the Plan — no intermediate template-choice page.
      const ws = await api.post('/api/est-worksheets/', { job: job.job_id });
      window.location.hash = `/worksheets/${ws.est_worksheet_id}`;
    } catch (e) {
      alert(e.message || 'Failed to start estimate.');
    } finally {
      startingEstimate = false;
    }
  }

  async function createChangeOrder() {
    creatingCo = true;
    try {
      const co = await api.post('/api/change-orders/', { job: job.job_id });
      window.location.hash = `/change-orders/${co.change_order_id}`;
    } catch (e) {
      alert(e.message || 'Failed to create change order.');
    } finally {
      creatingCo = false;
    }
  }

  $effect(() => {
    if (job?.job_id) {
      refreshShipmentCount();
      refreshDeliverableFulfillment();
      refreshChangeOrders();
    }
  });

  // Display status for estimates: show "amended" instead of "accepted" when the
  // estimate has been amended by an accepted change order. Derived server-side
  // (EstimateSerializer.is_amended); the stored status stays "accepted".
  function estimateDisplayStatus(est) {
    return est?.is_amended ? 'amended' : est?.status;
  }

  // Display status for change orders: show "amended" instead of "accepted" when
  // a later accepted CO exists on the same job (ordered by change_order_id).
  // Only an accepted later CO triggers the relabel — draft/open/rejected/etc. do not.
  function changeOrderDisplayStatus(co, allCosForJob) {
    if (co?.status === 'accepted' && (allCosForJob || []).some(
      other => other.change_order_id > co.change_order_id
               && other.status === 'accepted'
    )) {
      return 'amended';
    }
    return co?.status;
  }

  // Invoice helpers
  function invoiceTotal(inv) {
    return (inv?.line_items || []).reduce(
      (s, li) => s + Number(li.qty || 0) * Number(li.price || 0), 0,
    );
  }
  function invoicePaid(inv) {
    return Number(inv?.qbo_amount_paid) || 0;
  }
  function fmtMoney(n) {
    return `$${(Number(n) || 0).toFixed(2)}`;
  }
  function fmtDate(s) {
    if (!s) return '—';
    return new Date(s).toLocaleDateString();
  }

  // Oldest first for left-to-right tabs; default to most-recent-unpaid, else most-recent.
  const UNPAID = new Set(['open', 'partly-paid', 'defaulted']);
  let sortedInvoices = $derived(
    [...invList].sort((a, b) => new Date(a.created_date) - new Date(b.created_date))
  );
  let defaultInvoice = $derived(
    sortedInvoices.findLast(i => UNPAID.has(i.status)) || sortedInvoices[sortedInvoices.length - 1] || null
  );
  let selectedInvoiceId = $state(null);
  let displayedInvoice = $derived(
    sortedInvoices.find(i => i.invoice_id === selectedInvoiceId) || defaultInvoice
  );

  // Rollup across all invoices (excluding cancelled/superseded from billed totals).
  const COUNTS_AS_BILLED = (s) => s !== 'cancelled' && s !== 'superseded' && s !== 'draft';
  let totalBilled = $derived(
    invList.filter(i => COUNTS_AS_BILLED(i.status))
           .reduce((s, inv) => s + invoiceTotal(inv), 0)
  );
  let totalPaid = $derived(
    invList.reduce((s, inv) => s + invoicePaid(inv), 0)
  );
  let totalOutstanding = $derived(totalBilled - totalPaid);

  // Purchase order helpers
  function poTotal(po) {
    return (po?.line_items || []).reduce(
      (s, li) => s + Number(li.qty || 0) * Number(li.price || 0), 0,
    );
  }
  let sortedPOs = $derived(
    [...poList].sort((a, b) => new Date(a.created_date) - new Date(b.created_date))
  );
  let selectedPoId = $state(null);
  let displayedPo = $derived(
    sortedPOs.find(p => p.po_id === selectedPoId) || sortedPOs[sortedPOs.length - 1] || null
  );
  let totalCommitted = $derived(
    poList.filter(p => p.status !== 'cancelled')
          .reduce((s, p) => s + poTotal(p), 0)
  );
  const BILLABLE_JOB_STATUSES = [
    'approved', 'in_progress', 'work_complete', 'completed', 'cancelled',
  ];
  let creatingInvoice = $state(false);
  let canCreateInvoice = $derived(
    (canManageJobs || canManageFinancials) &&
    BILLABLE_JOB_STATUSES.includes(job.status) &&
    !draftInvoice
  );

  async function createInvoiceManual() {
    creatingInvoice = true;
    try {
      const inv = await api.post('/api/invoices/', { job: job.job_id });
      window.location.hash = `/invoices/${inv.invoice_id}`;
    } catch (e) {
      alert(e.data?.detail || e.message || 'Failed to create invoice.');
    } finally {
      creatingInvoice = false;
    }
  }

  // All materials on this job (for the Materials section)
  let jobMaterials = $derived(job.materials || []);

  // Horizontal accordion state — which section is expanded
  const VALID_SECTIONS = ['estimate', 'tasks_materials', 'invoices', 'shipments', 'pos'];
  const storageKey = (id) => `jobDetailActiveSection_${id}`;

  function getDefaultSection() {
    if (job.status === 'work_complete' || job.status === 'completed') {
      if (invoices?.results?.length > 0) return 'invoices';
    }
    if (shipmentCount > 0 && hasOutstandingDeliverables) return 'shipments';
    if (jobTasks.length > 0) return 'tasks_materials';
    if (estimates?.results?.length > 0 || worksheets?.results?.length > 0) return 'estimate';
    return 'estimate';
  }

  function readStoredSection(id) {
    try {
      const v = sessionStorage.getItem(storageKey(id));
      // Migrate old section keys to the unified pillars
      if (v === 'worksheets' || v === 'estimates') return 'estimate';
      if (v === 'tasks' || v === 'materials') return 'tasks_materials';
      return VALID_SECTIONS.includes(v) ? v : null;
    } catch { return null; }
  }

  // Toggle inside the Estimate pillar: 'plan' | 'client-view'
  // Default: 'plan' when there is no live estimate or it is draft; 'client-view' once sent/frozen.
  // Computed from the raw prop (not a $derived) so it only sets the initial default, not re-deriving
  // on every data update (which would override the user's manual toggle choice).
  const PLAN_DEFAULT_STATUSES = new Set(['draft', 'superseded', null, undefined]);
  function initialEstimateView() {
    const estList = [...(estimates?.results || [])].sort((a, b) => a.version - b.version);
    const liveEst = estList.findLast(e => e.status !== 'superseded') || estList[estList.length - 1] || null;
    return (!liveEst || PLAN_DEFAULT_STATUSES.has(liveEst?.status)) ? 'plan' : 'client-view';
  }
  let estimateView = $state(initialEstimateView());

  let userSection = $state(null);
  let activeSection = $derived(userSection ?? readStoredSection(job.job_id) ?? getDefaultSection());

  // Drop overrides when navigating to a different job so stored/default re-applies.
  $effect(() => {
    void job.job_id;
    userSection = null;
    selectedWorksheetId = null;
    selectedVersionKey = null;
    selectedInvoiceId = null;
    selectedPoId = null;
    estimateView = initialEstimateView();
    enrichedTasks = [];
    enrichedJobId = null;
  });

  function openSection(s) {
    userSection = s;
    try { sessionStorage.setItem(storageKey(job.job_id), s); } catch {}
  }

  // The combined Tasks & Materials pillar renders the Task View (TaskTree), which
  // wants tasks pre-loaded with their materials + subtasks. The job payload only
  // carries flat top-level tasks, so we lazily fetch per-task children when the
  // pillar is open (read view; full interactions live on the task-list page).
  let enrichedTasks = $state([]);
  let enrichedJobId = $state(null);
  let enriching = $state(false);
  // Job-level materials only (task-linked ones ride inside the enriched tree).
  let jobLevelMaterials = $derived(jobMaterials.filter(m => !m.task));

  async function fetchTaskChildren(taskId, what) {
    try { const r = await api.get(`/api/tasks/${taskId}/${what}/`); return r.results ?? r; }
    catch { return []; }
  }
  async function enrichTasks() {
    enriching = true;
    try {
      const tops = (job.tasks || []).filter(t => !t.parent_task);
      enrichedTasks = await Promise.all(tops.map(async (task) => {
        const [materials, subtasks] = await Promise.all([
          fetchTaskChildren(task.task_id, 'materials'),
          fetchTaskChildren(task.task_id, 'subtasks'),
        ]);
        const enrichedSubs = await Promise.all(subtasks.map(async (sub) => ({
          ...sub, materials: await fetchTaskChildren(sub.task_id, 'materials'),
        })));
        return { ...task, materials, subtasks: enrichedSubs };
      }));
      enrichedJobId = job.job_id;
    } finally { enriching = false; }
  }

  $effect(() => {
    if (activeSection === 'tasks_materials' && enrichedJobId !== job.job_id && !enriching) {
      enrichTasks();
    }
  });
</script>

<div class="job-detail-page">

{#snippet invoicedLink(inv)}
  {#if inv}
    <a class="badge-invoiced" href={`#/invoices/${inv.id}`} use:link
       title="Billed on this invoice">Invoiced · {inv.number}</a>
  {/if}
{/snippet}

<JobHeader {job} {contact} {onStatusChange} />

{#if job.status === 'draft' && job.latest_change_request}
  <div class="change-request-banner">
    <strong>Customer requested changes:</strong>
    <span class="cr-text">{job.latest_change_request.text || '(no comment provided)'}</span>
    <span class="cr-hint">Edit the revised estimate below, then re-send it.</span>
  </div>
{/if}

<!-- DESCRIPTION + DELIVERABLES + HISTORY (fixed height) -->
<div class="midband">
  <div class="panel description-panel">
    <div class="panel-head">Description</div>
    <div class="panel-scroll">
      <p class="preserve-breaks"><LinkifiedText text={job.description || 'No description.'} /></p>
    </div>
  </div>
  <DeliverablesSection jobId={job.job_id} canManage={job.can_manage} />
  <div class="panel history-panel">
    <div class="panel-scroll history-scroll-host">
      <EmailPanel {emails} />
    </div>
  </div>
</div>

<!-- HORIZONTAL ACCORDION -->
<div class="accordion">
  <!-- Estimate (merged Plan + Client View pillar) -->
  {#if activeSection !== 'estimate'}
    <div class="pillar pillar-est"
         role="button" tabindex="0"
         onclick={() => openSection('estimate')}
         onkeydown={(e) => e.key === 'Enter' && openSection('estimate')}>
      <span class="label-v">Estimate</span>
      <span class="pillar-count">{worksheetList.length + versionTimeline.length}</span>
    </div>
  {:else}
    <div class="open open-est">
      <div class="top-bar top-bar-est">
        <span class="top-bar-title">ESTIMATE</span>
        <span class="top-bar-actions">
          {#if canStartEstimate}
            <button type="button" onclick={startEstimate} disabled={startingEstimate}>
              {startingEstimate ? 'Starting…' : 'Start Estimate'}
            </button>
          {/if}
          {#if currentWorksheet && estimateView === 'plan'}
            <a href="#/worksheets/{currentWorksheet.est_worksheet_id}">Open Plan →</a>
          {:else if estimateView === 'client-view' && displayedVersion?.kind === 'co'}
            <a href="#/change-orders/{displayedVersion.co.change_order_id}">Open →</a>
          {:else if estimateView === 'client-view' && displayedEstimate}
            <a href="#/estimates/{displayedEstimate.estimate_id}">Open →</a>
          {/if}
          {#if canManageJobs && job.status === 'on_hold' && !hasLiveChangeOrder}
            <button type="button" onclick={createChangeOrder} disabled={creatingCo}>
              {creatingCo ? 'Creating…' : '+ New change order'}
            </button>
          {/if}
        </span>
      </div>

      <!-- Plan / Client View toggle -->
      <div class="est-view-toggle">
        <button
          type="button"
          aria-pressed={estimateView === 'plan'}
          class:active={estimateView === 'plan'}
          onclick={() => { estimateView = 'plan'; }}
        >Plan</button>
        <button
          type="button"
          aria-pressed={estimateView === 'client-view'}
          class:active={estimateView === 'client-view'}
          onclick={() => { estimateView = 'client-view'; }}
        >Client View</button>
      </div>

      {#if estimateView === 'plan'}
        <!-- Plan (worksheet) side -->
        <div class="body">
          {#if !currentWorksheet}
            <p class="empty-msg">No plan for this job yet.</p>
          {:else}
            {@const wsTasks = (displayedWorksheet?.tasks || []).slice().sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0))}
            {@const taskless = displayedWorksheet?.taskless_materials || []}
            {#if wsTasks.length === 0 && taskless.length === 0}
              <p class="empty-msg">Plan has no tasks or materials.</p>
            {:else}
              <table class="ws-readonly">
                <colgroup>
                  <col>
                  <col class="col-qty">
                  <col class="col-units">
                  <col class="col-money">
                  <col class="col-money">
                </colgroup>
                <thead>
                  <tr>
                    <th>Name</th>
                    <th class="text-right">Qty</th>
                    <th>Units</th>
                    <th class="text-right">Price</th>
                    <th class="text-right">Ext</th>
                  </tr>
                </thead>
                <tbody>
                  {#each wsTasks as task}
                    <tr class="task-row">
                      <td class="name">{task.name}{#if task.description}<span class="dim"> — {task.description}</span>{/if}</td>
                      <td class="text-right">{task.est_qty ?? '—'}</td>
                      <td>{task.units || ''}</td>
                      <td class="text-right">{fmt(unitPrice(task))}</td>
                      <td class="text-right">{fmt(task.amount)}</td>
                    </tr>
                    {#each (task.plan_materials || []) as mat}
                      <tr class="material-row">
                        <td class="indent preserve-breaks"><span class="marker">●</span> {mat.description || '(no description)'}</td>
                        <td class="text-right">{mat.quantity ?? '—'}</td>
                        <td>{mat.units || ''}</td>
                        <td class="text-right">{fmt(mat.sell_price)}</td>
                        <td class="text-right">{fmt(materialTotal(mat))}</td>
                      </tr>
                    {/each}
                  {/each}
                </tbody>
              </table>

              {#if taskless.length > 0}
                <div class="ml-heading">Materials not assigned to a task</div>
                <table class="ml-readonly">
                  <colgroup>
                    <col>
                    <col class="col-qty">
                    <col class="col-units">
                    <col class="col-money">
                    <col class="col-money">
                  </colgroup>
                  <tbody>
                    {#each taskless as mat}
                      <tr>
                        <td class="preserve-breaks">{mat.description || '(no description)'}</td>
                        <td class="text-right">{mat.quantity ?? '—'}</td>
                        <td>{mat.units || ''}</td>
                        <td class="text-right">{fmt(mat.sell_price)}</td>
                        <td class="text-right">{fmt(materialTotal(mat))}</td>
                      </tr>
                    {/each}
                  </tbody>
                </table>
              {/if}

              <div class="ws-total">
                <span class="ws-total-label">Total</span>
                <span class="ws-total-value">{fmt(worksheetGrandTotal)}</span>
              </div>
            {/if}
          {/if}
        </div>
      {:else}
        <!-- Client View (estimate + COs) side -->
        {#if versionTimeline.length > 1}
          <div class="est-tabs">
            {#each versionTimeline as ver}
              {#if ver.kind === 'estimate'}
                <button
                  type="button"
                  class="est-tab"
                  class:active={ver.key === (displayedVersion?.key)}
                  onclick={() => { selectedVersionKey = ver.key; }}
              >
                {ver.est.estimate_number} v{ver.est.version} <span class="est-tab-status">({estimateDisplayStatus(ver.est)})</span>
              </button>
            {:else}
              <a
                class="est-tab est-tab-co"
                href={`/change-orders/${ver.co.change_order_id}`}
                use:link
              >
                {ver.co.change_order_number || `CO #${ver.co.change_order_id}`} <span class="est-tab-status">({changeOrderDisplayStatus(ver.co, changeOrders)})</span>
              </a>
            {/if}
          {/each}
        </div>
        {/if}
        <div class="body">
          {#if displayedVersion?.kind === 'co'}
            <!-- CO effective agreement view (Option A): base estimate lines with CO deltas applied -->
            {#if coEffectiveLines.length > 0}
              <table class="est-table">
                <colgroup>
                  <col class="col-num">
                  <col>
                  <col class="col-qty">
                  <col class="col-units">
                  <col class="col-money">
                  <col class="col-money">
                </colgroup>
                <thead><tr>
                  <th>#</th><th>Description</th>
                  <th class="text-right">Qty</th><th>Units</th><th class="text-right">Price</th><th class="text-right">Total</th>
                </tr></thead>
                <tbody>
                  {#each coEffectiveLines as li}
                    <tr class:co-line-changed={li.coTouched === 'changed'} class:co-line-added={li.coTouched === 'added'}>
                      <td>{li.line_number}</td>
                      <td>
                        {li.description}
                        {#if li.coTouched}
                          <span class="co-tag">{coCountOnEstimate > 1 ? `CO-${li.coOrdinal}` : 'CO'}</span>
                        {/if}
                      </td>
                      <td class="text-right">{li.qty}</td>
                      <td>{li.units || 'none'}</td>
                      <td class="text-right">${Number(li.price).toFixed(2)}</td>
                      <td class="text-right">${(Number(li.qty) * Number(li.price)).toFixed(2)}</td>
                    </tr>
                  {/each}
                </tbody>
              </table>
              <div class="est-footer">
                <div class="est-meta">
                  <span class="meta-bit">
                    <span class="meta-label">Change Order</span>
                    <span class="meta-value">{displayedVersion.co.change_order_number || `CO #${displayedVersion.co.change_order_id}`}</span>
                  </span>
                  <span class="pill pill-co-{displayedVersion.co.status}">{displayedVersion.co.status}</span>
                </div>
                <div class="est-totals">
                  <div class="t-label">Total</div>
                  <div class="t-value grand">${coEffectiveTotal.toFixed(2)}</div>
                </div>
              </div>
            {:else}
              <p class="empty-msg">No effective lines (CO has no base estimate or all lines removed).</p>
            {/if}
          {:else if displayedEstimate?.line_items?.length > 0}
            <table class="est-table">
              <colgroup>
                <col class="col-num">
                <col>
                <col class="col-qty">
                <col class="col-units">
                <col class="col-money">
                <col class="col-money">
              </colgroup>
              <thead><tr>
                <th>#</th><th>Description</th>
                <th class="text-right">Qty</th><th>Units</th><th class="text-right">Price</th><th class="text-right">Total</th>
              </tr></thead>
              <tbody>
                {#each displayedEstimate.line_items as li}
                  <tr>
                    <td>{li.line_number}</td>
                    <td>{li.description}</td>
                    <td class="text-right">{li.qty}</td>
                    <td>{li.units || 'none'}</td>
                    <td class="text-right">${Number(li.price).toFixed(2)}</td>
                    <td class="text-right">${(Number(li.qty) * Number(li.price)).toFixed(2)}</td>
                  </tr>
                {/each}
              </tbody>
            </table>
            <div class="est-footer">
              <div class="est-meta">
                {#if displayedEstimate.sent_date}
                  <span class="meta-bit"><span class="meta-label">Sent</span> <span class="meta-value">{fmtDate(displayedEstimate.sent_date)}</span></span>
                {/if}
                {#if displayedEstimate.closed_date && displayedEstimate.status === 'accepted'}
                  <span class="meta-bit"><span class="meta-label">Accepted</span> <span class="meta-value">{fmtDate(displayedEstimate.closed_date)}</span></span>
                {:else if displayedEstimate.closed_date && displayedEstimate.status === 'rejected'}
                  <span class="meta-bit"><span class="meta-label">Rejected</span> <span class="meta-value">{fmtDate(displayedEstimate.closed_date)}</span></span>
                {:else if displayedEstimate.closed_date && displayedEstimate.status === 'superseded'}
                  <span class="meta-bit"><span class="meta-label">Superseded</span> <span class="meta-value">{fmtDate(displayedEstimate.closed_date)}</span></span>
                {:else if displayedEstimate.closed_date && displayedEstimate.status === 'expired'}
                  <span class="meta-bit"><span class="meta-label">Expired</span> <span class="meta-value">{fmtDate(displayedEstimate.closed_date)}</span></span>
                {:else if !displayedEstimate.sent_date && displayedEstimate.created_date}
                  <span class="meta-bit"><span class="meta-label">Started</span> <span class="meta-value">{fmtDate(displayedEstimate.created_date)}</span></span>
                {/if}
              </div>
              <div class="est-totals">
                <div class="t-label">Total</div>
                <div class="t-value grand">
                  ${displayedEstimate.line_items.reduce((sum, li) => sum + Number(li.qty) * Number(li.price), 0).toFixed(2)}
                </div>
              </div>
            </div>
          {:else if displayedEstimate}
            <p class="empty-msg">Client View has no line items.</p>
          {:else}
            <p class="empty-msg">No Client View yet.</p>
          {/if}
        </div>
      {/if}
    </div>
  {/if}

  <!-- Tasks & Materials -->
  {#if activeSection !== 'tasks_materials'}
    <div class="pillar pillar-tasks"
         role="button" tabindex="0"
         onclick={() => openSection('tasks_materials')}
         onkeydown={(e) => e.key === 'Enter' && openSection('tasks_materials')}>
      <span class="label-v">Tasks &amp; Materials</span>
      <span class="pillar-count">{jobTasks.length + jobMaterials.length + looseExpenses.length}</span>
    </div>
  {:else}
    <div class="open open-tasks">
      <div class="top-bar top-bar-tasks">
        <span class="top-bar-title">
          TASKS &amp; MATERIALS · {jobTasks.length} task{jobTasks.length === 1 ? '' : 's'}, {jobMaterials.length} material{jobMaterials.length === 1 ? '' : 's'}{#if looseExpenses.length}, {looseExpenses.length} expense{looseExpenses.length === 1 ? '' : 's'}{/if}
        </span>
        <span class="top-bar-actions">
          <a href="#/jobs/{job.job_id}/tasklist">View task list →</a>
        </span>
      </div>
      <div class="body">
        {#if enriching && enrichedTasks.length === 0}
          <p class="empty-msg">Loading…</p>
        {:else if jobTasks.length === 0 && jobMaterials.length === 0 && looseExpenses.length === 0}
          <p class="empty-msg">No tasks, materials, or expenses yet.</p>
        {:else}
          <TaskTree
            tasks={enrichedTasks}
            jobMaterials={jobLevelMaterials}
            expenses={jobExpenses}
            readonly={true}
            canManage={job?.can_manage}
            onTaskClick={(t) => { window.location.hash = `/jobs/${job.job_id}/tasks/${t.task_id}`; }}
          />
        {/if}
      </div>
    </div>
  {/if}

  <!-- Invoices -->
  {#if activeSection !== 'invoices'}
    <div class="pillar pillar-inv"
         role="button" tabindex="0"
         onclick={() => openSection('invoices')}
         onkeydown={(e) => e.key === 'Enter' && openSection('invoices')}>
      <span class="label-v">Invoices</span>
      <span class="pillar-count">{invList.length}</span>
    </div>
  {:else}
    <div class="open open-inv">
      <div class="top-bar top-bar-inv">
        <span class="top-bar-title">
          INVOICES{#if invList.length} · {invList.length} invoice{invList.length === 1 ? '' : 's'} · {fmtMoney(totalBilled)} billed · {fmtMoney(totalPaid)} paid · {fmtMoney(totalOutstanding)} outstanding{:else} · None yet{/if}
        </span>
        <span class="top-bar-actions">
          {#if displayedInvoice}
            <a href="#/invoices/{displayedInvoice.invoice_id}">View Invoice</a>
          {/if}
          {#if canCreateInvoice}
            <button type="button" onclick={createInvoiceManual} disabled={creatingInvoice}>
              {creatingInvoice ? 'Creating…' : 'Create Invoice'}
            </button>
          {/if}
        </span>
      </div>
      {#if sortedInvoices.length > 1}
        <div class="inv-tabs">
          {#each sortedInvoices as inv}
            <button
              type="button"
              class="inv-tab"
              class:active={inv.invoice_id === displayedInvoice?.invoice_id}
              onclick={() => { selectedInvoiceId = inv.invoice_id; }}
            >
              {inv.invoice_number} <span class="inv-tab-status">({inv.status})</span>
            </button>
          {/each}
        </div>
      {/if}
      <div class="body">
        {#if displayedInvoice}
          {@const items = displayedInvoice.line_items || []}
          {#if items.length > 0}
            <table class="inv-readonly">
              <colgroup>
                <col class="col-num">
                <col>
                <col class="col-qty">
                <col class="col-units">
                <col class="col-money">
                <col class="col-money">
              </colgroup>
              <thead>
                <tr>
                  <th>#</th>
                  <th>Description</th>
                  <th class="text-right">Qty</th>
                  <th>Units</th>
                  <th class="text-right">Price</th>
                  <th class="text-right">Ext</th>
                </tr>
              </thead>
              <tbody>
                {#each items as li}
                  <tr>
                    <td>{li.line_number}</td>
                    <td class="preserve-breaks"><LinkifiedText text={li.description} /></td>
                    <td class="text-right">{li.qty}</td>
                    <td>{li.units || 'none'}</td>
                    <td class="text-right">{fmtMoney(li.price)}</td>
                    <td class="text-right">{fmtMoney(Number(li.qty) * Number(li.price))}</td>
                  </tr>
                {/each}
              </tbody>
            </table>
          {:else}
            <p class="empty-msg">Invoice has no line items.</p>
          {/if}
          {@const total = invoiceTotal(displayedInvoice)}
          {@const paid = invoicePaid(displayedInvoice)}
          {@const outstanding = total - paid}
          <div class="inv-footer">
            <div class="inv-meta">
              <a class="inv-link" href="#/invoices/{displayedInvoice.invoice_id}">{displayedInvoice.invoice_number}</a>
              <span class="pill pill-{displayedInvoice.status}">{displayedInvoice.status}</span>
              {#if displayedInvoice.sent_date}
                <span class="meta-bit"><span class="meta-label">Sent</span> <span class="meta-value">{fmtDate(displayedInvoice.sent_date)}</span></span>
              {/if}
              {#if displayedInvoice.due_date}
                <span class="meta-bit" class:late={displayedInvoice.is_late}>
                  <span class="meta-label">Due</span> <span class="meta-value">{fmtDate(displayedInvoice.due_date)}</span>
                </span>
              {/if}
              {#if displayedInvoice.closed_date}
                <span class="meta-bit"><span class="meta-label">Closed</span> <span class="meta-value">{fmtDate(displayedInvoice.closed_date)}</span></span>
              {/if}
            </div>
            <div class="inv-totals">
              <div class="t-label">Total</div>
              <div class="t-value">{fmtMoney(total)}</div>
              <div class="t-label paid">Paid</div>
              <div class="t-value paid">{fmtMoney(paid)}</div>
              <div class="t-label" class:out={outstanding > 0}>Outstanding</div>
              <div class="t-value grand" class:out={outstanding > 0}>{fmtMoney(outstanding)}</div>
            </div>
          </div>
        {:else}
          <p class="empty-msg">No invoices created for this job yet.</p>
        {/if}
      </div>
    </div>
  {/if}

  <!-- Shipments -->
  {#if activeSection !== 'shipments'}
    <div class="pillar pillar-ship"
         role="button" tabindex="0"
         onclick={() => openSection('shipments')}
         onkeydown={(e) => e.key === 'Enter' && openSection('shipments')}>
      <span class="label-v">Shipments</span>
      <span class="pillar-count">{shipmentCount}</span>
    </div>
  {:else}
    <div class="open open-ship">
      <div class="top-bar top-bar-ship">
        <span class="top-bar-title">
          SHIPMENTS{#if shipmentCount} · {shipmentCount}{:else} · None{/if}
        </span>
        <span class="top-bar-actions">
          <a use:link href={`/jobs/${job.job_id}/shipments`}>Manage shipments →</a>
        </span>
      </div>
      <div class="body">
        <ShipmentsPillar jobId={job.job_id} />
      </div>
    </div>
  {/if}

  <!-- Purchase Orders -->
  {#if activeSection !== 'pos'}
    <div class="pillar pillar-po"
         role="button" tabindex="0"
         onclick={() => openSection('pos')}
         onkeydown={(e) => e.key === 'Enter' && openSection('pos')}>
      <span class="label-v">POs</span>
      <span class="pillar-count">{poList.length}</span>
    </div>
  {:else}
    <div class="open open-po">
      <div class="top-bar top-bar-po">
        <span class="top-bar-title">
          PURCHASE ORDERS{#if poList.length} · {poList.length} order{poList.length === 1 ? '' : 's'} · {fmtMoney(totalCommitted)} committed{:else} · None{/if}
        </span>
        <span class="top-bar-actions">
          {#if displayedPo}
            <a href="#/purchase-orders/{displayedPo.po_id}">View Full PO</a>
          {/if}
          {#if canManageFinancials}
            <a href="#/purchase-orders/new?job={job.job_id}">Create PO</a>
          {/if}
        </span>
      </div>
      {#if sortedPOs.length > 1}
        <div class="po-tabs">
          {#each sortedPOs as po}
            <button
              type="button"
              class="po-tab"
              class:active={po.po_id === displayedPo?.po_id}
              onclick={() => { selectedPoId = po.po_id; }}
            >
              {po.po_number} <span class="po-tab-status">({po.status})</span>
            </button>
          {/each}
        </div>
      {/if}
      <div class="body">
        {#if displayedPo}
          {@const items = displayedPo.line_items || []}
          {#if items.length > 0}
            <table class="po-readonly">
              <colgroup>
                <col class="col-num">
                <col>
                <col class="col-qty">
                <col class="col-units">
                <col class="col-money">
                <col class="col-money">
              </colgroup>
              <thead>
                <tr>
                  <th>#</th>
                  <th>Description</th>
                  <th class="text-right">Qty</th>
                  <th>Units</th>
                  <th class="text-right">Price</th>
                  <th class="text-right">Ext</th>
                </tr>
              </thead>
              <tbody>
                {#each items as li}
                  <tr class:other-job={li.effective_job_id && li.effective_job_id !== job.job_id}>
                    <td>{li.line_number}</td>
                    <td>
                      <span class="preserve-breaks"><LinkifiedText text={li.description} /></span>
                      {#if li.effective_job_id && li.effective_job_id !== job.job_id}
                        <span class="other-job-label">(other job: {li.effective_job_number})</span>
                      {/if}
                    </td>
                    <td class="text-right">{li.qty}</td>
                    <td>{li.units || 'none'}</td>
                    <td class="text-right">{fmtMoney(li.price)}</td>
                    <td class="text-right">{fmtMoney(Number(li.qty) * Number(li.price))}</td>
                  </tr>
                {/each}
              </tbody>
            </table>
          {:else}
            <p class="empty-msg">PO has no line items.</p>
          {/if}
          {@const total = poTotal(displayedPo)}
          <div class="po-footer">
            <div class="po-meta">
              <a class="po-link" href="#/purchase-orders/{displayedPo.po_id}">{displayedPo.po_number}</a>
              <span class="pill pill-{displayedPo.status}">{(displayedPo.status || '').replace('_', ' ')}</span>
              {#if displayedPo.business_name}
                <span class="meta-bit"><span class="meta-label">Vendor</span> <span class="meta-value">{displayedPo.business_name}</span></span>
              {/if}
              {#if displayedPo.issued_date}
                <span class="meta-bit"><span class="meta-label">Issued</span> <span class="meta-value">{fmtDate(displayedPo.issued_date)}</span></span>
              {/if}
              {#if displayedPo.received_date}
                <span class="meta-bit"><span class="meta-label">Received</span> <span class="meta-value">{fmtDate(displayedPo.received_date)}</span></span>
              {/if}
              {#if displayedPo.cancel_date}
                <span class="meta-bit"><span class="meta-label">Cancelled</span> <span class="meta-value">{fmtDate(displayedPo.cancel_date)}</span></span>
              {/if}
            </div>
            <div class="po-totals">
              <div class="t-label">Total</div>
              <div class="t-value">{fmtMoney(total)}</div>
            </div>
          </div>
        {:else}
          <p class="empty-msg">No purchase orders for this job.</p>
        {/if}
      </div>
    </div>
  {/if}
</div>

</div>

<style>
  /* PAGE WRAPPER — full viewport, flex column so accordion fills remaining space */
  .job-detail-page {
    height: 100vh;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  .change-request-banner {
    background: #ffedd5;
    border: 1px solid #fdba74;
    color: #9a3412;
    padding: 8px 12px;
    font-size: 13px;
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    align-items: baseline;
  }
  .change-request-banner .cr-text { font-style: italic; }
  .change-request-banner .cr-hint { color: #c2410c; margin-left: auto; font-size: 12px; }

  /* HEADER */
  .job-header {
    background: #1f2937;
    color: #fff;
    padding: 14px 24px;
    display: grid;
    grid-template-columns: 1fr auto;
    gap: 24px;
    align-items: center;
    height: 110px;
    box-sizing: border-box;
    flex: 0 0 auto;
  }
  .titleblock { padding-left: 52px; min-width: 0; }
  .edit-link { font-size: 12px; font-weight: 400; opacity: 0.6; margin-left: 10px; color: #fff; text-decoration: none; }
  .edit-link:hover { opacity: 1; text-decoration: underline; }
  .customer-line { font-size: 13px; opacity: 0.85; margin: 2px 0 0; }
  .status-row { margin-top: 8px; display: flex; gap: 10px; align-items: center; font-size: 12px; }
  .status-badge {
    padding: 3px 10px; border-radius: 10px; font-size: 12px;
    font-weight: 600; text-transform: capitalize;
  }
  .status-select-wrapper { position: relative; display: inline-block; }
  .status-select {
    appearance: none; -webkit-appearance: none;
    padding: 3px 26px 3px 10px; border-radius: 10px;
    font-size: 12px; font-weight: 600; text-transform: capitalize;
    border: 2px solid transparent; cursor: pointer; outline: none;
    transition: border-color 0.15s ease;
  }
  .status-select:hover { border-color: rgba(0,0,0,0.15); }
  .status-select:focus { border-color: rgba(0,0,0,0.3); }
  .status-select-wrapper::after {
    content: '\25BE'; position: absolute; right: 9px; top: 50%;
    transform: translateY(-50%); font-size: 10px; pointer-events: none; opacity: 0.6;
  }
  .status-draft { background: #f3f4f6; color: #374151; }
  .status-submitted { background: #dbeafe; color: #1e40af; }
  .status-approved { background: #dcfce7; color: #166534; }
  .status-in_progress { background: #fef3c7; color: #92400e; }
  .status-work_complete { background: #e0e7ff; color: #3730a3; }
  .status-completed { background: #dbeafe; color: #1e40af; }
  .status-rejected { background: #fee2e2; color: #991b1b; }
  .status-cancelled { background: #fef3c7; color: #92400e; }
  .dates { opacity: 0.7; }
  .release-btn { font-size: 12px; padding: 3px 10px; margin-left: 4px; }

  /* P/L grid */
  .pl-grid {
    display: grid;
    grid-template-columns: repeat(4, auto);
    gap: 22px;
    background: rgba(255,255,255,0.06);
    padding: 10px 18px;
    border-radius: 8px;
    border: 1px solid rgba(255,255,255,0.08);
  }
  .pl-item { text-align: right; }
  .pl-label { font-size: 10px; text-transform: uppercase; letter-spacing: 0.6px; opacity: 0.65; }
  .pl-value { font-size: 18px; font-weight: 700; margin-top: 2px; font-variant-numeric: tabular-nums; }
  .pl-spent { color: #fca5a5; }
  .pl-billable { color: #fde68a; }
  .pl-invoiced { color: #86efac; }

  /* MIDBAND */
  .midband {
    display: grid;
    grid-template-columns: 1fr 1fr 320px;
    gap: 12px;
    padding: 12px 24px;
    background: #f8f9fa;
    border-bottom: 1px solid #e5e7eb;
    height: 200px;
    box-sizing: border-box;
    flex: 0 0 auto;
  }
  /* Let the 1fr columns shrink below their content's intrinsic width so a long
     unbreakable token (e.g. a pasted URL) wraps instead of shoving the
     Deliverables/History columns off-screen. */
  .midband > :global(*) { min-width: 0; }
  .panel {
    background: #fff;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
    padding: 12px;
    display: flex;
    flex-direction: column;
    min-height: 0;
  }
  .panel-head {
    font-size: 10px;
    text-transform: uppercase;
    color: #888;
    letter-spacing: 0.5px;
    margin-bottom: 6px;
    flex: 0 0 auto;
  }
  .panel-scroll { overflow-y: auto; flex: 1 1 auto; min-height: 0; }
  .description-panel p { margin: 0; line-height: 1.6; color: #333; font-size: 14px; }
  /* Let the inner panel's scroll relax inside our fixed-height panel */
  .history-scroll-host :global(h3) { margin-top: 0; font-size: 14px; }
  .history-scroll-host :global(.email-scroll),
  .history-scroll-host :global(.history-scroll) { max-height: none; }

  /* ACCORDION */
  .accordion {
    display: flex;
    border-top: 1px solid #e5e7eb;
    flex: 1 1 auto;
    /* Header is 110px, midband 200px = 310px taken; the rest is ours. */
    min-height: calc(100vh - 310px);
  }
  .pillar {
    width: 44px;
    flex: 0 0 44px;
    color: #fff;
    display: flex;
    flex-direction: column;
    align-items: center;
    padding-top: 16px;
    gap: 8px;
    box-sizing: border-box;
    border-right: 1px solid #fff;
    cursor: pointer;
  }
  .pillar:hover { filter: brightness(1.08); }
  .pillar .label-v {
    writing-mode: vertical-rl;
    transform: rotate(180deg);
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.6px;
    text-transform: capitalize;
    white-space: nowrap;
  }
  .pillar .pillar-count {
    writing-mode: horizontal-tb;
    font-size: 11px;
    font-weight: 600;
    opacity: 0.85;
    font-variant-numeric: tabular-nums;
  }
  .pillar-est   { background: #4f46e5; }
  .pillar-tasks { background: #b45309; }
  .pillar-mat   { background: #ca8a04; }
  .pillar-inv   { background: #15803d; }
  .pillar-ship  { background: #0369a1; }
  .pillar-po    { background: #475569; }

  .open {
    flex: 1 1 auto;
    display: flex;
    flex-direction: column;
    min-width: 0;
    border-right: 1px solid #fff;
  }
  .top-bar {
    color: #fff;
    padding: 8px 16px;
    font-size: 13px;
    font-weight: 600;
    letter-spacing: 0.4px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
  }
  .top-bar-est   { background: #4f46e5; }
  .top-bar-tasks { background: #b45309; }
  .top-bar-mat   { background: #ca8a04; }
  .top-bar-inv   { background: #15803d; }
  .top-bar-ship  { background: #0369a1; }
  .top-bar-po    { background: #475569; }
  .top-bar-title { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .top-bar-actions { display: flex; gap: 8px; align-items: center; flex-shrink: 0; }
  .top-bar-actions a {
    font-size: 12px; font-weight: 500;
    padding: 3px 10px; border-radius: 4px;
    background: rgba(255,255,255,0.15); color: #fff;
    text-decoration: none;
  }
  .top-bar-actions a:hover { background: rgba(255,255,255,0.28); }
  .top-bar-actions button {
    font-size: 12px; padding: 3px 10px;
  }

  .body {
    flex: 1;
    background: #fff;
    overflow-y: auto;
    padding: 0;
  }

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
  .pill { padding: 2px 10px; border-radius: 10px; font-size: 12px; font-weight: 500; text-transform: capitalize; }
  .pill-complete { background: #e0f2fe; color: #0369a1; }
  .pill-in_progress { background: #fef3c7; color: #92400e; }
  .pill-pending { background: #f3e8ff; color: #7c3aed; }
  .pill-draft { background: #f3f4f6; color: #6b7280; }
  .pill-final { background: #e0e7ff; color: #4338ca; }
  .pill-blocked { background: #fee2e2; color: #991b1b; }
  .pill-cancelled { background: #fecaca; color: #991b1b; }
  .pill-paid { background: #dcfce7; color: #166534; }
  .pill-partly-paid { background: #fef3c7; color: #92400e; }
  .pill-defaulted { background: #fee2e2; color: #991b1b; }
  .pill-superseded { background: #f3f4f6; color: #6b7280; }
  .pill-accepted { background: #dcfce7; color: #166534; }
  .pill-open { background: #dbeafe; color: #1e40af; }
  .pill-active { background: #dcfce7; color: #166534; }
  .pill-received { background: #e0f2fe; color: #0369a1; }
  .pill-issued { background: #dbeafe; color: #1e40af; }
  .pill-consumed { background: #d1fae5; color: #065f46; }
  .pill-na { background: #f3f4f6; color: #6b7280; }

  /* Worksheet read-only view */
  .ws-tabs {
    background: #ccfbf1; padding: 6px 16px; border-bottom: 1px solid #99f6e4;
    display: flex; gap: 4px; font-size: 12px; flex: 0 0 auto;
  }
  .ws-tab {
    padding: 4px 12px; border-radius: 8px; cursor: pointer;
    color: #115e59; background: transparent; border: none; font-size: 12px;
  }
  .ws-tab:hover { background: rgba(255,255,255,0.5); }
  .ws-tab.active { background: #99f6e4; font-weight: 600; }
  .ws-tab-status { opacity: 0.7; font-weight: 400; margin-left: 2px; }

  .ws-readonly { width: 100%; border-collapse: collapse; font-size: 13px; table-layout: fixed; }
  .ws-readonly th {
    padding: 8px 14px; text-align: left; background: #f0fdfa; color: #115e59;
    font-weight: 600; border-bottom: 1px solid #ccfbf1;
  }
  .ws-readonly td {
    padding: 6px 14px; vertical-align: top; border-bottom: 1px solid #f0fdfa;
  }
  .ws-readonly col.col-qty { width: 70px; }
  .ws-readonly col.col-units { width: 70px; }
  .ws-readonly col.col-money { width: 110px; }
  .ws-readonly .task-row td { background: #fff; }
  .ws-readonly .task-row .name { font-weight: 600; }
  .ws-readonly .material-row td { background: #f2fcfa; }
  .ws-readonly .indent { padding-left: 32px; }
  .ws-readonly .marker { color: #aaa; font-size: 8px; margin-right: 6px; }
  .ws-readonly .dim { color: #888; font-weight: 400; font-size: 12px; }
  .ws-readonly .text-right { font-variant-numeric: tabular-nums; }
  .ws-total {
    display: flex; justify-content: flex-end; align-items: baseline;
    padding: 10px 14px; background: #ecfdf5; border-top: 2px solid #99f6e4;
    font-weight: 700; font-size: 14px;
  }
  .ws-total-label { margin-right: 12px; }
  .ws-total-value {
    width: 110px; text-align: right; font-variant-numeric: tabular-nums;
  }

  .ml-heading {
    margin: 0; padding: 4px 14px;
    font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; color: #115e59;
    background: #ccfbf1; font-weight: 600; line-height: 1.4;
  }
  .ml-readonly { width: 100%; border-collapse: collapse; font-size: 13px; table-layout: fixed; }
  .ml-readonly td {
    padding: 6px 14px; vertical-align: top; background: #f2fcfa;
    border-bottom: 1px solid #ccfbf1;
  }
  .ml-readonly col.col-qty { width: 70px; }
  .ml-readonly col.col-units { width: 70px; }
  .ml-readonly col.col-money { width: 110px; }
  .ml-readonly .text-right { font-variant-numeric: tabular-nums; }

  /* Plan / Client View toggle */
  .est-view-toggle {
    display: flex;
    gap: 0;
    background: #ddd6fe;
    padding: 6px 16px;
    border-bottom: 1px solid #c4b5fd;
    flex: 0 0 auto;
  }
  .est-view-toggle button {
    padding: 4px 14px;
    border: 1px solid #c4b5fd;
    background: transparent;
    color: #3730a3;
    font-size: 12px;
    font-weight: 500;
    cursor: pointer;
    border-radius: 0;
  }
  .est-view-toggle button:first-child { border-radius: 6px 0 0 6px; }
  .est-view-toggle button:last-child  { border-radius: 0 6px 6px 0; margin-left: -1px; }
  .est-view-toggle button.active,
  .est-view-toggle button[aria-pressed="true"] {
    background: #c4b5fd;
    font-weight: 700;
  }

  /* Estimate tabs */
  .est-tabs {
    background: #ddd6fe; padding: 6px 16px; border-bottom: 1px solid #c4b5fd;
    display: flex; gap: 4px; font-size: 12px; flex: 0 0 auto;
  }
  .est-tab {
    padding: 4px 12px; border-radius: 8px; cursor: pointer;
    color: #3730a3; background: transparent; border: none; font-size: 12px;
  }
  .est-tab:hover { background: rgba(255,255,255,0.5); }
  .est-tab.active { background: #c4b5fd; font-weight: 600; }
  .est-tab-status { opacity: 0.7; font-weight: 400; margin-left: 2px; }

  /* Estimate table */
  .est-table { table-layout: fixed; }
  .est-table thead { background: #ddd6fe; }
  .est-table thead th { color: #3730a3; }
  .est-table tbody tr { background: #eef2ff; }
  .est-table tbody tr:nth-child(even) { background: #e8e5ff; }
  .est-table tbody tr + tr { border-top: 1px solid #ddd6fe; }
  .est-table col.col-num { width: 50px; }
  .est-table col.col-qty { width: 70px; }
  .est-table col.col-units { width: 70px; }
  .est-table col.col-money { width: 110px; }

  /* Tasks (work order) table */
  .wo-table { table-layout: fixed; }
  .wo-table thead { background: #fde68a; }
  .wo-table thead th { color: #78350f; }
  .wo-table tbody tr { background: #fffbeb; }
  .wo-table tbody tr:nth-child(even) { background: #fef3c7; }
  .wo-table tbody tr + tr { border-top: 1px solid #fde68a; }
  .wo-table .row-active { background: #fde68a; }
  .wo-table col.col-assigned { width: 130px; }
  .wo-table col.col-status { width: 130px; }
  .wo-table col.col-time { width: 240px; }
  .time-cell { vertical-align: middle; }
  .time-track {
    width: 100%; height: 7px; background: rgba(0, 0, 0, 0.08);
    border-radius: 4px; overflow: hidden;
  }
  .time-fill { height: 100%; transition: width 0.2s ease; }
  .time-fill.under { background: #16a34a; }
  .time-fill.over { background: #dc2626; }
  .time-text {
    font-size: 11px; color: #555; margin-top: 3px;
    font-variant-numeric: tabular-nums;
  }
  .time-text.over { color: #b91c1c; }
  .time-delta { color: #b91c1c; }
  .time-dim { color: #888; }

  /* Invoice tabs */
  .inv-tabs {
    background: #bbf7d0; padding: 6px 16px; border-bottom: 1px solid #86efac;
    display: flex; gap: 4px; font-size: 12px; flex: 0 0 auto;
  }
  .inv-tab {
    padding: 4px 12px; border-radius: 8px; cursor: pointer;
    color: #14532d; background: transparent; border: none; font-size: 12px;
  }
  .inv-tab:hover { background: rgba(255,255,255,0.5); }
  .inv-tab.active { background: #86efac; font-weight: 600; }
  .inv-tab-status { opacity: 0.7; font-weight: 400; margin-left: 2px; }

  /* Invoice read-only line items */
  .inv-readonly { width: 100%; border-collapse: collapse; font-size: 13px; table-layout: fixed; }
  .inv-readonly col.col-num { width: 50px; }
  .inv-readonly col.col-qty { width: 70px; }
  .inv-readonly col.col-units { width: 70px; }
  .inv-readonly col.col-money { width: 110px; }
  .inv-readonly th {
    padding: 8px 14px; text-align: left; background: #dcfce7; color: #14532d;
    font-weight: 600; border-bottom: 1px solid #bbf7d0;
  }
  .inv-readonly td {
    padding: 6px 14px; vertical-align: top; background: #f0fdf4;
    border-bottom: 1px solid #dcfce7;
  }
  .inv-readonly tr:nth-child(even) td { background: #dcfce7; }
  .inv-readonly .text-right { font-variant-numeric: tabular-nums; }

  /* Invoice / Estimate footer (meta + totals combined) */
  .inv-footer, .est-footer {
    display: grid; grid-template-columns: 1fr auto; gap: 24px;
    border-top: 2px solid #86efac;
    padding: 12px 16px; font-size: 13px;
  }
  .inv-footer { background: #ecfdf5; }
  .est-footer { background: #eff6ff; border-top-color: #93c5fd; }
  .inv-meta, .est-meta {
    display: flex; gap: 14px; align-items: center; flex-wrap: wrap;
  }
  .est-totals { display: grid; grid-template-columns: auto 110px; column-gap: 12px; row-gap: 2px; }
  .est-totals .t-label { text-align: right; color: #1e3a8a; font-size: 12px; }
  .est-totals .t-value { text-align: right; font-weight: 700; font-variant-numeric: tabular-nums; }
  .est-totals .t-value.grand { font-size: 15px; }
  .inv-link { font-weight: 600; color: #14532d; text-decoration: none; }
  .inv-link:hover { text-decoration: underline; }
  .meta-bit { color: #14532d; font-size: 12px; }
  .meta-bit .meta-label {
    color: #888; font-size: 11px; text-transform: uppercase; letter-spacing: .4px;
  }
  .meta-bit .meta-value { font-weight: 600; font-variant-numeric: tabular-nums; }
  .meta-bit.late .meta-value { color: #b91c1c; }
  .meta-bit.late .meta-label { color: #b91c1c; }

  .inv-totals { display: grid; grid-template-columns: auto 110px; column-gap: 12px; row-gap: 2px; }
  .inv-totals .t-label { text-align: right; color: #14532d; font-size: 12px; }
  .inv-totals .t-value { text-align: right; font-weight: 700; font-variant-numeric: tabular-nums; }
  .inv-totals .t-label.paid { color: #166534; }
  .inv-totals .t-value.paid { color: #166534; }
  .inv-totals .t-value.out { color: #b91c1c; }
  .inv-totals .t-label.out { color: #b91c1c; }
  .inv-totals .t-value.grand { font-size: 15px; }

  /* PO tabs */
  .po-tabs {
    background: #e2e8f0; padding: 6px 16px; border-bottom: 1px solid #cbd5e1;
    display: flex; gap: 4px; font-size: 12px; flex: 0 0 auto;
  }
  .po-tab {
    padding: 4px 12px; border-radius: 8px; cursor: pointer;
    color: #334155; background: transparent; border: none; font-size: 12px;
  }
  .po-tab:hover { background: rgba(255,255,255,0.5); }
  .po-tab.active { background: #cbd5e1; font-weight: 600; }
  .po-tab-status { opacity: 0.7; font-weight: 400; margin-left: 2px; }

  /* PO read-only line items */
  .po-readonly { width: 100%; border-collapse: collapse; font-size: 13px; table-layout: fixed; }
  .po-readonly col.col-num { width: 50px; }
  .po-readonly col.col-qty { width: 70px; }
  .po-readonly col.col-units { width: 70px; }
  .po-readonly col.col-money { width: 110px; }
  .po-readonly th {
    padding: 8px 14px; text-align: left; background: #e2e8f0; color: #334155;
    font-weight: 600; border-bottom: 1px solid #cbd5e1;
  }
  .po-readonly td {
    padding: 6px 14px; vertical-align: top; background: #f8fafc;
    border-bottom: 1px solid #e2e8f0;
  }
  .po-readonly tr:nth-child(even) td { background: #f1f5f9; }
  .po-readonly tr.other-job td { opacity: 0.55; }
  .po-readonly .text-right { font-variant-numeric: tabular-nums; }

  /* PO footer (meta + total) */
  .po-footer {
    display: grid; grid-template-columns: 1fr auto; gap: 24px;
    background: #f1f5f9; border-top: 2px solid #cbd5e1;
    padding: 12px 16px; font-size: 13px;
  }
  .po-meta {
    display: flex; gap: 14px; align-items: center; flex-wrap: wrap;
  }
  .po-link { font-weight: 600; color: #334155; text-decoration: none; }
  .po-link:hover { text-decoration: underline; }
  .po-totals { display: grid; grid-template-columns: auto 110px; column-gap: 12px; row-gap: 2px; }
  .po-totals .t-label { text-align: right; color: #334155; font-size: 12px; }
  .po-totals .t-value { text-align: right; font-weight: 700; font-variant-numeric: tabular-nums; font-size: 15px; }

  /* PO statuses (partly/fully received) */
  .pill-partly_received { background: #fef3c7; color: #92400e; }
  .pill-received_in_full { background: #dcfce7; color: #166534; }

  /* Material table */
  .mat-table { table-layout: fixed; }
  .mat-table thead { background: #fde68a; }
  .mat-table thead th { color: #78350f; }
  .mat-table tbody tr { background: #fffbeb; }
  .mat-table tbody tr:nth-child(even) { background: #fef3c7; }
  .mat-table tbody tr + tr { border-top: 1px solid #fde68a; }
  .mat-table col.col-qty { width: 80px; }
  .mat-table col.col-on-order { width: 130px; }
  .mat-table col.col-units { width: 70px; }
  .mat-table col.col-money { width: 100px; }
  .mat-table .row-consumed td { opacity: 0.55; }
  .mat-table .badge-consumed {
    font-size: 10px; color: #555;
    margin-left: 6px; padding: 1px 6px;
    background: #e5e7eb; border-radius: 8px;
  }
  .mat-table .badge-paid {
    font-size: 10px; color: #166534;
    margin-left: 6px; padding: 1px 6px;
    background: #dcfce7; border-radius: 8px;
  }
  .badge-invoiced {
    font-size: 0.85em; text-decoration: none;
    border: 1px solid #888; border-radius: 3px;
    padding: 0 4px; margin-left: 6px;
  }
  .mat-table .add-po {
    font-size: 11px; color: #1e40af; margin-left: 8px;
  }
  .mat-table .add-po:hover { text-decoration: underline; }
  .mat-table .dim { color: #aaa; }
  .po-badge { font-size: 12px; color: #555; }

  /* PO other-job differentiation */
  .other-job { opacity: 0.5; }
  .other-job-label { font-size: 11px; color: #999; font-style: italic; margin-left: 4px; }

  /* Change-order status pills (used in CO tab footer and inline) */
  .pill-co-draft { background: #f3f4f6; color: #374151; }
  .pill-co-open { background: #fef3c7; color: #92400e; }
  .pill-co-accepted { background: #dcfce7; color: #166534; }
  .pill-co-rejected { background: #fee2e2; color: #991b1b; }

  /* CO tabs inside the est-tabs strip — anchor links with warmer tint to distinguish from est tabs */
  .est-tab.est-tab-co { color: #7c2d12; text-decoration: none; }
  .est-tab.est-tab-co:hover { background: #fed7aa; }

  /* CO effective-lines: lightly mark CO-touched rows */
  .est-table tbody tr.co-line-changed { background: #fff7ed; border-left: 3px solid #f97316; }
  .est-table tbody tr.co-line-added   { background: #f0fdf4; border-left: 3px solid #22c55e; }
  .co-tag {
    display: inline-block;
    font-size: 9px; font-weight: 700; letter-spacing: 0.3px;
    padding: 1px 4px; border-radius: 3px;
    background: #ffedd5; color: #9a3412;
    margin-left: 5px; vertical-align: middle;
    text-transform: uppercase;
  }
  .est-table tbody tr.co-line-added .co-tag {
    background: #dcfce7; color: #166534;
  }
</style>

<script>
  import { api, errorMessage } from '../../lib/api.js';
  import EstimateSourcePool from '../estimates/WizardSourcePool.svelte';
  import InvoiceSourcePool from '../invoices/WizardSourcePool.svelte';
  import AgreementAdjustmentsPanel from '../invoices/AgreementAdjustmentsPanel.svelte';
  import WizardLineItemCard from './WizardLineItemCard.svelte';
  import WizardActions from './WizardActions.svelte';
  import FormMessage from '../FormMessage.svelte';
  import { showError } from '../../stores/messages.js';
  import { createFlushRegistry } from '../../lib/wizardFlush.js';

  // Reconcile (wizard) mode lives inside the estimate/invoice document panels.
  // The two documents share one skeleton — a source pool of billable atoms on
  // the left, the document's line items on the right — with a handful of real
  // differences captured in CONFIGS below (pool shape/component, line-item
  // envelope, whether "Send all" refetches the pool, manual lines, agreement
  // adjustments). The panel owns lines↔reconcile mode toggling and persistence;
  // this component only owns the reconcile view and its mutations.
  let {
    docType,             // 'estimate' | 'invoice'
    docId,
    onChanged = () => {}, // called after a mutation so the panel's lines view refreshes
    onExit = () => {},    // called when the user clicks "Done" — panel flips to lines
  } = $props();

  // ── Per-document configuration ────────────────────────────────────────────
  // Values verified against the (now-retired) EstimateWizardPage/InvoiceWizardPage.
  const CONFIGS = {
    estimate: {
      apiBase: (id) => `/api/estimates/${id}`,
      routeSeg: 'estimate',
      idField: 'estimate_id',
      PoolComponent: EstimateSourcePool,
      poolHeading: 'Source pool (job atoms)',
      sendAllLabel: 'Send all to Estimate',
      sendAllTitle: 'Create one line item per available atom',
      conflictFallback: 'Some atoms were claimed by another estimate.',
      normalizeLineItems: (items) => items.results || items,
      // Estimate "Send all" only refreshes the doc + line items (no pool refetch).
      refetchPoolOnSendAll: false,
      hasManualLine: false,
      hasAgreementAdjustments: false,
      // Flat atom list: sourcePool.atoms[].
      reconcile: (pool, lineItems) => {
        const claimMap = new Map();
        for (const li of lineItems) {
          for (const src of li.sources || []) {
            claimMap.set(`${src.source_type}:${src.source_pk}`, { line_item_id: li.line_item_id });
          }
        }
        return {
          atoms: pool.atoms.map((a) => {
            if (a.state === 'claimed_by_other') return a;
            const key = `${a.type}:${a.id}`;
            if (claimMap.has(key)) {
              return { ...a, state: 'claimed_by_current', claiming_line_item_id: claimMap.get(key).line_item_id };
            }
            if (a.state === 'claimed_by_current') {
              return { ...a, state: 'available', claiming_line_item_id: null };
            }
            return a;
          }),
        };
      },
    },
    invoice: {
      apiBase: (id) => `/api/invoices/${id}`,
      routeSeg: 'invoice',
      idField: 'invoice_id',
      PoolComponent: InvoiceSourcePool,
      poolHeading: 'Tasks and Materials',
      sendAllLabel: 'Send all to Invoice',
      sendAllTitle: 'Create one line item per available atom',
      conflictFallback: 'Some atoms were claimed by another invoice.',
      normalizeLineItems: (items) => items,
      // Invoice "Send all" does a full reload including the source pool.
      refetchPoolOnSendAll: true,
      hasManualLine: true,
      hasAgreementAdjustments: true,
      // Nested task list: sourcePool.tasks[].atoms[]. claimed_by_other AND
      // not_billable are backend-decided independently of this invoice's line
      // items — never reconcile them to 'available'.
      reconcile: (pool, lineItems) => {
        const claimMap = new Map();
        for (const li of lineItems) {
          for (const src of li.sources || []) {
            claimMap.set(`${src.source_type}:${src.source_pk}`, {
              line_item_id: li.line_item_id,
              line_number: li.line_number,
            });
          }
        }
        for (const task of pool.tasks) {
          for (const atom of task.atoms) {
            if (atom.state === 'claimed_by_other' || atom.state === 'not_billable') continue;
            const key = `${atom.type}:${atom.id}`;
            if (claimMap.has(key)) {
              const claim = claimMap.get(key);
              atom.state = 'claimed_by_current';
              atom.claiming_line_item_id = claim.line_item_id;
              atom.claiming_line_number = claim.line_number;
            } else {
              atom.state = 'available';
              atom.claiming_line_item_id = null;
              atom.claiming_line_number = null;
            }
          }
        }
        return { ...pool };
      },
    },
  };

  // Reactive so a docId change (e.g. switching document versions via the panel
  // subnav while reconcile is open) repoints every endpoint and reloads.
  const cfg = $derived(CONFIGS[docType]);
  const apiBase = $derived(cfg.apiBase(docId));
  const PoolComponent = $derived(cfg.PoolComponent);

  const flushRegistry = createFlushRegistry();

  let doc = $state(null);
  let lineItems = $state([]);
  let sourcePool = $state(null);
  let selectedAtoms = $state([]);
  let loading = $state(true);
  let error = $state(null);
  // Set when an add bounced off the atoms-claimed 409 — the message under the
  // add controls then offers "Reload wizard" (the conflict's next step).
  let conflictError = $state('');

  const canAddHere = $derived(selectedAtoms.length > 0);

  async function addAtomsToLineItem(lineItemId) {
    conflictError = '';
    try {
      await api.post(`${apiBase}/line-items/${lineItemId}/add-atoms/`, { atoms: selectedAtoms });
      await reloadLineItems();
    } catch (e) {
      if (e.status === 409) {
        conflictError = errorMessage(e, cfg.conflictFallback);
      } else {
        showError(errorMessage(e, 'Failed to add atoms.'));
      }
    }
  }

  async function createNewLineItem() {
    conflictError = '';
    try {
      await api.post(`${apiBase}/line-items-from-atoms/`, { atoms: selectedAtoms });
      await reloadLineItems();
    } catch (e) {
      if (e.status === 409) {
        conflictError = errorMessage(e, cfg.conflictFallback);
      } else {
        showError(errorMessage(e, 'Failed to create line item.'));
      }
    }
  }

  function reloadFromConflict() {
    conflictError = '';
    loadAll();
  }

  async function addManualLineItem() {
    try {
      await api.post(`${apiBase}/line-items/`, {
        description: '', qty: '1', units: 'each', price: '0.00',
      });
      await reloadLineItems();
    } catch (e) {
      showError(errorMessage(e, 'Failed to add manual line item.'));
    }
  }

  // Initial (and conflict-reload) load — fetches everything including the pool.
  async function loadAll() {
    loading = true;
    error = null;
    try {
      const [d, items, pool] = await Promise.all([
        api.get(`${apiBase}/`),
        api.get(`${apiBase}/line-items/`),
        api.get(`${apiBase}/source-pool/`),
      ]);
      doc = d;
      lineItems = cfg.normalizeLineItems(items);
      sourcePool = pool;
      reconcileAtomStates();
    } catch (e) {
      error = e.message || 'Failed to load wizard';
    } finally {
      loading = false;
    }
  }

  async function sendAllAtoms() {
    try {
      await api.post(`${apiBase}/send-all-atoms/`);
      if (cfg.refetchPoolOnSendAll) {
        await loadAll();
      } else {
        await reloadLineItems();
      }
      onChanged();
    } catch (e) {
      showError(errorMessage(e, 'Could not send all atoms.'));
    }
  }

  // Post-action refresh — fetches the doc and line items, then reconciles atom
  // states in the existing source pool. Does NOT re-fetch the pool.
  async function reloadLineItems() {
    try {
      const [d, items] = await Promise.all([
        api.get(`${apiBase}/`),
        api.get(`${apiBase}/line-items/`),
      ]);
      doc = d;
      lineItems = cfg.normalizeLineItems(items);
      reconcileAtomStates();
      selectedAtoms = [];
      onChanged();
    } catch (e) {
      error = e.message || 'Failed to reload';
    }
  }

  function reconcileAtomStates() {
    if (!sourcePool) return;
    sourcePool = cfg.reconcile(sourcePool, lineItems);
  }

  // Initial load, and a fresh load whenever the target document changes. Only
  // docType/docId are tracked — loadAll's own writes don't feed back in.
  $effect(() => {
    void `${docType}:${docId}`;
    loadAll();
  });
</script>

{#if loading}
  <p>Loading…</p>
{:else if error}
  <p class="error">{error}</p>
{:else if doc}
  <div class="reconcile-grid">
    <div>
      <h3>{cfg.poolHeading}</h3>
      <p>
        <button type="button" onclick={sendAllAtoms} title={cfg.sendAllTitle}>{cfg.sendAllLabel}</button>
      </p>
      <PoolComponent {sourcePool} bind:selectedAtoms />
    </div>
    <div>
      <h3>Line items</h3>
      {#each lineItems as li (li.line_item_id)}
        <WizardLineItemCard
          lineItem={li}
          {apiBase}
          {canAddHere}
          onAddHere={addAtomsToLineItem}
          onchange={reloadLineItems}
          registerFlush={flushRegistry.register}
        />
      {/each}
      <div class="new-line-item">
        <em>New line item</em>
        <button
          onclick={createNewLineItem}
          disabled={!canAddHere}
          style="float: right;"
          title={canAddHere ? 'Create a new line item from selected atoms' : 'Select atoms first'}
        >Add Here</button>
      </div>
      <FormMessage error={conflictError}>
        <button type="button" onclick={reloadFromConflict}>Reload wizard</button>
      </FormMessage>
      {#if cfg.hasManualLine}
        <button type="button" onclick={addManualLineItem}>+ Manual</button>
      {/if}
      {#if cfg.hasAgreementAdjustments}
        <AgreementAdjustmentsPanel invoiceId={doc[cfg.idField]} onLineItemAdded={reloadLineItems} />
      {/if}
    </div>
  </div>

  <WizardActions
    {apiBase}
    detailRoute={doc.job ? `/jobs/${doc.job}/${cfg.routeSeg}/${docId}` : `/${cfg.routeSeg}s/${docId}`}
    discardRoute={doc.job ? `/jobs/${doc.job}` : '/'}
    onDone={async () => { await flushRegistry.flushAll(); onExit(); }}
  />
{/if}

<style>
  .error { color: #a8071a; }
  .reconcile-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
  .new-line-item {
    border: 1px dashed #aaa; padding: 8px; margin-bottom: 8px; color: #777;
  }
</style>

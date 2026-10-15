<!-- frontend/src/components/purchaseorders/OrderModal.svelte -->
<script>
  // THE Order modal (PO order flow §5.1): a PO header plus one line, which
  // creates nothing until Submit. Three sources — `material` (MaterialRow
  // "Order"), `item` (catalog "order"), `email` (email action panel "Create
  // new" PO, Task 9). The item is fixed for material/item sources; vendor
  // comes from the item's history (VendorPicker) and, once known, the
  // vendor's open drafts are offered as an explicit append-or-new choice.
  import { push } from 'svelte-spa-router';
  import { api } from '../../lib/api.js';
  import { triageError } from '../../lib/errorTriage.js';
  import { showError, showSuccess } from '../../stores/messages.js';
  import { orderPrefillQty } from '../../lib/materials.js';
  import Modal from '../Modal.svelte';
  import UnitsSelect from '../UnitsSelect.svelte';
  import FieldError from '../FieldError.svelte';
  import FormMessage from '../FormMessage.svelte';
  import VendorPicker from './VendorPicker.svelte';
  import { emailApi, resolveSenderToContact } from '../../lib/email.js';
  import SenderResolutionForm from '../email/SenderResolutionForm.svelte';
  import DuplicateContactNotice from '../contacts/DuplicateContactNotice.svelte';
  import DuplicateBusinessNotice from '../contacts/DuplicateBusinessNotice.svelte';
  import InventoryItemPicker from '../InventoryItemPicker.svelte';

  let {
    source,                 // 'material' | 'item' | 'email'
    material = null,        // source === 'material'
    item = null,            // source === 'item': { inventory_item_id, code, description? }
    prefillQty = '',        // source === 'item'
    emailRecordId = null,   // source === 'email'
    onDone = () => {},
    onCancel = () => {},
  } = $props();

  const itemId = $derived(source === 'material' ? material?.inventory_item : item?.inventory_item_id);

  let loading = $state(true);
  let itemDetail = $state(null);
  let history = $state(null);     // { vendors, earmarks, open_drafts }
  let categories = $state([]);

  let vendorId = $state(null);
  let vendorRow = $state(null);   // history row or business object
  let contacts = $state([]);
  let contactId = $state('');
  let requestedDate = $state('');
  let draftChoice = $state(null); // null | 'new' | po_id

  let form = $state({ qty: '', units: 'none', price: '', description: '', vendor_sku: '', accounting_category: '' });
  let skuTouched = $state(false);
  let base = { price: '' };      // the line's price before any vendor seeding
  let qtyError = $state('');
  let busy = $state(false);
  let formError = $state('');
  let fieldErrs = $state({});

  // Email source: the vendor is the sender's business, resolved on submit.
  let senderInfo = $state(null);
  let resolutionState = $state(null);
  let duplicateContact = $state(null);
  let duplicateBusiness = $state(null);
  let addLine = $state(false);
  let pickedItem = $state(null);
  const noticeShowing = $derived(!!duplicateContact || !!duplicateBusiness);

  const draftsForVendor = $derived(
    vendorId == null ? [] : (history?.open_drafts || []).filter((d) => d.business_id === vendorId));
  const appendTarget = $derived(
    draftChoice && draftChoice !== 'new' ? draftsForVendor.find((d) => d.po_id === draftChoice) : null);
  const choiceNeeded = $derived(draftsForVendor.length > 0 && draftChoice == null);
  const canSubmit = $derived(!busy && !loading &&
    (source === 'email' ? !!resolutionState : vendorId != null && !choiceNeeded));

  async function load() {
    loading = true;
    if (source === 'email') {
      try {
        const [info, cats] = await Promise.all([
          emailApi.senderInfo(emailRecordId),
          api.get('/api/accounting-categories/?page_size=100'),
        ]);
        senderInfo = info;
        categories = cats.results || cats;
      } catch (e) {
        const t = triageError(e);
        showError(t.overlay || t.message || 'Could not load email.');
        onCancel();
      } finally { loading = false; }
      return;
    }
    try {
      const excl = source === 'material' && material?.job ? `?exclude_job=${material.job}` : '';
      const [it, hist, cats] = await Promise.all([
        api.get(`/api/inventory/${itemId}/`),
        api.get(`/api/inventory/${itemId}/vendor-history/${excl}`),
        api.get('/api/accounting-categories/?page_size=100'),
      ]);
      itemDetail = it;
      categories = cats.results || cats;
      // Line defaults: the item's, then (material source) the material's.
      form.description = it.description || '';
      form.units = it.units || 'none';
      form.price = it.purchase_price ?? '';
      form.accounting_category = it.accounting_category ?? '';
      if (source === 'material') {
        form.qty = orderPrefillQty(material);
        form.description = material.description || form.description;
        form.units = material.units || form.units;
        if (material.unit_cost != null) form.price = material.unit_cost;
        if (material.accounting_category) form.accounting_category = material.accounting_category;
      } else {
        form.qty = prefillQty;
      }
      base = { price: form.price };
      history = hist;   // VendorPicker mounts now and preselects the first vendor
    } catch (e) {
      const t = triageError(e);
      showError(t.overlay || t.message || 'Could not load vendor history.');
      onCancel();
    } finally {
      loading = false;
    }
  }
  $effect(() => { void itemId; void emailRecordId; load(); });

  let vendorSeeded = false;   // the first handleVendor is the mount-time preselect

  async function handleVendor(row) {
    const initial = !vendorSeeded;
    vendorSeeded = true;
    vendorRow = row;
    draftChoice = null;
    fieldErrs = {};
    if (!row) { vendorId = null; contacts = []; contactId = ''; return; }
    vendorId = row.business_id;
    const isHistory = 'vendor_sku' in row;
    contacts = []; contactId = '';   // never post the previous vendor's contact
    if (isHistory) {
      if (!skuTouched) form.vendor_sku = row.vendor_sku || '';
      // The material's own cost survives the initial preselect (spec §5.1);
      // an explicit vendor change re-seeds from that vendor's last price.
      if (!(initial && source === 'material')) {
        form.price = row.last_price != null && row.last_price !== '' ? row.last_price : base.price;
      }
    } else {
      // A searched vendor has no history: back to the line's own defaults.
      if (!skuTouched) form.vendor_sku = '';
      form.price = base.price;
    }
    let contactData, biz;
    try {
      [contactData, biz] = await Promise.all([
        api.get(`/api/contacts/?business=${row.business_id}&page_size=100`),
        isHistory ? api.get(`/api/businesses/${row.business_id}/`) : Promise.resolve(row),
      ]);
    } catch (e) {
      const t = triageError(e);
      showError(t.overlay || t.message || 'Could not load vendor contacts.');
      return;
    }
    if (vendorId !== row.business_id) return;   // vendor changed while loading
    contacts = contactData.results || contactData;
    // Detail GET nests default_contact as an object; search rows carry a plain pk.
    const dc = biz?.default_contact;
    const dcId = dc != null && typeof dc === 'object' ? dc.contact_id : dc;
    const preferred = [isHistory ? row.contact_id : null, dcId, contacts[0]?.contact_id]
      .find((id) => id != null && contacts.some((c) => c.contact_id === id));
    contactId = preferred ?? '';
  }

  function linePayload() {
    return {
      qty: String(form.qty).trim(),
      units: form.units || 'none',
      price: form.price === '' || form.price == null ? null : String(form.price),
      description: form.description,
      vendor_sku: form.vendor_sku,
      accounting_category: form.accounting_category ? Number(form.accounting_category) : null,
    };
  }

  function handleItemPick(it) {
    pickedItem = it;
    if (!it) return;
    form.description = it.description || '';
    form.units = it.units || 'none';
    form.price = it.purchase_price ?? '';
    form.accounting_category = it.accounting_category ?? '';
  }

  function handleCancel() {
    if (noticeShowing) { duplicateContact = null; duplicateBusiness = null; }
    else onCancel();
  }

  async function submit(e) {
    e.preventDefault();
    qtyError = ''; formError = ''; fieldErrs = {};
    if (source === 'email') {
      duplicateContact = null; duplicateBusiness = null;
      if (addLine && (!String(form.qty).trim() || Number(form.qty) <= 0)) {
        qtyError = 'Enter a quantity greater than 0.';
        return;
      }
      if (!canSubmit) return;
      busy = true;
      try {
        const { contactId: cid, businessId } = await resolveSenderToContact(resolutionState);
        let vendorBusinessId = businessId;
        if (!vendorBusinessId) {
          const c = await api.get(`/api/contacts/${cid}/`);
          vendorBusinessId = c.business?.business_id ?? c.business ?? c.business_id ?? null;
        }
        if (!vendorBusinessId) {
          formError = 'A vendor business is required to create a PO. Pick or create one for this contact.';
          return;
        }
        const body = { vendor_business_id: vendorBusinessId, contact_id: cid, requested_date: requestedDate || null };
        if (addLine) body.line = { inventory_item: pickedItem?.inventory_item_id ?? null, ...linePayload() };
        const resp = await emailApi.createPo(emailRecordId, body);
        showSuccess('Added to', { href: `#/purchase-orders/${resp.po_id}`, label: resp.po_number });
        onDone(resp);
        push(`/purchase-orders/${resp.po_id}`);
      } catch (err) {
        if (err?.status === 409 && err.data?.code === 'duplicate_email') duplicateContact = err.data.existing_contact;
        else if (err?.status === 409 && err.data?.code === 'duplicate_business_name') duplicateBusiness = err.data.existing_business;
        else {
          const t = triageError(err);
          if (t.overlay) showError(t.overlay);
          else { formError = t.message; fieldErrs = { ...(t.fields.line || {}), ...t.fields }; }
        }
      } finally { busy = false; }
      return;
    }
    if (!String(form.qty).trim() || Number(form.qty) <= 0) {
      qtyError = 'Enter a quantity greater than 0.';
      return;
    }
    if (!canSubmit) return;
    const line = linePayload();
    const body = appendTarget
      ? { po_id: appendTarget.po_id, line }
      : { po: { business: vendorId, contact: contactId === '' ? null : Number(contactId),
                requested_date: requestedDate || null }, line };
    const url = source === 'material'
      ? `/api/materials/${material.material_id}/order/`
      : `/api/inventory/${itemId}/order/`;
    busy = true;
    try {
      const resp = await api.post(url, body);
      showSuccess('Added to', { href: `#/purchase-orders/${resp.po_id}`, label: resp.po_number });
      onDone(resp);
      push(`/purchase-orders/${resp.po_id}`);
    } catch (err) {
      const t = triageError(err);
      if (t.overlay) { showError(t.overlay); return; }
      formError = t.message;
      // Nested po.* / line.* bags plus the service's top-level `business`
      // (an inactive vendor) all land under their inputs.
      fieldErrs = { ...(t.fields.po || {}), ...(t.fields.line || {}), ...t.fields };
    } finally {
      busy = false;
    }
  }

  const submitLabel = $derived(appendTarget ? `Add to ${appendTarget.po_number}` : 'Create PO');
  const itemCode = $derived(itemDetail?.code?.startsWith('LOT-') ? '' : itemDetail?.code);
</script>

<!-- Native <form> owns Enter; the shell wires Escape. -->
<Modal open={true} onCancel={handleCancel} busy={busy} maxWidth="720px" label="Order">
  <h3 class="modal-title">{source === 'email' ? 'Order — new PO from email'
    : `Order — ${itemCode || itemDetail?.description || material?.description || ''}`}</h3>
  {#if loading}
    <p>Loading…</p>
  {:else if source === 'email' && senderInfo}
    {#if duplicateContact}
      <DuplicateContactNotice contact={duplicateContact}
        onViewExisting={() => { onCancel(); push(`/contacts/${duplicateContact.contact_id}`); }}
        onReactivate={async () => { await api.post(`/api/contacts/${duplicateContact.contact_id}/reactivate/`, {}); onCancel(); push(`/contacts/${duplicateContact.contact_id}`); }}
        onBack={() => { duplicateContact = null; }} />
    {:else if duplicateBusiness}
      <DuplicateBusinessNotice business={duplicateBusiness}
        onViewExisting={() => { onCancel(); push(`/businesses/${duplicateBusiness.business_id}`); }}
        onBack={() => { duplicateBusiness = null; }} />
    {/if}
    <div hidden={noticeShowing}>
      <form onsubmit={submit}>
        <SenderResolutionForm {senderInfo} bind:state={resolutionState} />
        <p>
          <label for="order-date"><strong>Requested date</strong></label><br>
          <input id="order-date" type="date" bind:value={requestedDate}>
        </p>
        <p><label><input type="checkbox" bind:checked={addLine}> Add a first line</label></p>
        {#if addLine}
          <fieldset class="line">
            <legend>Line</legend>
            <p>
              <strong>Item</strong><br>
              <InventoryItemPicker value={pickedItem?.inventory_item_id} selectedItem={pickedItem}
                onSelect={handleItemPick} params={{ is_active: true }} />
            </p>
            {@render lineFields()}
          </fieldset>
        {/if}
        <p class="dialog-actions">
          <button type="submit" disabled={!canSubmit}>Create PO</button>
          <button type="button" onclick={onCancel} disabled={busy}>Cancel</button>
        </p>
        <FormMessage error={formError} />
      </form>
    </div>
  {:else if history}
    <form onsubmit={submit}>
      <p>
        <label for="vendor-recent"><strong>Vendor *</strong></label><br>
        <VendorPicker vendors={history.vendors} onSelect={handleVendor} />
        <FieldError errors={fieldErrs} field="business" />
      </p>

      {#if !appendTarget}
        <p>
          <label for="order-contact"><strong>Contact</strong></label><br>
          <select id="order-contact" bind:value={contactId} disabled={vendorId == null}>
            <option value="">— none —</option>
            {#each contacts as c (c.contact_id)}
              <option value={c.contact_id}>{c.first_name} {c.last_name}</option>
            {/each}
          </select>
          <FieldError errors={fieldErrs} field="contact" />
        </p>
        <p>
          <label for="order-date"><strong>Requested date</strong></label><br>
          <input id="order-date" type="date" bind:value={requestedDate}>
          <FieldError errors={fieldErrs} field="requested_date" />
        </p>
      {/if}

      {#if draftsForVendor.length}
        <fieldset class="drafts">
          <legend>Open drafts for this vendor</legend>
          <label><input type="radio" bind:group={draftChoice} value="new"> Start a new PO</label>
          {#each draftsForVendor as d (d.po_id)}
            <label><input type="radio" bind:group={draftChoice} value={d.po_id}>
              Add to {d.po_number} ({d.line_count} {d.line_count === 1 ? 'line' : 'lines'})</label>
          {/each}
        </fieldset>
      {/if}

      <fieldset class="line">
        <legend>Line</legend>
        <p><strong>Item:</strong> {#if itemCode}<code class="mat-code">{itemCode}</code>{/if} {itemDetail.description}</p>
        {@render lineFields()}
      </fieldset>

      <p class="dialog-actions">
        <button type="submit" disabled={!canSubmit}>{submitLabel}</button>
        <button type="button" onclick={onCancel} disabled={busy}>Cancel</button>
      </p>
      <FormMessage error={formError} />
    </form>
  {/if}
</Modal>

{#snippet lineFields()}
  <p>
    <label for="order-qty"><strong>Qty *</strong></label><br>
    <input id="order-qty" type="number" step="any" min="0" bind:value={form.qty} oninput={() => qtyError = ''}>
    {#if qtyError}<span class="field-error">{qtyError}</span>{/if}
    <FieldError errors={fieldErrs} field="qty" />
    {#if history?.earmarks?.length}
      <br><small class="earmarks">Also needed: {history.earmarks.map((e) => `${e.job_number} ×${String(Number(e.quantity))}`).join(', ')}</small>
    {/if}
  </p>
  <p>
    <label for="order-units"><strong>Units</strong></label><br>
    <UnitsSelect id="order-units" bind:value={form.units} />
    <FieldError errors={fieldErrs} field="units" />
  </p>
  <p>
    <label for="order-price"><strong>Price</strong></label><br>
    <input id="order-price" type="number" step="0.01" min="0" bind:value={form.price}>
    <FieldError errors={fieldErrs} field="price" />
  </p>
  <p>
    <label for="order-description"><strong>Description</strong></label><br>
    <input id="order-description" type="text" bind:value={form.description}>
    <FieldError errors={fieldErrs} field="description" />
  </p>
  <p>
    <label for="order-sku"><strong>Vendor SKU</strong></label><br>
    <input id="order-sku" type="text" maxlength="100" bind:value={form.vendor_sku} oninput={() => skuTouched = true}>
    <FieldError errors={fieldErrs} field="vendor_sku" />
  </p>
  <p>
    <label for="order-category"><strong>Category</strong></label><br>
    <select id="order-category" bind:value={form.accounting_category}>
      <option value="">-- None --</option>
      {#each categories.filter((c) => !c.is_fallback) as cat (cat.id)}
        <option value={cat.id}>{cat.name}</option>
      {/each}
    </select>
    <FieldError errors={fieldErrs} field="accounting_category" />
  </p>
{/snippet}

<style>
  .modal-title { margin: 0 0 12px; font-size: 16px; }
  .drafts, .line { margin: 8px 0; }
  .drafts label { display: block; }
  .earmarks { color: #555; }
  .field-error { color: #c00; font-size: 0.9em; margin-left: 6px; }
  .mat-code { font-size: 11px; color: #374151; background: #f3f4f6; border: 1px solid #d1d5db; border-radius: 3px; padding: 0 4px; }
  .dialog-actions { display: flex; gap: 8px; margin-top: 12px; }
</style>

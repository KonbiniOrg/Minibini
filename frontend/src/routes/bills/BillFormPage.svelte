<script>
  import { api, errorMessage } from '../../lib/api.js';
  import { push, querystring } from 'svelte-spa-router';
  import BusinessPicker from '../../components/BusinessPicker.svelte';

  const { params = {} } = $props();
  const isEdit = $derived(!!params.id);

  let businesses = $state([]);
  let contactsForBusiness = $state([]);
  let vendorPos = $state([]);
  let loadingContacts = $state(false);
  let loading = $state(true);
  let errors = $state(null);
  let saving = $state(false);
  let billStatus = $state('draft');

  // Query param: ?po=ID pre-links a PO on create
  const initialParams = new URLSearchParams($querystring);
  const contextPoId = initialParams.get('po');

  // PO picker selection (create mode)
  let selectedPoId = $state(null);
  let selectedPoNumber = $state(null);

  // po_billing context fetched after PO is chosen
  let poBilling = $state(null);

  let form = $state({
    business: null,
    contact: '',
    vendor_invoice_number: '',
    due_date: '',
  });

  let lastFetchedBusiness = form.business;
  let pickedBusiness = $state(null);

  function getDefaultContactId(businessId) {
    if (pickedBusiness && String(pickedBusiness.business_id) === String(businessId)) {
      return pickedBusiness.default_contact || null;
    }
    const biz = businesses.find(b => String(b.business_id) === String(businessId));
    return biz?.default_contact || null;
  }

  async function fetchContactsAndAutoSelect(businessId, autoSelect) {
    if (!businessId) {
      contactsForBusiness = [];
      return;
    }
    loadingContacts = true;
    try {
      const data = await api.get(`/api/contacts/?business=${businessId}&page_size=100`);
      contactsForBusiness = data.results || [];
      if (autoSelect) {
        const defaultId = getDefaultContactId(businessId);
        if (defaultId && contactsForBusiness.some(c => c.contact_id === defaultId)) {
          form.contact = defaultId;
        } else if (contactsForBusiness.length > 0) {
          form.contact = contactsForBusiness[0].contact_id;
        } else {
          form.contact = '';
        }
      }
    } catch (e) {
      console.error('Failed to fetch contacts for business', businessId, e);
      contactsForBusiness = [];
    } finally {
      loadingContacts = false;
    }
  }

  async function fetchVendorPos(businessId) {
    if (!businessId) { vendorPos = []; return; }
    try {
      const data = await api.get(`/api/purchase-orders/?business=${businessId}&page_size=100`);
      vendorPos = data.results || [];
    } catch (e) {
      console.error('Failed to fetch POs for business', businessId, e);
      vendorPos = [];
    }
  }

  $effect(() => {
    const biz = form.business;
    if (biz === lastFetchedBusiness) return;
    lastFetchedBusiness = biz;
    fetchContactsAndAutoSelect(biz, true);
    selectedPoId = null;
    selectedPoNumber = null;
    poBilling = null;
    fetchVendorPos(biz);
  });

  async function fetchPoBilling(poId) {
    if (!poId) { poBilling = null; return; }
    try {
      const data = await api.get(`/api/bills/?purchase_order=${poId}&page_size=100`);
      const bills = data.results || data;
      const active = bills.filter(b => b.status !== 'cancelled');
      const poData = await api.get(`/api/purchase-orders/${poId}/`);
      poBilling = {
        other_bills: active.map(b => ({
          bill_id: b.bill_id,
          vendor_invoice_number: b.vendor_invoice_number,
          status: b.status,
          total: b.total,
        })),
        po_fully_billed: poData.is_fully_billed,
      };
    } catch (e) {
      console.error('Failed to fetch PO billing context', e);
      poBilling = null;
    }
  }

  async function load() {
    loading = true;
    errors = null;
    try {
      const bizData = await api.get('/api/businesses/?page_size=100');
      businesses = bizData.results || [];

      if (isEdit) {
        const bill = await api.get(`/api/bills/${params.id}/`);
        billStatus = bill.status;
        if (bill.status === 'draft') {
          form.business = bill.business || null;
          form.contact = bill.contact || '';
          form.vendor_invoice_number = bill.vendor_invoice_number || '';
          form.due_date = bill.due_date ? bill.due_date.slice(0, 10) : '';
          // Load contacts for the existing business without auto-selecting
          if (form.business) {
            lastFetchedBusiness = form.business;
            await fetchContactsAndAutoSelect(form.business, false);
          }
        }
      } else if (contextPoId) {
        // Arrived via "Create Bill" from a PO: pre-fill the vendor from the PO
        // and pull in the double-bill surfacing. Line items are copied
        // server-side on save (create_bill_from_po).
        const po = await api.get(`/api/purchase-orders/${contextPoId}/`);
        selectedPoId = po.po_id;
        selectedPoNumber = po.po_number;
        if (po.business) {
          form.business = po.business || null;
          lastFetchedBusiness = po.business || null;
          await fetchContactsAndAutoSelect(po.business, false);
          form.contact = po.contact || '';
        }
        await fetchPoBilling(contextPoId);
      }
    } catch (e) {
      errors = e.message;
    } finally {
      loading = false;
    }
  }

  async function handleSubmit(e) {
    e.preventDefault();
    saving = true;
    errors = null;
    try {
      const body = {
        business: (form.business !== '' && form.business != null) ? Number(form.business) : null,
        contact: form.contact !== '' ? Number(form.contact) : null,
        vendor_invoice_number: form.vendor_invoice_number,
        due_date: form.due_date || null,
      };
      if (isEdit) {
        await api.patch(`/api/bills/${params.id}/`, body);
        push(`/bills/${params.id}`);
      } else {
        if (contextPoId) body.purchase_order = Number(contextPoId);
        if (selectedPoId) body.purchase_order = Number(selectedPoId);
        const created = await api.post('/api/bills/', body);
        push(`/bills/${created.bill_id}`);
      }
    } catch (e) {
      errors = errorMessage(e);
    } finally {
      saving = false;
    }
  }

  $effect(() => {
    void params.id;
    load();
  });
</script>

<h2>{isEdit ? 'Edit Bill' : 'New Bill'}</h2>

{#if loading}
  <p>Loading...</p>
{:else if isEdit && billStatus !== 'draft'}
  <p>This bill is <strong>{billStatus}</strong> and can no longer be edited.</p>
  <p><a href={`#/bills/${params.id}`}>Back to bill</a></p>
{:else}
  {#if errors}
    <p><strong>Error:</strong> {errors}</p>
  {/if}
  <form onsubmit={handleSubmit}>
    <p>
      <label><strong>Vendor (Business) *</strong></label><br>
      <!-- selectedItem: neither bill nor po expose business_detail on this page; picker resolves by id as fallback -->
      <BusinessPicker bind:value={form.business} disabled={!!contextPoId}
        selectedItem={null}
        onSelect={(b) => { pickedBusiness = b; }} />
      {#if contextPoId}<br><small>Vendor comes from the purchase order.</small>{/if}
    </p>

    {#if !isEdit}
    {#if contextPoId}
    <p><strong>Purchase Order:</strong> {selectedPoNumber || contextPoId}</p>
    {:else}
    <p>
      <label for="purchase_order"><strong>Purchase Order</strong></label><br>
      <select id="purchase_order" bind:value={selectedPoId}
        onchange={() => { const po = vendorPos.find(p => p.po_id === selectedPoId); selectedPoNumber = po?.po_number ?? null; fetchPoBilling(selectedPoId); }}>
        <option value={null}>-- None --</option>
        {#each vendorPos as po (po.po_id)}
          <option value={po.po_id}>{po.po_number}</option>
        {/each}
      </select>
    </p>
    {/if}
    {#if poBilling?.po_fully_billed}
      <p class="warn">⚠ {selectedPoNumber} is fully billed</p>
    {/if}
    {#if poBilling?.other_bills?.length}
      <p class="info">This PO already has {poBilling.other_bills.length} other bill(s):
        {#each poBilling.other_bills as ob}
          <a href={`#/bills/${ob.bill_id}`}>{ob.vendor_invoice_number}</a>{' '}
        {/each}
      </p>
    {/if}
    {/if}

    <p>
      <label for="contact"><strong>Contact</strong></label><br>
      <select id="contact" bind:value={form.contact} disabled={loadingContacts}>
        {#if loadingContacts}
          <option value="">-- Loading... --</option>
        {:else if !form.business}
          <option value="">-- Select a business first --</option>
        {:else}
          <option value="">-- None --</option>
          {#each contactsForBusiness as c (c.contact_id)}
            <option value={c.contact_id}>{c.first_name} {c.last_name}</option>
          {/each}
        {/if}
      </select>
    </p>

    <p>
      <label for="vendor_invoice_number"><strong>Vendor Invoice #</strong></label><br>
      <input type="text" id="vendor_invoice_number" bind:value={form.vendor_invoice_number}>
    </p>

    <p>
      <label for="due_date"><strong>Due Date</strong></label><br>
      <input type="date" id="due_date" bind:value={form.due_date}>
    </p>

    <p>
      <button type="submit" disabled={saving}>Save</button>
      <a href={isEdit ? `#/bills/${params.id}` : '#/bills'}>Cancel</a>
    </p>
  </form>
{/if}

<style>
  .warn { background: #fff3cd; border: 1px solid #e0a800; padding: 8px; border-radius: 4px; }
  .info { color: #555; }
</style>

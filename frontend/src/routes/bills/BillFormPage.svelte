<script>
  import { api } from '../../lib/api.js';
  import { push, querystring } from 'svelte-spa-router';

  const { params = {} } = $props();
  const isEdit = $derived(!!params.id);

  let businesses = $state([]);
  let contactsForBusiness = $state([]);
  let loadingContacts = $state(false);
  let loading = $state(true);
  let errors = $state(null);
  let saving = $state(false);
  let billStatus = $state('draft');

  // Query param: ?po=ID pre-links a PO on create
  const initialParams = new URLSearchParams($querystring);
  const contextPoId = initialParams.get('po');

  let form = $state({
    business: '',
    contact: '',
    vendor_invoice_number: '',
    due_date: '',
  });

  let lastFetchedBusiness = form.business;

  function getDefaultContactId(businessId) {
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

  $effect(() => {
    const biz = form.business;
    if (biz === lastFetchedBusiness) return;
    lastFetchedBusiness = biz;
    fetchContactsAndAutoSelect(biz, true);
  });

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
          form.business = bill.business || '';
          form.contact = bill.contact || '';
          form.vendor_invoice_number = bill.vendor_invoice_number || '';
          form.due_date = bill.due_date ? bill.due_date.slice(0, 10) : '';
          // Load contacts for the existing business without auto-selecting
          if (form.business) {
            lastFetchedBusiness = form.business;
            await fetchContactsAndAutoSelect(form.business, false);
          }
        }
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
        business: form.business !== '' ? Number(form.business) : null,
        contact: form.contact !== '' ? Number(form.contact) : null,
        vendor_invoice_number: form.vendor_invoice_number,
        due_date: form.due_date || null,
      };
      if (isEdit) {
        await api.patch(`/api/bills/${params.id}/`, body);
        push(`/bills/${params.id}`);
      } else {
        if (contextPoId) body.purchase_order = Number(contextPoId);
        const created = await api.post('/api/bills/', body);
        push(`/bills/${created.bill_id}`);
      }
    } catch (e) {
      errors = e.data ? JSON.stringify(e.data) : e.message;
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
      <label for="business"><strong>Vendor (Business) *</strong></label><br>
      <select id="business" bind:value={form.business} required>
        <option value="">-- Select Business --</option>
        {#each businesses as biz (biz.business_id)}
          <option value={biz.business_id}>{biz.business_name}</option>
        {/each}
      </select>
    </p>

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

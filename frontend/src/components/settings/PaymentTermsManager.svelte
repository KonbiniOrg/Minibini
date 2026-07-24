<script>
  // Payment-terms manager (Settings → Business): a flat list, modal
  // create/edit, two-phase confirm delete. Terms with a qbo_id are QBO
  // mirrors — editable, but the next terms pull will flag local edits.
  import { api } from '../../lib/api.js';
  import { triageError } from '../../lib/errorTriage.js';
  import { showError } from '../../stores/messages.js';
  import Modal from '../Modal.svelte';
  import FieldError from '../FieldError.svelte';
  import FormMessage from '../FormMessage.svelte';

  let { refreshEpoch = 0 } = $props();

  let terms = $state([]);
  let loading = $state(true);

  // Modal state: editingId null = closed, 'new' = create, pk = edit.
  let editingId = $state(null);
  let form = $state({ name: '', days: '' });
  let saving = $state(false);
  let formError = $state('');
  let fieldErrs = $state({});

  async function load() {
    loading = true;
    try {
      terms = await api.get('/api/payment-terms/');
    } catch (e) {
      showError(triageError(e).overlay || 'Failed to load payment terms.');
    } finally {
      loading = false;
    }
  }

  function clearFormMessages() {
    formError = '';
    fieldErrs = {};
  }

  function startCreate() {
    form = { name: '', days: '' };
    editingId = 'new';
    clearFormMessages();
  }

  function startEdit(term) {
    form = { name: term.name, days: term.days ?? '' };
    editingId = term.term_id;
    clearFormMessages();
  }

  function cancelEdit() {
    editingId = null;
    clearFormMessages();
  }

  async function save() {
    saving = true;
    clearFormMessages();
    try {
      const payload = {
        name: form.name,
        days: form.days === '' ? null : Number(form.days),
      };
      if (editingId === 'new') {
        await api.post('/api/payment-terms/', payload);
      } else {
        await api.patch(`/api/payment-terms/${editingId}/`, payload);
      }
      editingId = null;
      await load();
    } catch (e) {
      const t = triageError(e);
      if (t.overlay) {
        showError(t.overlay);
      } else {
        formError = t.message;
        fieldErrs = t.fields;
      }
    } finally {
      saving = false;
    }
  }

  async function remove(term) {
    try {
      const first = await api.delete(`/api/payment-terms/${term.term_id}/`);
      const count = first?.impact?.businesses ?? 0;
      const detail = count
        ? `It is used by ${count} business${count === 1 ? '' : 'es'} — their terms will be cleared.`
        : 'It is not assigned to any business.';
      if (!confirm(`Delete payment terms "${term.name}"? ${detail}`)) return;
      await api.delete(`/api/payment-terms/${term.term_id}/?confirm=true`);
      await load();
    } catch (e) {
      showError(triageError(e).overlay || (e?.message || 'Delete failed.'));
    }
  }

  $effect(() => {
    void refreshEpoch;        // re-load after an import-panel commit
    load();
  });
</script>

<h4>Payment terms</h4>
{#if loading}
  <p>Loading…</p>
{:else}
  {#if terms.length}
    <table class="data-table terms-table">
      <thead>
        <tr><th>Name</th><th>Days</th><th></th><th>In use</th><th></th></tr>
      </thead>
      <tbody>
        {#each terms as term (term.term_id)}
          <tr>
            <td>{term.name}</td>
            <td>{term.days ?? '—'}</td>
            <td>{#if term.qbo_id}<span class="qbo-badge">QBO</span>{/if}</td>
            <td>{term.business_count
                  ? `${term.business_count} business${term.business_count === 1 ? '' : 'es'}`
                  : '—'}</td>
            <td>
              <button type="button" onclick={() => startEdit(term)}>Edit</button>
              <button type="button" onclick={() => remove(term)}>Delete</button>
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  {:else}
    <p><em>No payment terms yet.</em></p>
  {/if}
  <p><button type="button" onclick={startCreate}>+ New terms</button></p>
{/if}

<Modal open={editingId !== null} onSave={save} onCancel={cancelEdit}
       busy={saving} maxWidth="420px"
       label={editingId === 'new' ? 'New payment terms' : 'Edit payment terms'}>
  <h4>{editingId === 'new' ? 'New payment terms' : 'Edit payment terms'}</h4>
  <p>
    <label><strong>Name</strong><br>
      <input type="text" bind:value={form.name} placeholder="Net 30">
    </label>
    <FieldError errors={fieldErrs} field="name" />
  </p>
  <p>
    <label><strong>Days until due</strong><br>
      <input type="number" min="0" bind:value={form.days} placeholder="30">
    </label>
    <FieldError errors={fieldErrs} field="days" />
  </p>
  <p><small>Leave days blank for terms without a fixed due date.</small></p>
  <p>
    <button type="button" onclick={save} disabled={saving}>Save</button>
    <button type="button" onclick={cancelEdit}>Cancel</button>
  </p>
  <FormMessage error={formError} />
</Modal>

<style>
  .terms-table { max-width: 480px; }
  .qbo-badge {
    font-size: 0.75em;
    border: 1px solid #2ca01c;
    color: #2ca01c;
    border-radius: 4px;
    padding: 0 4px;
  }
</style>

<script>
  // Structure stamping (spec §9 rule 6, task-owned-money Phase 4 Task 5):
  // applying a WorkTemplate with `is_product_structure` mints ONE parent
  // task (est_qty=quantity) plus its per-unit subtasks in one call, instead
  // of the flat per-item generation every other template already does.
  // Convenience only — ad-hoc structure building (Add Task, then Add
  // Subtask) needs no template at all; this is the optional shortcut.
  import { api } from '../../lib/api.js';
  import { triageError } from '../../lib/errorTriage.js';
  import { showError } from '../../stores/messages.js';
  import Modal from '../Modal.svelte';
  import FieldError from '../FieldError.svelte';
  import FormMessage from '../FormMessage.svelte';

  let { open = false, jobId = null, onSaved = () => {}, onClose = () => {} } = $props();

  let templates = $state([]);
  let loading = $state(false);
  let templateId = $state('');
  let quantity = $state('');
  let busy = $state(false);
  let formError = $state('');
  let fieldErrs = $state({});

  async function loadTemplates() {
    loading = true;
    try {
      const resp = await api.get('/api/work-templates/?page_size=100');
      templates = resp.results || resp;
    } catch (e) {
      templates = [];
    } finally {
      loading = false;
    }
  }

  $effect(() => {
    if (open) {
      templateId = '';
      quantity = '';
      formError = '';
      fieldErrs = {};
      loadTemplates();
    }
  });

  // Clear stale errors as soon as the user changes anything.
  $effect(() => {
    templateId; quantity;
    formError = '';
    fieldErrs = {};
  });

  const selectedTemplate = $derived(
    templates.find((t) => String(t.template_id) === String(templateId)) || null
  );
  // Quantity only means something (and is only sent) for a product-structure
  // template — matches the API's own rejection of `quantity` on a flat one.
  const needsQuantity = $derived(!!selectedTemplate?.is_product_structure);

  async function save() {
    busy = true;
    formError = '';
    fieldErrs = {};
    if (!templateId) {
      fieldErrs = { template_id: ['This field is required.'] };
      busy = false;
      return;
    }
    const payload = { template_id: Number(templateId) };
    if (needsQuantity) {
      const q = quantity === '' ? NaN : Number(quantity);
      if (!Number.isFinite(q) || q <= 0) {
        fieldErrs = { quantity: ['Must be greater than zero.'] };
        busy = false;
        return;
      }
      payload.quantity = q;
    }
    try {
      const job = await api.post(`/api/jobs/${jobId}/populate-from-template/`, payload);
      onSaved(job);
    } catch (e) {
      const t = triageError(e);
      if (t.overlay) {
        showError(t.overlay);
      } else {
        formError = t.message;
        fieldErrs = t.fields;
      }
    } finally {
      busy = false;
    }
  }
</script>

<Modal {open} onCancel={onClose} maxWidth="600px" label="Apply template">
<form onsubmit={(e) => { e.preventDefault(); if (!busy) save(); }}>
  <h3>Apply Template</h3>

  {#if loading}
    <p>Loading…</p>
  {:else}
    <p>
      <label><strong>Template *</strong><br>
        <select bind:value={templateId} style="width:100%;box-sizing:border-box;">
          <option value="">-- Select a template --</option>
          {#each templates as t (t.template_id)}
            <option value={t.template_id}>{t.template_name}</option>
          {/each}
        </select>
      </label>
      <FieldError errors={fieldErrs} field="template_id" />
    </p>

    {#if needsQuantity}
      <p>
        <label><strong>Quantity *</strong><br>
          <input type="number" step="any" min="0" bind:value={quantity} style="width:100%;box-sizing:border-box;">
        </label>
        <FieldError errors={fieldErrs} field="quantity" />
      </p>
    {/if}

    <p>
      <button type="submit" disabled={busy}>{busy ? 'Applying…' : 'Apply'}</button>
      <button type="button" onclick={onClose} disabled={busy}>Cancel</button>
    </p>
    <FormMessage error={formError} />
  {/if}
</form>
</Modal>

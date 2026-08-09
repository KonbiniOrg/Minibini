<script>
  // Streamlined deposit-invoice generator (Task 21, 2026-07 — replaces the
  // picker's "Add Deposit" entry). Two-step create, reusing the exact
  // backend contract the rest of the deposit feature already uses (no
  // backend changes):
  //   1. POST /api/invoices/ {job, seed: false} — same call InvoicePanel's
  //      Start Invoice makes, except seed: false: a fresh draft otherwise
  //      auto-seeds from the job's agreement (better-fees skeleton phase),
  //      but this modal wants an empty, deposit-only draft.
  //      InvoiceWizardService.open_for_job is idempotent: if the job
  //      already has an open draft, it returns that draft instead of erroring
  //      (see docs/designs/invoicing-and-expenses.md), so this button is safe
  //      to offer even when a draft already exists.
  //   2. POST /api/invoices/{id}/line-items/ {deposit: true, ...} — the
  //      existing deposit line-item contract; the server stamps the
  //      configured deposit accounting category.
  import { api } from '../../lib/api.js';
  import { triageError } from '../../lib/errorTriage.js';
  import { showError } from '../../stores/messages.js';
  import Modal from '../Modal.svelte';
  import FieldError from '../FieldError.svelte';
  import FormMessage from '../FormMessage.svelte';

  let {
    open = false,
    job,
    onCreated = () => {},
    onClose = () => {},
  } = $props();

  let amount = $state('');
  let busy = $state(false);
  let formError = $state('');
  let fieldErrs = $state({});

  // Fresh on every open — a cancelled attempt must not leave a stale amount
  // or error behind when reopened.
  $effect(() => {
    if (open) { amount = ''; busy = false; formError = ''; fieldErrs = {}; }
  });

  async function submit() {
    formError = '';
    fieldErrs = {};
    const amt = Number(amount);
    if (!amount || !(amt > 0)) {
      fieldErrs = { amount: ['Enter an amount greater than 0.'] };
      return;
    }

    busy = true;
    let invoiceId;
    try {
      const inv = await api.post('/api/invoices/', { job: job.job_id, seed: false });
      invoiceId = inv.invoice_id;
    } catch (e) {
      busy = false;
      const t = triageError(e);
      if (t.overlay) {
        showError(t.overlay);
      } else {
        formError = t.message || 'Failed to start invoice.';
        fieldErrs = t.fields;
      }
      return;
    }

    try {
      await api.post(`/api/invoices/${invoiceId}/line-items/`, {
        deposit: true,
        description: `Deposit on ${job.job_number}`,
        qty: '1',
        units: 'none',
        price: amount,
      });
    } catch (e) {
      // The draft invoice already exists at this point (step 1 succeeded) —
      // even though the deposit line failed (e.g. no default deposit
      // category configured), the draft is real and worth showing: the user
      // can fix the config and add the line by hand. So still navigate to
      // it (same as the success path) rather than leaving the user stuck on
      // this closing modal; the failure is surfaced via the global overlay
      // instead of a form message that's about to disappear.
      const t = triageError(e);
      showError(t.overlay
        || (t.fields.accounting_category && t.fields.accounting_category[0])
        || t.message
        || 'Could not add the deposit line.');
      busy = false;
      onCreated(invoiceId);
      return;
    }

    busy = false;
    onCreated(invoiceId);
  }
</script>

<Modal {open} onCancel={onClose} label="Add Deposit Invoice">
<form onsubmit={(e) => { e.preventDefault(); if (!busy) submit(); }}>
  <h3>Add Deposit Invoice</h3>
  <p>
    <label>Amount<br>
      <!-- svelte-ignore a11y_autofocus -- intentional: sole input in a
           just-opened single-purpose modal (Task 21 brief). -->
      <input type="number" step="0.01" autofocus value={amount}
             oninput={(e) => amount = e.target.value}>
    </label>
    <FieldError errors={fieldErrs} field="amount" />
  </p>
  <div class="buttons">
    <button type="submit" disabled={busy}>{busy ? 'Creating…' : 'Create'}</button>
    <button type="button" onclick={onClose} disabled={busy}>Cancel</button>
  </div>
  <FormMessage error={formError} />
</form>
</Modal>

<style>
  .buttons { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
</style>

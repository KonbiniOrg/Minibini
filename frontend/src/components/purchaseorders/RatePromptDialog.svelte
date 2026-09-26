<script>
  // Task-rate prompt (outsourced-work port, ported from task-owned-money
  // Phase 5 spec §7 rule 4): after a reconcile call, each PO line with a
  // clean final price on an uninvoiced linked task offers "update the
  // task's rate to the final-price-derived suggestion?". This NEVER
  // auto-applies — accept PATCHes the task itself through the existing
  // money-gated task-update path; decline just dismisses that row. Each
  // row resolves independently, so a failure on one doesn't block the
  // others.
  //
  // Only rendered by the caller for canManageFinancials users — the
  // PATCH the Accept button issues is money-gated server-side
  // (TaskSerializer.MONEY_FIELDS: CanManageJobOrPM or can_manage_financials).
  // can_manage_financials always satisfies that gate, so gating this
  // dialog's visibility on it client-side never mis-hides a working
  // Accept button. A job's PM-only user (no can_manage_financials) could
  // also satisfy the server gate for their own job's task, but the PO
  // page has no per-task job/PM context to evaluate that client-side —
  // this dialog simply doesn't render for them (hide-on-403-equivalent
  // fallback, not a hard block: nothing here prevents them from using
  // the task's own edit form directly). Any unexpected 403 (edge case)
  // still surfaces as a normal per-row error, not a crash.
  //
  // Re-shape from fees (outsourced-work port): `current_rate` is now the
  // task's EFFECTIVE rate (compute_rate_prompts reads task.effective_rate(),
  // modifiers-aware) rather than the raw stored rate, so it's displayed as
  // received with no further derivation. Each prompt also carries
  // `has_active_modifiers` — when true, a per-row note clarifies that the
  // Current Rate already includes modifiers layered on top of the plain
  // accepted rate, so accepting the suggestion doesn't remove them.
  import Modal from '../Modal.svelte';
  import { api } from '../../lib/api.js';
  import { triageError } from '../../lib/errorTriage.js';
  import { formatMoney } from '../../lib/format.js';

  // markupApplied mirrors the reconcile response's `markup_applied` flag
  // (compute_rate_prompts): false means no `default_material_markup_percent`
  // Configuration row exists, so every suggested_rate above is simply the
  // clean final_price with no markup layered on — worth surfacing so the
  // PM doesn't mistake the number for a marked-up sell price. Defaults true
  // (no note) so callers that don't thread the flag through render exactly
  // as before.
  const { prompts = [], markupApplied = true, onClose = () => {} } = $props();

  // rowState[task_id] = { status: 'pending'|'accepted'|'declined'|'error', message? }
  const rowState = $state({});

  async function accept(prompt) {
    rowState[prompt.task_id] = { status: 'pending' };
    try {
      const task = await api.get(`/api/tasks/${prompt.task_id}/`);
      await api.patch(`/api/jobs/${task.job.id}/tasks/${prompt.task_id}/`, {
        rate: prompt.suggested_rate,
      });
      rowState[prompt.task_id] = { status: 'accepted' };
    } catch (e) {
      const t = triageError(e);
      rowState[prompt.task_id] = {
        status: 'error',
        message: t.overlay || t.message || 'Could not update the task rate.',
      };
    }
  }

  function decline(prompt) {
    rowState[prompt.task_id] = { status: 'declined' };
  }
</script>

<!-- No onSave: each row accepts/declines independently, so there is no
     single primary Enter action for the modal shell to fire. -->
<Modal open={true} onCancel={onClose} maxWidth="700px" label="Update task rates?">
  <h3>Update task rates?</h3>
  <p>Reconciliation recorded a final price that differs from the quoted rate on these linked tasks. Accept to update the task's selling rate, or decline to leave it as quoted.</p>
  {#if !markupApplied}
    <p class="markup-note"><em>No markup configured — suggestion equals vendor cost.</em></p>
  {/if}
  <table class="data-table">
    <thead>
      <tr><th>Task</th><th class="text-right">Current Rate</th><th class="text-right">Suggested Rate</th><th>Decision</th></tr>
    </thead>
    <tbody>
      {#each prompts as prompt (prompt.task_id)}
        {@const state = rowState[prompt.task_id]}
        <tr>
          <td>
            {prompt.task_name}
            {#if prompt.has_active_modifiers}
              <br><small class="modifiers-note">modifiers apply on top of the accepted rate</small>
            {/if}
          </td>
          <td class="text-right">{formatMoney(prompt.current_rate)}</td>
          <td class="text-right">{formatMoney(prompt.suggested_rate)}</td>
          <td>
            {#if !state}
              <button type="button" onclick={() => accept(prompt)}>Accept</button>
              <button type="button" onclick={() => decline(prompt)}>Decline</button>
            {:else if state.status === 'pending'}
              Updating…
            {:else if state.status === 'accepted'}
              Updated.
            {:else if state.status === 'declined'}
              Declined.
            {:else if state.status === 'error'}
              <span class="row-error">{state.message}</span>
              <button type="button" onclick={() => accept(prompt)}>Retry</button>
            {/if}
          </td>
        </tr>
      {/each}
    </tbody>
  </table>
  <p>
    <button type="button" onclick={onClose}>Close</button>
  </p>
</Modal>

<style>
  .text-right { text-align: right; }
  .row-error { color: #c00; }
  .modifiers-note { color: #666; }
</style>

<script>
  /**
   * Modal that asks the user "still needed?" for one or more linked Materials
   * about to be severed. Emits a map of {line_item_id: "keep"|"delete"}.
   *
   * Props:
   *   items: [{ material_id, job_number, quantity, description, line_item_id }]
   *   onSubmit: (decisions) => void   // decisions keyed by line_item_id
   *   onCancel: () => void
   */
  import Modal from '../Modal.svelte';

  const { items = [], onSubmit, onCancel } = $props();
  let decisions = $state({});

  // Default every row to 'keep' — the non-destructive choice (the Material
  // stays planned on its Job; the user opts in to deleting it).
  // svelte-ignore state_referenced_locally -- mount-seed by design (parent remounts via {#if}/{#key}, or a $effect re-syncs)
  for (const it of items) {
    decisions[it.line_item_id] = 'keep';
  }

  function submit() {
    onSubmit({ ...decisions });
  }
</script>

<Modal open={true} onSave={submit} onCancel={onCancel} maxWidth="900px">
    <h3>Linked Materials — still needed?</h3>
    <p>Each of these Materials is currently linked to a PO line you're about to sever. Decide whether the plan on the Job should stay.</p>
    <table class="data-table">
      <thead>
        <tr><th>Job</th><th>Material</th><th>Qty</th><th>Decision</th></tr>
      </thead>
      <tbody>
        {#each items as it}
          <tr>
            <td>{it.job_number}</td>
            <td>{it.description}</td>
            <td>{it.quantity}</td>
            <td>
              <label>
                <input type="radio" name={`d-${it.line_item_id}`} value="keep"
                       checked={decisions[it.line_item_id] === 'keep'}
                       onchange={() => { decisions[it.line_item_id] = 'keep'; }}>
                Keep on {it.job_number}
              </label>
              <label>
                <input type="radio" name={`d-${it.line_item_id}`} value="delete"
                       checked={decisions[it.line_item_id] === 'delete'}
                       onchange={() => { decisions[it.line_item_id] = 'delete'; }}>
                Delete
              </label>
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
    <p>
      <button onclick={submit}>Confirm</button>
      <button onclick={onCancel}>Cancel</button>
    </p>
</Modal>

<style>
</style>

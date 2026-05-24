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
  import { modalKeys } from '../../lib/modalKeys.js';

  const { items = [], onSubmit, onCancel } = $props();
  let decisions = $state({});

  // Default every row to 'delete'
  for (const it of items) {
    decisions[it.line_item_id] = 'delete';
  }

  function submit() {
    onSubmit({ ...decisions });
  }
</script>

<div class="overlay" use:modalKeys={{ onSave: submit, onCancel }}>
  <div class="dialog">
    <h3>Linked Materials — still needed?</h3>
    <p>Each of these Materials is currently linked to a PO line you're about to sever. Decide whether the plan on the Job should stay.</p>
    <table border="1">
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
  </div>
</div>

<style>
  .overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: center; z-index: 1000; }
  .dialog { background: white; padding: 20px; max-width: 600px; border-radius: 6px; }
</style>

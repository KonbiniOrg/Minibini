<script>
  const {
    lineItems = [],
    onSubmit,
    onCancel,
  } = $props();

  // Only show lines that still need receiving
  let receivableItems = $derived(
    lineItems.filter(li => Number(li.qty_received) + Number(li.qty_cancelled) < Number(li.qty))
  );

  let entries = $state([]);

  $effect(() => {
    entries = receivableItems.map(li => {
      const remaining = Number(li.qty) - Number(li.qty_received);
      return {
        line_item_id: li.line_item_id,
        line_number: li.line_number,
        description: li.description,
        qty_ordered: Number(li.qty),
        qty_already_received: Number(li.qty_received),
        // Pre-fill with remaining qty; user can edit (overage allowed).
        qty_receiving: remaining > 0 ? String(remaining) : '',
        note: '',
      };
    });
  });

  function handleSubmit(e) {
    e.preventDefault();
    const items = entries
      .filter(entry => entry.qty_receiving && Number(entry.qty_receiving) > 0)
      .map(entry => ({
        line_item_id: entry.line_item_id,
        qty_received: Number(entry.qty_receiving),
        note: entry.note || undefined,
      }));
    if (items.length === 0) return;
    onSubmit(items);
  }
</script>

<fieldset>
  <legend><strong>Receive Items</strong></legend>

  {#if receivableItems.length === 0}
    <p>All items have been received.</p>
  {:else}
    <form onsubmit={handleSubmit}>
      <table class="data-table">
        <thead>
          <tr>
            <th>#</th>
            <th>Description</th>
            <th class="text-right">Ordered</th>
            <th class="text-right">Received</th>
            <th class="text-right">Remaining</th>
            <th class="text-right">Receiving Now</th>
            <th>Note</th>
          </tr>
        </thead>
        <tbody>
          {#each entries as entry, i}
            <tr>
              <td>{entry.line_number}</td>
              <td>{entry.description}</td>
              <td class="text-right">{entry.qty_ordered}</td>
              <td class="text-right">{entry.qty_already_received}</td>
              <td class="text-right">{entry.qty_ordered - entry.qty_already_received}</td>
              <td>
                <input
                  type="number"
                  bind:value={entries[i].qty_receiving}
                  step="any"
                  min="0"
                  style="width:80px;text-align:right;"
                >
              </td>
              <td>
                <input
                  type="text"
                  bind:value={entries[i].note}
                  placeholder="Optional note"
                  style="width:100%;box-sizing:border-box;"
                >
              </td>
            </tr>
          {/each}
        </tbody>
      </table>

      <p>
        <button type="submit">Record Receipt</button>
        <button type="button" onclick={onCancel}>Cancel</button>
      </p>
    </form>
  {/if}
</fieldset>

<style>
  .text-right { text-align: right; }
</style>

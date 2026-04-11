<script>
  let { sourcePool = null, selectedAtoms = $bindable([]) } = $props();

  function toggleAtom(atomType, atomId) {
    const key = `${atomType}:${atomId}`;
    const existing = selectedAtoms.find(a => `${a.type}:${a.id}` === key);
    if (existing) {
      selectedAtoms = selectedAtoms.filter(a => `${a.type}:${a.id}` !== key);
    } else {
      selectedAtoms = [...selectedAtoms, {type: atomType, id: atomId}];
    }
  }

  function isSelected(atomType, atomId) {
    return selectedAtoms.some(a => a.type === atomType && a.id === atomId);
  }
</script>

{#if !sourcePool}
  <p>No source data.</p>
{:else}
  {#each sourcePool.work_orders as wo}
    {#each wo.tasks as task}
      <div>
        {#if !task.has_billable_atoms}
          <em style="color: #999;">{task.name} (no billable items)</em>
        {:else}
          <strong>{task.name}</strong>
          {#each task.atoms as atom}
            <div style="margin-left: 16px;">
              {#if atom.state === 'available'}
                <label>
                  <input
                    type="checkbox"
                    checked={isSelected(atom.atom_type, atom.atom_id)}
                    onchange={() => toggleAtom(atom.atom_type, atom.atom_id)}
                  >
                  {atom.description}
                  {#if atom.sub_info} <small>&middot; {atom.sub_info}</small>{/if}
                  &mdash; ${atom.computed_amount}
                </label>
              {:else if atom.state === 'claimed_by_current'}
                <span style="color: #777;">
                  <input type="checkbox" checked disabled>
                  <em>{atom.description} &mdash; ${atom.computed_amount}</em>
                  <small>&rarr; line {atom.claiming_line_number}</small>
                </span>
              {:else if atom.state === 'claimed_by_other'}
                <span style="color: #999;">
                  <input type="checkbox" disabled>
                  <em>{atom.description} &mdash; ${atom.computed_amount}</em>
                  <small>
                    <a href="#/invoices/{atom.claiming_invoice_id}">&rarr; {atom.claiming_invoice_number}</a>
                  </small>
                </span>
              {/if}
            </div>
          {/each}
        {/if}
      </div>
    {/each}
  {/each}
{/if}

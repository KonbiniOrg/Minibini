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

{#if !sourcePool || sourcePool.atoms.length === 0}
  <p><em>No atoms on this worksheet.</em></p>
{:else}
  <ul style="list-style: none; padding: 0;">
    {#each sourcePool.atoms as atom (atom.type + ':' + atom.id)}
      <li>
        {#if atom.state === 'available'}
          <label>
            <input
              type="checkbox"
              checked={isSelected(atom.type, atom.id)}
              onchange={() => toggleAtom(atom.type, atom.id)}
            >
            <small>[{atom.type === 'plan_task' ? 'task' : 'material'}]</small>
            {atom.description}
            &mdash; ${atom.amount}
          </label>
        {:else if atom.state === 'claimed_by_current'}
          <span style="color: #777;">
            <input type="checkbox" checked disabled>
            <em>{atom.description} &mdash; ${atom.amount}</em>
            <small>&rarr; line {atom.claiming_line_item_id}</small>
          </span>
        {:else if atom.state === 'claimed_by_other'}
          <span style="color: #999;">
            <input type="checkbox" disabled>
            <em>{atom.description} &mdash; ${atom.amount}</em>
            <small>&rarr; estimate {atom.claiming_estimate_number}</small>
          </span>
        {/if}
      </li>
    {/each}
  </ul>
{/if}

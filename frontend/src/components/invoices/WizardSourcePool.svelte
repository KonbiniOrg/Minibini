<script>
  import WizardAtomRow from '../wizards/WizardAtomRow.svelte';

  let { sourcePool = null, selectedAtoms = $bindable([]) } = $props();

  function toggleAtom(atom) {
    const key = `${atom.type}:${atom.id}`;
    const existing = selectedAtoms.find(a => `${a.type}:${a.id}` === key);
    if (existing) {
      selectedAtoms = selectedAtoms.filter(a => `${a.type}:${a.id}` !== key);
    } else {
      selectedAtoms = [...selectedAtoms, {type: atom.type, id: atom.id}];
    }
  }

  function isSelected(atom) {
    return selectedAtoms.some(a => a.type === atom.type && a.id === atom.id);
  }
</script>

{#if !sourcePool}
  <p>No source data.</p>
{:else}
  {#each sourcePool.tasks as task (task.task_id ?? task.name)}
    <div>
      {#if !task.has_billable_atoms}
        <em style="color: #999;">{task.name} (no billable items)</em>
      {:else}
        <strong>{task.name}</strong>
        {#each task.atoms as atom (atom.type + ':' + atom.id)}
          <div style="margin-left: 16px;">
            <WizardAtomRow
              {atom}
              selected={isSelected(atom)}
              onToggle={() => toggleAtom(atom)}
            />
          </div>
        {/each}
      {/if}
    </div>
  {/each}
{/if}

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

{#if !sourcePool || sourcePool.atoms.length === 0}
  <p><em>No atoms on this worksheet.</em></p>
{:else}
  <ul style="list-style: none; padding: 0;">
    {#each sourcePool.atoms as atom (atom.type + ':' + atom.id)}
      <li>
        <WizardAtomRow
          {atom}
          selected={isSelected(atom)}
          onToggle={() => toggleAtom(atom)}
        />
      </li>
    {/each}
  </ul>
{/if}

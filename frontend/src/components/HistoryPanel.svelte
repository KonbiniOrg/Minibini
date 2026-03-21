<script>
  import { viewMode } from '../stores/viewMode.js';

  let {
    history = null,
    onAddNote = null,
  } = $props();

  let noteText = $state('');

  let visibleHistory = $derived(
    history?.results
      ? $viewMode === 'full'
        ? history.results
        : history.results.filter(h => h.text)
      : []
  );

  async function submitNote() {
    if (!noteText.trim() || !onAddNote) return;
    await onAddNote(noteText.trim());
    noteText = '';
  }
</script>

{#if onAddNote}
  <p>
    <textarea bind:value={noteText} rows="2" placeholder="Add a note..."></textarea><br>
    <button onclick={submitNote} disabled={!noteText.trim()}>Add Note</button>
  </p>
{/if}
{#if visibleHistory.length > 0}
  {#each visibleHistory as entry}
    {#if entry.text}
      <p>
        <strong>{entry.username || 'Unknown'}</strong>
        ({new Date(entry.timestamp).toLocaleString()}):<br>
        {entry.text}
        {#if entry.changes}
          {@const fields = Object.entries(entry.changes).filter(([k]) => !k.startsWith('_'))}
          {#if fields.length > 0}
            <br><small>{fields.map(([k, v]) => `${k}: ${v.old} → ${v.new}`).join(', ')}</small>
          {/if}
        {/if}
      </p>
    {:else}
      <p><small>
        <strong>{entry.username || 'System'}</strong>
        ({new Date(entry.timestamp).toLocaleString()})
        [{entry.entry_type}] {entry.object_type}
        {#if entry.changes}
          — {Object.entries(entry.changes).filter(([k]) => !k.startsWith('_')).map(([k, v]) => `${k}: ${v.old} → ${v.new}`).join(', ')}
        {/if}
        {#if entry.changes?._created}
          — created
        {/if}
        {#if entry.changes?._action}
          — {entry.changes._action}
        {/if}
      </small></p>
    {/if}
  {/each}
{:else}
  <p>No history.</p>
{/if}

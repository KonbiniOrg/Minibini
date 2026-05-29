<script>
  import { viewMode } from '../stores/viewMode.js';

  let {
    history = null,
    onAddNote = null,
  } = $props();

  let noteText = $state('');

  let entries = $derived.by(() => {
    const all = (history?.results || []).map(h => ({
      data: h,
      date: new Date(h.timestamp),
    }));
    all.sort((a, b) => b.date - a.date);
    if ($viewMode === 'lite') {
      return all.filter(e => e.data.text);
    }
    return all;
  });

  async function submitNote() {
    if (!noteText.trim() || !onAddNote) return;
    await onAddNote(noteText.trim());
    noteText = '';
  }
</script>

<h3>History</h3>

{#if onAddNote}
  <div>
    <textarea bind:value={noteText} rows="2" placeholder="Add a note..."></textarea>
    <button onclick={submitNote} disabled={!noteText.trim()}>Add Note</button>
  </div>
{/if}

<div class="history-scroll">
  {#if entries.length > 0}
    {#each entries as entry}
      <div class="history-entry">
        {#if entry.data.text}
          <p>
            <strong>{entry.data.username || 'Unknown'}</strong>
            ({new Date(entry.data.timestamp).toLocaleString()}):<br>
            <span class="preserve-breaks">{entry.data.text}</span>
            {#if entry.data.changes}
              {@const fields = Object.entries(entry.data.changes).filter(([k]) => !k.startsWith('_'))}
              {#if fields.length > 0}
                <br><small>{fields.map(([k, v]) => `${k}: ${v.old} → ${v.new}`).join(', ')}</small>
              {/if}
            {/if}
          </p>
        {:else}
          <p><small>
            <strong>{entry.data.username || 'System'}</strong>
            ({new Date(entry.data.timestamp).toLocaleString()})
            [{entry.data.entry_type}] {entry.data.object_type}
            {#if entry.data.changes}
              — {Object.entries(entry.data.changes).filter(([k]) => !k.startsWith('_')).map(([k, v]) => `${k}: ${v.old} → ${v.new}`).join(', ')}
            {/if}
            {#if entry.data.changes?._created}
              — created
            {/if}
            {#if entry.data.changes?._action}
              — {entry.data.changes._action}
            {/if}
          </small></p>
        {/if}
      </div>
    {/each}
  {:else}
    <p>No history.</p>
  {/if}
</div>

<style>
  .history-scroll { overflow-y: auto; max-height: 280px; }
  .history-entry { padding: 6px 0; border-bottom: 1px solid #f0f0f0; font-size: 13px; line-height: 1.4; }
</style>

<script>
  import { api } from '../../lib/api.js';

  let { params = {} } = $props();
  let jobId = $derived(params.id);

  let job = $state(null);
  let history = $state(null);
  let loading = $state(true);
  let loadError = $state(null);
  let noteText = $state('');
  let saving = $state(false);

  async function load() {
    loading = true;
    loadError = null;
    try {
      const [jobData, histData] = await Promise.all([
        api.get(`/api/jobs/${jobId}/`),
        api.get(`/api/jobs/${jobId}/history/`),
      ]);
      job = jobData;
      history = histData;
    } catch (e) {
      loadError = e.message;
    } finally {
      loading = false;
    }
  }

  $effect(() => {
    if (jobId) load();
  });

  let entries = $derived((history?.results || []).map(h => ({ ...h, when: new Date(h.timestamp) })));

  function fieldChanges(changes) {
    if (!changes) return '';
    return Object.entries(changes)
      .filter(([k]) => !k.startsWith('_'))
      .map(([k, v]) => `${k}: ${v?.old ?? '–'} → ${v?.new ?? '–'}`)
      .join(', ');
  }

  function describe(entry) {
    const c = entry.changes || {};
    if (entry.entry_type === 'note') return entry.text;
    if (c._action) return c._action;
    if (c._created) return 'created';
    return fieldChanges(c) || '(no detail)';
  }

  async function addNote() {
    const text = noteText.trim();
    if (!text) return;
    saving = true;
    try {
      await api.post(`/api/jobs/${jobId}/notes/`, { text });
      noteText = '';
      await load();
    } catch (e) {
      alert(e.message || 'Failed to add note');
    } finally {
      saving = false;
    }
  }
</script>

{#if loading}
  <p>Loading…</p>
{:else if loadError}
  <p class="error">{loadError}</p>
{:else}
  <div class="job-history-page">
    <p><a href="#/jobs/{jobId}">← Back to job</a></p>
    <h1>History — Job {job?.job_number}</h1>

    <div class="add-note">
      <textarea bind:value={noteText} rows="2" placeholder="Add a note…"></textarea>
      <button onclick={addNote} disabled={saving || !noteText.trim()}>Add Note</button>
    </div>

    {#if entries.length > 0}
      <ul class="timeline">
        {#each entries as entry (entry.id)}
          <li class="entry entry-{entry.entry_type}">
            <div class="entry-meta">
              {#if entry.source_link}
                <a class="source" href={entry.source_link}>{entry.source_label || entry.object_type}</a>
              {:else}
                <span class="source">{entry.source_label || entry.object_type}</span>
              {/if}
              <span class="who">{entry.username || 'System'}</span>
              <span class="when">{entry.when.toLocaleString()}</span>
            </div>
            <div class="entry-body preserve-breaks">{describe(entry)}</div>
          </li>
        {/each}
      </ul>
    {:else}
      <p>No history yet.</p>
    {/if}
  </div>
{/if}

<style>
  .job-history-page { max-width: 820px; margin: 0 auto; padding: 16px 24px; }
  .add-note { margin: 12px 0 20px; }
  .add-note textarea { width: 100%; box-sizing: border-box; }
  .timeline { list-style: none; padding: 0; margin: 0; }
  .entry { padding: 8px 0; border-bottom: 1px solid #eee; }
  .entry-meta { display: flex; gap: 10px; font-size: 13px; color: #555; align-items: baseline; }
  .entry-meta .source { font-weight: 600; color: #1f2937; }
  .entry-meta .when { margin-left: auto; }
  .entry-body { margin-top: 2px; }
  .entry-note .entry-body { font-style: italic; }
  .preserve-breaks { white-space: pre-wrap; }
</style>

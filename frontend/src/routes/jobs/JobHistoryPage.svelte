<script>
  import { api } from '../../lib/api.js';
  import { link } from 'svelte-spa-router';
  import JobHeader from '../../components/jobs/JobHeader.svelte';

  let { params = {} } = $props();
  let jobId = $derived(params.id);

  let job = $state(null);
  let contact = $state(null);
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
      // Fetch contact for the JobHeader; non-fatal if the lookup fails.
      contact = null;
      if (job.contact) {
        try {
          contact = await api.get(`/api/contacts/${job.contact}/`);
        } catch {
          contact = null;
        }
      }
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

  // Color group per object type; change orders share the estimate tint.
  function typeClass(objectType) {
    return 'ot-' + (objectType === 'changeorder' ? 'estimate' : objectType);
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

<div class="page">
  {#if loading}
    <p>Loading…</p>
  {:else if loadError}
    <p class="err">{loadError}</p>
  {:else if job}
    <JobHeader {job} {contact} onStatusChange={load} />

    <header class="page-header">
      <h2>History</h2>
      <p><a use:link href={`/jobs/${jobId}`}>← Back to overview</a></p>
    </header>

    <div class="body">
      <div class="add-note">
        <textarea bind:value={noteText} rows="2" placeholder="Add a note…"></textarea>
        <button onclick={addNote} disabled={saving || !noteText.trim()}>Add Note</button>
      </div>

      {#if entries.length > 0}
        <ul class="timeline">
          {#each entries as entry (entry.id)}
            <li class="entry entry-{entry.entry_type} {typeClass(entry.object_type)}">
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
  {:else}
    <p class="err">Failed to load job.</p>
  {/if}
</div>

<style>
  .page { padding: 0 0 20px 0; }
  .page-header { padding: 0 24px; }
  .page-header h2 { margin-top: 16px; margin-bottom: 4px; }
  .body { max-width: 820px; padding: 0 24px; }
  .add-note { margin: 12px 0 20px; }
  .add-note textarea { width: 100%; box-sizing: border-box; }
  .timeline { list-style: none; padding: 0; margin: 0; }
  .entry { padding: 8px 10px; border-bottom: 1px solid rgba(0, 0, 0, 0.06); }

  /* Background tint by object type. Estimates + change orders share a tint.
     Warm-biased: job/task/shipment pulled apart off the blue end. */
  .ot-job { background: #ebe8e4; }        /* neutral warm gray */
  .ot-estimate { background: #fdf0c9; }   /* amber */
  .ot-invoice { background: #e4f3e0; }    /* green */
  .ot-task { background: #f6d2d5; }        /* rose / red */
  .ot-deliverable { background: #eaddf6; } /* violet */
  .ot-shipment { background: #f5e3cd; }    /* warm sand */
  .ot-material { background: #f9dcc6; }    /* peach */
  .entry-meta { display: flex; gap: 10px; font-size: 13px; color: #555; align-items: baseline; }
  .entry-meta .source { font-weight: 600; color: #1f2937; }
  .entry-meta .when { margin-left: auto; }
  .entry-body { margin-top: 2px; }
  .entry-note .entry-body { font-style: italic; }
  .preserve-breaks { white-space: pre-wrap; }
  .err { color: #c00; padding: 0 24px; }
</style>

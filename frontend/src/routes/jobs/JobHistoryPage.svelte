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

  // --- Field-diff rendering (From/To + long-value popover) ---
  const LONG_LEN = 100;
  let openPopover = $state(null); // `${entryId}:${field}` of the open popover

  function popKey(entryId, field) {
    return `${entryId}:${field}`;
  }
  function togglePopover(entryId, field) {
    const k = popKey(entryId, field);
    openPopover = openPopover === k ? null : k;
  }

  function fmtVal(v) {
    return v == null ? '(empty)' : String(v);
  }
  function isLong(v) {
    const s = v == null ? '' : String(v);
    return s.length > LONG_LEN || s.includes('\n');
  }
  function previewVal(v, n = 120) {
    const s = (v == null ? '' : String(v)).replace(/\s+/g, ' ').trim();
    return s.length > n ? s.slice(0, n) + '…' : s;
  }

  function isFieldDiff(entry) {
    const c = entry.changes || {};
    if (entry.entry_type === 'note') return false;
    if (c._action || c._created) return false;
    return Object.keys(c).some((k) => !k.startsWith('_'));
  }
  function diffFields(entry) {
    const c = entry.changes || {};
    return Object.entries(c)
      .filter(([k]) => !k.startsWith('_'))
      .map(([field, v]) => ({
        field,
        old: v?.old ?? null,
        new: v?.new ?? null,
        long: isLong(v?.old) || isLong(v?.new),
      }));
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
                <span class="stamp">
                  <span class="when">{entry.when.toLocaleString()}</span>
                  <span class="who">{entry.username || 'System'}</span>
                </span>
              </div>
              <div class="entry-body">
                {#if isFieldDiff(entry)}
                  {#each diffFields(entry) as f (f.field)}
                    {#if f.long}
                      <div class="diff diff-long">
                        <div class="diff-field">{f.field} changed</div>
                        <div class="ft-row"><span class="ft-label">From</span><span class="ft-prev">{previewVal(f.old)}</span></div>
                        <div class="ft-row"><span class="ft-label">To</span><span class="ft-prev">{previewVal(f.new)}</span></div>
                        <div class="pop-wrap">
                          <button class="pop-trigger" type="button" onclick={() => togglePopover(entry.id, f.field)}>
                            {openPopover === popKey(entry.id, f.field) ? 'Hide full' : 'Show full'}
                          </button>
                          {#if openPopover === popKey(entry.id, f.field)}
                            <button class="pop-backdrop" type="button" aria-label="Close" onclick={() => (openPopover = null)}></button>
                            <div class="popover" role="dialog" aria-label="{f.field} full text">
                              <div class="pop-section">
                                <div class="pop-label">From</div>
                                <div class="pop-val preserve-breaks">{fmtVal(f.old)}</div>
                              </div>
                              <div class="pop-section">
                                <div class="pop-label">To</div>
                                <div class="pop-val preserve-breaks">{fmtVal(f.new)}</div>
                              </div>
                            </div>
                          {/if}
                        </div>
                      </div>
                    {:else}
                      <div class="diff diff-short">
                        <span class="diff-field">{f.field}</span>:
                        <span class="val">{fmtVal(f.old)}</span>
                        <span class="arrow">→</span>
                        <span class="val">{fmtVal(f.new)}</span>
                      </div>
                    {/if}
                  {/each}
                {:else}
                  <span class="preserve-breaks">{describe(entry)}</span>
                {/if}
              </div>
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
     A balanced spread across the spectrum — one hue family each. */
  .ot-task { background: #f7d3d6; }        /* red / rose */
  .ot-material { background: #fbe0c6; }    /* orange */
  .ot-estimate { background: #fcf1c6; }    /* yellow / amber */
  .ot-invoice { background: #dcf1d8; }     /* green */
  .ot-shipment { background: #d4eef0; }    /* teal */
  .ot-job { background: #dde7f5; }         /* blue */
  .ot-deliverable { background: #e7dcf6; } /* purple */
  .entry-meta { display: flex; gap: 10px; font-size: 13px; color: #555; align-items: baseline; }
  .entry-meta .source { font-weight: 600; color: #1f2937; }
  .entry-meta .stamp { margin-left: auto; display: flex; flex-direction: column; align-items: flex-end; line-height: 1.3; }
  .entry-meta .who { color: #777; }
  .entry-body { margin-top: 2px; }
  .entry-note .entry-body { font-style: italic; }
  .preserve-breaks { white-space: pre-wrap; }
  .err { color: #c00; padding: 0 24px; }

  /* Field diffs */
  .diff { margin: 1px 0; }
  .diff-field { font-weight: 600; color: #374151; }
  .diff-short .val { color: #111; }
  .diff-short .arrow { color: #9ca3af; }
  .diff-long { margin: 3px 0; }
  .ft-row { display: flex; gap: 8px; align-items: baseline; }
  .ft-label {
    flex: 0 0 2.5em; color: #6b7280; font-size: 11px;
    text-transform: uppercase; letter-spacing: 0.03em;
  }
  .ft-prev { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #374151; }

  /* Long-value popover */
  .pop-wrap { position: relative; display: inline-block; margin-top: 3px; }
  .pop-trigger { font-size: 12px; padding: 1px 8px; cursor: pointer; }
  .pop-backdrop {
    position: fixed; inset: 0; z-index: 40;
    background: transparent; border: 0; padding: 0; cursor: default;
  }
  .popover {
    position: absolute; top: calc(100% + 4px); left: 0; z-index: 50;
    width: min(480px, 80vw); max-height: 50vh; overflow: auto;
    background: #fff; border: 1px solid #cbd5e1; border-radius: 6px;
    box-shadow: 0 6px 20px rgba(0, 0, 0, 0.18); padding: 10px 12px;
  }
  .pop-section + .pop-section { margin-top: 8px; border-top: 1px solid #eee; padding-top: 8px; }
  .pop-label {
    font-size: 11px; text-transform: uppercase; letter-spacing: 0.03em;
    color: #6b7280; margin-bottom: 2px;
  }
  .pop-val { font-size: 13px; color: #111; }
</style>

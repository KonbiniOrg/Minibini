<script>
  import { viewMode } from '../stores/viewMode.js';

  let {
    history = null,
    emails = null,
    onAddNote = null,
  } = $props();

  let noteText = $state('');
  let expandedEmails = $state({});

  function toggleEmail(id) {
    expandedEmails = { ...expandedEmails, [id]: !expandedEmails[id] };
  }

  let timeline = $derived.by(() => {
    const entries = [];

    const histResults = history?.results || [];
    for (const h of histResults) {
      entries.push({ type: 'history', data: h, date: new Date(h.timestamp) });
    }

    const emailResults = emails?.results || [];
    for (const e of emailResults) {
      const tempEmail = e.temp_email;
      const date = tempEmail?.date_sent ? new Date(tempEmail.date_sent) : new Date(e.created_at);
      entries.push({ type: 'email', data: e, date });
    }

    entries.sort((a, b) => b.date - a.date);

    if ($viewMode === 'lite') {
      return entries.filter(e => e.type === 'email' || (e.type === 'history' && e.data.text));
    }
    return entries;
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
  {#if timeline.length > 0}
    {#each timeline as entry}
      {#if entry.type === 'history'}
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
      {:else if entry.type === 'email'}
        {@const email = entry.data}
        {@const temp = email.temp_email}
        <div class="history-email">
          <small class="history-date">{entry.date.toLocaleString()}</small>
          {#if temp}
            <div>
              <span class="email-icon">@</span>
              <span class="email-subject" onclick={() => toggleEmail(email.email_record_id)}
                    role="button" tabindex="0"
                    onkeydown={(e) => e.key === 'Enter' && toggleEmail(email.email_record_id)}>
                {temp.subject || '(no subject)'}
              </span>
            </div>
            <div class="email-from">{temp.from_email}</div>
            <div class="email-preview-container" class:open={expandedEmails[email.email_record_id]}>
              <div class="email-preview-inner">
                <div class="email-preview">
                  <div class="ep-header">To: {temp.to_email} · {entry.date.toLocaleString()}</div>
                  <div><a href="/core/email/{email.email_record_id}/">View full email</a></div>
                </div>
              </div>
            </div>
          {:else}
            <div>
              <span class="email-icon">@</span>
              <span>Email (details no longer cached)</span>
            </div>
            <div><a href="/core/email/{email.email_record_id}/">View full email</a></div>
          {/if}
        </div>
      {/if}
    {/each}
  {:else}
    <p>No history.</p>
  {/if}
</div>

<style>
  .history-scroll { overflow-y: auto; max-height: 280px; }
  .history-entry, .history-email { padding: 6px 0; border-bottom: 1px solid #f0f0f0; font-size: 13px; line-height: 1.4; }
  .history-date { color: #999; font-size: 11px; }
  .email-icon { display: inline-block; width: 16px; height: 16px; background: #dbeafe; border-radius: 3px; text-align: center; line-height: 16px; font-size: 10px; color: #2563eb; margin-right: 4px; vertical-align: middle; }
  .email-subject { color: #2563eb; cursor: pointer; font-weight: 500; }
  .email-subject:hover { text-decoration: underline; }
  .email-from { color: #666; font-size: 12px; }
  .email-preview-container { display: grid; grid-template-rows: 0fr; transition: grid-template-rows 0.2s ease; }
  .email-preview-container.open { grid-template-rows: 1fr; }
  .email-preview-inner { overflow: hidden; }
  .email-preview { margin-top: 6px; padding: 8px 10px; background: #fff; border: 1px solid #e5e7eb; border-radius: 4px; font-size: 12px; line-height: 1.5; }
  .ep-header { color: #888; font-size: 11px; margin-bottom: 4px; }
</style>

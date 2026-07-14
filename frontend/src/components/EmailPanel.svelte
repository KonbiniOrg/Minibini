<script>
  // showHeading renders the component's own <h3>Email</h3>. Callers that box
  // the panel with their own micro-cap head (the job context band) pass false.
  let { emails = null, showHeading = true } = $props();

  let items = $derived.by(() => {
    const results = emails?.results || [];
    return [...results].sort((a, b) => {
      const da = a.temp_email?.date_sent
        ? new Date(a.temp_email.date_sent)
        : new Date(a.created_at);
      const db = b.temp_email?.date_sent
        ? new Date(b.temp_email.date_sent)
        : new Date(b.created_at);
      return db - da;
    });
  });

  function shortDate(value) {
    if (!value) return '';
    const d = new Date(value);
    return d.toLocaleDateString();
  }
</script>

{#if showHeading}<h3>Email</h3>{/if}

<div class="email-scroll">
  {#if items.length > 0}
    {#each items as email}
      {@const temp = email.temp_email}
      {@const date = temp?.date_sent ? temp.date_sent : email.created_at}
      <a
        class="email-row"
        class:outbound={email.direction === 'outbound'}
        href="#/email/{email.email_record_id}"
      >
        <div class="row-head">
          <span class="date">{shortDate(date)}</span>
          <span class="arrow">{email.direction === 'outbound' ? '→' : '←'}</span>
          <span class="addr">{email.display_address || '(unknown)'}</span>
          <span class="subject">{temp?.subject || '(no subject)'}</span>
        </div>
        {#if email.snippet}
          <div class="snippet">{email.snippet}</div>
        {/if}
      </a>
    {/each}
  {:else}
    <p>No email associated with this job.</p>
  {/if}
</div>

<style>
  .email-scroll { overflow-y: auto; max-height: 280px; }
  .email-row {
    display: block;
    padding: 6px 8px;
    border-bottom: 1px solid #f0f0f0;
    font-size: 13px;
    line-height: 1.4;
    color: inherit;
    text-decoration: none;
  }
  .email-row:hover { background: #f9fafb; }
  .email-row.outbound { background: #f0f7ff; }
  .email-row.outbound:hover { background: #e0eefd; }
  .row-head {
    display: flex;
    gap: 6px;
    align-items: baseline;
  }
  .date { color: #999; font-size: 11px; flex: 0 0 auto; }
  .arrow { color: #888; flex: 0 0 auto; }
  .addr { color: #666; font-size: 12px; flex: 0 0 auto; max-width: 40%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .subject {
    color: #2563eb;
    font-weight: 500;
    flex: 1 1 auto;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .snippet {
    color: #555;
    font-size: 12px;
    margin-top: 2px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
</style>

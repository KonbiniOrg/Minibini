<script>
  const { content = null, tempEmail = null, emailRecord } = $props();

  function formatDate(val) {
    if (!val) return '';
    const d = new Date(val);
    if (isNaN(d)) return String(val);
    const pad = (n) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  }

  function joinList(v) {
    if (!v) return '';
    return Array.isArray(v) ? v.join(', ') : v;
  }
</script>

{#if content}
  <table border="1">
    <tbody>
      <tr><th>From:</th><td>{content.from || ''}</td></tr>
      <tr><th>To:</th><td>{joinList(content.to)}</td></tr>
      {#if content.cc && content.cc.length}
        <tr><th>CC:</th><td>{joinList(content.cc)}</td></tr>
      {/if}
      <tr><th>Date:</th><td>{formatDate(content.date)}</td></tr>
      <tr><th>Subject:</th><td><strong>{content.subject || ''}</strong></td></tr>
    </tbody>
  </table>

  <h3>Message Body</h3>
  {#if content.html}
    <div style="border: 1px solid; padding: 10px;">
      {@html content.html}
    </div>
  {:else if content.text}
    <pre style="border: 1px solid; padding: 10px; white-space: pre-wrap;">{content.text}</pre>
  {:else}
    <p><em>No message body available</em></p>
  {/if}

  {#if content.attachments && content.attachments.length}
    <h3>Attachments ({content.attachments.length})</h3>
    <ul>
      {#each content.attachments as att}
        <li>
          <strong>{att.filename}</strong>
          ({att.content_type}, {att.size} bytes)
        </li>
      {/each}
    </ul>
  {/if}
{:else if tempEmail}
  <p><strong>Email metadata available, but full content could not be retrieved from server.</strong></p>
  <table border="1">
    <tbody>
      <tr><th>From:</th><td>{tempEmail.from_email || ''}</td></tr>
      <tr><th>To:</th><td>{tempEmail.to_email || ''}</td></tr>
      {#if tempEmail.cc_email}
        <tr><th>CC:</th><td>{tempEmail.cc_email}</td></tr>
      {/if}
      <tr><th>Date:</th><td>{formatDate(tempEmail.date_sent)}</td></tr>
      <tr><th>Subject:</th><td><strong>{tempEmail.subject || ''}</strong></td></tr>
    </tbody>
  </table>
{:else}
  <p><strong>Email not found or could not be retrieved from server.</strong></p>
  <p>Message ID: {emailRecord?.message_id || ''}</p>
{/if}

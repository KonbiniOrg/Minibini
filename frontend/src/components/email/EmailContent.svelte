<script>
  const { content = null, tempEmail = null, emailRecord, contactLinks = {} } = $props();

  function formatDate(val) {
    if (!val) return '';
    const d = new Date(val);
    if (isNaN(d)) return String(val);
    const pad = (n) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  }

  // Pull the email part out of a "Name <email@host>" or bare-email string.
  function parseEmail(addr) {
    if (!addr) return '';
    const m = String(addr).match(/<([^>]+)>/);
    const email = (m ? m[1] : String(addr)).trim();
    return email.toLowerCase();
  }

  // Normalize the input — `content.to` / `content.cc` are arrays from the
  // IMAP service; the tempEmail fallback fields are comma-separated strings.
  function splitAddresses(v) {
    if (!v) return [];
    if (Array.isArray(v)) return v.filter(Boolean);
    return String(v).split(',').map(s => s.trim()).filter(Boolean);
  }
</script>

{#snippet addrCell(value)}
  {@const addrs = splitAddresses(value)}
  {#if addrs.length === 0}
    {''}
  {:else}
    {#each addrs as addr, i}
      {@const link = contactLinks[parseEmail(addr)]}
      {#if link}
        <a href="#/contacts/{link.contact_id}">{addr}</a>
      {:else}
        {addr}
      {/if}{#if i < addrs.length - 1}, {/if}
    {/each}
  {/if}
{/snippet}

{#if content}
  <table class="data-table">
    <tbody>
      <tr><th>From:</th><td>{@render addrCell(content.from)}</td></tr>
      <tr><th>To:</th><td>{@render addrCell(content.to)}</td></tr>
      {#if content.cc && content.cc.length}
        <tr><th>CC:</th><td>{@render addrCell(content.cc)}</td></tr>
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
  <table class="data-table">
    <tbody>
      <tr><th>From:</th><td>{@render addrCell(tempEmail.from_email)}</td></tr>
      <tr><th>To:</th><td>{@render addrCell(tempEmail.to_email)}</td></tr>
      {#if tempEmail.cc_email}
        <tr><th>CC:</th><td>{@render addrCell(tempEmail.cc_email)}</td></tr>
      {/if}
      <tr><th>Date:</th><td>{formatDate(tempEmail.date_sent)}</td></tr>
      <tr><th>Subject:</th><td><strong>{tempEmail.subject || ''}</strong></td></tr>
    </tbody>
  </table>
{:else}
  <p><strong>Email not found or could not be retrieved from server.</strong></p>
  <p>Message ID: {emailRecord?.message_id || ''}</p>
{/if}

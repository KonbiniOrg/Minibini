<script>
  const { emails = [] } = $props();

  function formatDate(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    const pad = (n) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }

  function truncate(text, words = 10) {
    if (!text) return '';
    const parts = text.split(/\s+/);
    return parts.length <= words ? text : parts.slice(0, words).join(' ') + '…';
  }
</script>

{#if emails.length === 0}
  <p>No emails found.</p>
{:else}
  <table border="1">
    <thead>
      <tr>
        <th>Date</th>
        <th>From</th>
        <th>Subject</th>
        <th>Job</th>
        <th>Attachments</th>
      </tr>
    </thead>
    <tbody>
      {#each emails as email}
        <tr>
          <td>{formatDate(email.temp_email?.date_sent)}</td>
          <td>{email.temp_email?.from_email || ''}</td>
          <td>
            <a href="#/email/{email.email_record_id}">
              {truncate(email.temp_email?.subject || '(no subject)')}
            </a>
          </td>
          <td>
            {#if email.job}
              <a href="#/jobs/{email.job}">{email.job_number || `Job #${email.job}`}</a>
            {:else}
              <em>None</em>
            {/if}
          </td>
          <td>{email.temp_email?.has_attachments ? 'Yes' : 'No'}</td>
        </tr>
      {/each}
    </tbody>
  </table>
{/if}

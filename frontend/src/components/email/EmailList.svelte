<script>
  import DataTable from '../DataTable.svelte';
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

<DataTable
  rows={emails}
  key={(email) => email.email_record_id}
  emptyText="No emails found."
  columns={[
    { id: 'date',        label: 'Date',        cell: dateCell },
    { id: 'from',        label: 'From',        cell: fromCell },
    { id: 'subject',     label: 'Subject',     cell: subjectCell },
    { id: 'job',         label: 'Job',         cell: jobCell },
    { id: 'attachments', label: 'Attachments', cell: attachmentsCell },
  ]}
/>

{#snippet dateCell(email)}{formatDate(email.temp_email?.date_sent)}{/snippet}
{#snippet fromCell(email)}{email.temp_email?.from_email || ''}{/snippet}
{#snippet subjectCell(email)}
  <a href="#/email/{email.email_record_id}">{truncate(email.temp_email?.subject || '(no subject)')}</a>
{/snippet}
{#snippet jobCell(email)}
  {#if email.job}
    <a href="#/jobs/{email.job}">{email.job_number || `Job #${email.job}`}</a>
  {:else}
    <em>None</em>
  {/if}
{/snippet}
{#snippet attachmentsCell(email)}{email.temp_email?.has_attachments ? 'Yes' : 'No'}{/snippet}

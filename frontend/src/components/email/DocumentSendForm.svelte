<script>
  // Shared compose form for sending Estimate / PO / Invoice documents.
  // The parent fetches sendDefaults, renders this form, owns the submit
  // handler that builds the FormData and POSTs to the document's send
  // endpoint. The auto-generated PDF preview comes from sendDefaults and
  // can be removed (it'll just not be re-attached at submit).

  let {
    sendDefaults,         // { to, subject, body, attachments_preview: [{filename, content_type, size}, ...] }
    submitLabel = 'Send Email',
    onSubmit,             // function({ to, subject, body, cc, bcc, includeAutoAttachments: [bool...], extraFiles: [File...] })
    submitError = null,
    submitting = false,
  } = $props();

  let to = $state(sendDefaults?.to || '');
  let cc = $state(sendDefaults?.cc || '');
  let bcc = $state(sendDefaults?.bcc || '');
  let subject = $state(sendDefaults?.subject || '');
  let body = $state(sendDefaults?.body || '');

  // Which auto-attached PDFs to include (default all checked).
  let includeAutoAttachments = $state(
    (sendDefaults?.attachments_preview || []).map(() => true),
  );

  // User-uploaded files (held in form state until submit).
  let extraFiles = $state([]);

  function onFileChange(event) {
    const files = Array.from(event.target.files || []);
    extraFiles = [...extraFiles, ...files];
    event.target.value = '';
  }

  function removeExtra(index) {
    extraFiles = extraFiles.filter((_, i) => i !== index);
  }

  function toggleAutoAttachment(index) {
    includeAutoAttachments = includeAutoAttachments.map((v, i) => (i === index ? !v : v));
  }

  async function handleSubmit(e) {
    e.preventDefault();
    if (!to.trim()) return;
    const recipient = to.trim();
    if (!confirm(`Send this email to ${recipient}?`)) return;
    onSubmit({
      to: recipient,
      cc: cc.trim(),
      bcc: bcc.trim(),
      subject,
      body,
      includeAutoAttachments,
      extraFiles,
    });
  }

  function fmtSize(bytes) {
    if (!bytes) return '';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }
</script>

<form onsubmit={handleSubmit}>
  {#if submitError}
    <p class="send-error"><strong>Error:</strong> {submitError}</p>
  {/if}

  <p>
    <label for="to"><strong>To *</strong></label><br>
    <input type="email" id="to" bind:value={to} required>
  </p>
  <p>
    <label for="cc"><strong>CC</strong></label><br>
    <input type="text" id="cc" bind:value={cc} placeholder="Comma-separated emails">
  </p>
  <p>
    <label for="bcc"><strong>BCC</strong></label><br>
    <input type="text" id="bcc" bind:value={bcc} placeholder="Comma-separated emails">
  </p>
  <p>
    <label for="subject"><strong>Subject</strong></label><br>
    <input type="text" id="subject" bind:value={subject}>
  </p>
  <p>
    <label for="body"><strong>Body</strong></label><br>
    <textarea id="body" bind:value={body} rows="12" cols="70"></textarea>
  </p>

  {#if (sendDefaults?.attachments_preview || []).length > 0 || extraFiles.length > 0}
    <fieldset>
      <legend><strong>Attachments</strong></legend>
      {#each sendDefaults?.attachments_preview || [] as att, i}
        <p>
          <label>
            <input type="checkbox" checked={includeAutoAttachments[i]}
                   onchange={() => toggleAutoAttachment(i)}>
            {att.filename} ({att.content_type})
          </label>
        </p>
      {/each}
      {#each extraFiles as file, i}
        <p>
          {file.name} ({file.type || 'file'}, {fmtSize(file.size)})
          <button type="button" onclick={() => removeExtra(i)}>Remove</button>
        </p>
      {/each}
      <p>
        <label for="extra_attachments"><strong>Add attachment</strong></label><br>
        <input type="file" id="extra_attachments" multiple onchange={onFileChange}>
      </p>
    </fieldset>
  {/if}

  <p>
    <button type="submit" disabled={submitting || !to.trim()}>
      {submitting ? 'Sending…' : submitLabel}
    </button>
  </p>
</form>

<style>
  .send-error { color: #b91c1c; }
</style>

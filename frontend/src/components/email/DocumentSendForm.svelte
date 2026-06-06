<script>
  // Shared compose form for outbound email — sending Estimate / PO / Invoice
  // documents AND the inline Reply / Reply All composer.
  //
  // The form's text fields are $bindable so the parent can own the state.
  // Document-send pages don't bind; they let each field default from
  // sendDefaults and receive the values back through onSubmit's payload.
  // The reply composer DOES bind them — that's how mode switching
  // (Reply <-> Reply All) updates the CC field without remounting the form
  // or losing what the user has typed elsewhere.

  let {
    sendDefaults,         // { to, cc, bcc, subject, body, attachments_preview: [{filename, content_type, size}, ...] }
    to = $bindable(sendDefaults?.to || ''),
    cc = $bindable(sendDefaults?.cc || ''),
    bcc = $bindable(sendDefaults?.bcc || ''),
    subject = $bindable(sendDefaults?.subject || ''),
    body = $bindable(sendDefaults?.body || ''),
    extraFiles = $bindable([]),
    submitLabel = 'Send Email',
    onSubmit,             // function({ to, subject, body, cc, bcc, includeAutoAttachments: [bool...], extraFiles: [File...] })
    submitError = null,
    submitting = false,
  } = $props();

  // Which auto-attached PDFs to include (default all checked).
  let includeAutoAttachments = $state(
    (sendDefaults?.attachments_preview || []).map(() => true),
  );

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
    <input type="text" id="to" class="form-input" bind:value={to} placeholder="Comma-separated emails" required>
  </p>
  <p>
    <label for="cc"><strong>CC</strong></label><br>
    <input type="text" id="cc" class="form-input" bind:value={cc} placeholder="Comma-separated emails">
  </p>
  <p>
    <label for="bcc"><strong>BCC</strong></label><br>
    <input type="text" id="bcc" class="form-input" bind:value={bcc} placeholder="Comma-separated emails">
  </p>
  <p>
    <label for="subject"><strong>Subject</strong></label><br>
    <input type="text" id="subject" class="form-input" bind:value={subject}>
  </p>
  <p>
    <label for="body"><strong>Body</strong></label><br>
    <textarea id="body" class="form-input" bind:value={body} rows="12"></textarea>
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
  .form-input {
    width: 100%;
    max-width: 720px;
    box-sizing: border-box;
    font-family: inherit;
    font-size: 14px;
    padding: 4px 6px;
  }
  textarea.form-input {
    font-family: monospace;
  }
</style>

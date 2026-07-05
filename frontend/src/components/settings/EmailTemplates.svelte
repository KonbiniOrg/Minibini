<script>
  import { api } from '../../lib/api.js';
  import { triageError } from '../../lib/errorTriage.js';
  import { showError } from '../../stores/messages.js';
  import FormMessage from '../FormMessage.svelte';

  // The 8 boilerplate Configuration keys (4 document types × subject + body).
  // The backend service for each document type falls back to a built-in
  // default when the Configuration row is absent. We pre-fill the field with
  // that default text so the user can edit in place. (These defaults must
  // stay in sync with the *_BODY / *_SUBJECT constants in the matching backend
  // services.)

  const TEMPLATES = [
    {
      label: 'Estimate',
      subject: {
        key: 'estimate_email_subject_template',
        default: 'Estimate {document_number}',
      },
      body: {
        key: 'estimate_email_body_template',
        default:
          'Hi {contact_fname},\n\n' +
          'Please find attached our estimate {document_number} for {job_name}. ' +
          'Let us know if you have any questions.\n\n' +
          'Thanks,\n{my_user_name}',
      },
    },
    {
      label: 'Purchase Order',
      subject: {
        key: 'po_email_subject_template',
        default: 'Purchase Order {po_number}',
      },
      body: {
        key: 'po_email_body_template',
        default:
          'Please find attached Purchase Order {po_number}.\n\n' +
          'If you have any questions, please contact us.\n\n' +
          'Thank you.',
      },
    },
    {
      label: 'Invoice',
      subject: {
        key: 'invoice_email_subject_template',
        default: 'Invoice {document_number} for {job_number}',
      },
      body: {
        key: 'invoice_email_body_template',
        default:
          'Hi {contact_fname},\n\n' +
          'Please find attached your invoice {document_number} for {job_name}. ' +
          'The invoice includes a Pay Now link.\n\n' +
          'Thanks,\n{my_user_name}',
      },
    },
    {
      label: 'Change Order',
      subject: {
        key: 'change_order_email_subject_template',
        default: 'Change order {document_number}',
      },
      body: {
        key: 'change_order_email_body_template',
        default:
          'Hi {contact_fname},\n\n' +
          'We have a change to estimate {estimate_number} for {job_name}. ' +
          'You can review and approve the change online here:\n' +
          '{object_url}\n\n' +
          'Let us know if you have any questions.\n\n' +
          'Thanks,\n{my_user_name}',
      },
    },
  ];

  // Variables documentation, shown at the top so it's visible while editing.
  // Per-document-type aliases (estimate_number / po_number / vendor_name /
  // invoice_number) also work — noted in a small footer below the table.
  const COMMON_VARS = [
    ['{contact_fname}', 'Recipient first name'],
    ['{contact_lname}', 'Recipient last name'],
    ['{contact_business}', 'Recipient business name (blank if none)'],
    ['{my_user_name}', 'Sending user’s first name'],
    ['{job_number}', 'Job number (Estimate / Invoice only)'],
    ['{job_name}', 'Job name (Estimate / Invoice only)'],
    ['{document_number}', 'The document’s own number (EST-…, PO-…, INV-…)'],
    ['{object_url}', 'Customer-facing URL for the document (stub today; see LATER.md)'],
  ];

  const RETENTION_KEY = 'email_retention_days';
  const RETENTION_DEFAULT = '90';
  const DISPLAY_LIMIT_KEY = 'email_display_limit';
  const DISPLAY_LIMIT_DEFAULT = '30';

  let values = $state({});      // {key: stored value}
  let saving = $state({});      // {key: bool}
  let savedFlash = $state({});  // {key: timestamp ms of last successful save}
  let saveErrors = $state({});  // {key: form-footer error message}
  let loadError = $state(null);
  let loading = $state(true);

  async function load() {
    loading = true;
    loadError = null;
    try {
      const all = await api.get('/api/settings/');
      const next = {};
      // Pre-fill with the built-in default when no Configuration row
      // exists; the user edits in place instead of starting from blank.
      for (const t of TEMPLATES) {
        next[t.subject.key] = all[t.subject.key] ?? t.subject.default;
        next[t.body.key] = all[t.body.key] ?? t.body.default;
      }
      next[RETENTION_KEY] = all[RETENTION_KEY] ?? RETENTION_DEFAULT;
      next[DISPLAY_LIMIT_KEY] = all[DISPLAY_LIMIT_KEY] ?? DISPLAY_LIMIT_DEFAULT;
      values = next;
    } catch (e) {
      loadError = e.message;
    } finally {
      loading = false;
    }
  }

  async function save(key) {
    saving = { ...saving, [key]: true };
    saveErrors = { ...saveErrors, [key]: '' };
    try {
      await api.patch('/api/settings/', { [key]: values[key] });
      savedFlash = { ...savedFlash, [key]: Date.now() };
    } catch (e) {
      const t = triageError(e);
      if (t.overlay) {
        showError(t.overlay);
      } else {
        // Field-keyed errors come back keyed by the config key itself —
        // fold them into this key's footer message.
        const fieldText = Object.values(t.fields).flat().join(' ');
        saveErrors = {
          ...saveErrors,
          [key]: [t.message, fieldText].filter(Boolean).join(' ') || 'Save failed.',
        };
      }
    } finally {
      saving = { ...saving, [key]: false };
    }
  }

  function flashVisible(key) {
    const t = savedFlash[key];
    if (!t) return false;
    return (Date.now() - t) < 3000;
  }

  load();
</script>

<section>
  {#if !loading && !loadError}
    <fieldset class="template-block">
      <legend><strong>Retention</strong></legend>
      <p>
        <label for={RETENTION_KEY}><strong>Purge emails older than</strong></label>
        <input
          type="number"
          id={RETENTION_KEY}
          min="1"
          class="retention-input"
          bind:value={values[RETENTION_KEY]}
        >
        days
      </p>
      <p>
        <small>
          For emails linked to a Job, Purchase Order, or Bill, the clock
          starts when that record reaches a final status (e.g. completed,
          cancelled, paid in full) — not when the email itself was received.
          Linked records that are still active hold their emails
          indefinitely.
        </small>
      </p>
      <p>
        <button type="button"
                onclick={() => save(RETENTION_KEY)}
                disabled={saving[RETENTION_KEY]}>
          {saving[RETENTION_KEY] ? 'Saving…' : 'Save retention'}
        </button>
        {#if flashVisible(RETENTION_KEY)}<em class="ok">saved</em>{/if}
      </p>
      <FormMessage error={saveErrors[RETENTION_KEY]} />

      <p>
        <label for={DISPLAY_LIMIT_KEY}><strong>Show at most</strong></label>
        <input
          type="number"
          id={DISPLAY_LIMIT_KEY}
          min="1"
          class="retention-input"
          bind:value={values[DISPLAY_LIMIT_KEY]}
        >
        emails in the inbox
      </p>
      <p>
        <button type="button"
                onclick={() => save(DISPLAY_LIMIT_KEY)}
                disabled={saving[DISPLAY_LIMIT_KEY]}>
          {saving[DISPLAY_LIMIT_KEY] ? 'Saving…' : 'Save display limit'}
        </button>
        {#if flashVisible(DISPLAY_LIMIT_KEY)}<em class="ok">saved</em>{/if}
      </p>
      <FormMessage error={saveErrors[DISPLAY_LIMIT_KEY]} />
    </fieldset>
  {/if}

  <h3>Email Templates</h3>
  <p>
    Boilerplate subject and body used when sending an Estimate, Purchase Order,
    Invoice, or Change Order via email.
  </p>

  <fieldset class="template-block">
    <legend><strong>Available variables</strong></legend>
    <table class="vars">
      <tbody>
        {#each COMMON_VARS as [name, desc]}
          <tr><th><code>{name}</code></th><td>{desc}</td></tr>
        {/each}
      </tbody>
    </table>
    <p>
      <small>
        Per-document aliases also work: <code>{'{estimate_number}'}</code> on the
        Estimate template, <code>{'{po_number}'}</code> /
        <code>{'{vendor_name}'}</code> on the Purchase Order template,
        <code>{'{invoice_number}'}</code> on the Invoice template, and
        <code>{'{change_order_number}'}</code> / <code>{'{estimate_number}'}</code> /
        <code>{'{object_url}'}</code> (the customer portal link) on the Change
        Order template. Unknown
        placeholders render literally (no crashes), so it is safe to try one
        and check the result on a Send page.
      </small>
    </p>
  </fieldset>

  {#if loading}
    <p>Loading templates&hellip;</p>
  {:else if loadError}
    <p class="error">Could not load settings: {loadError}</p>
  {:else}
    {#each TEMPLATES as t (t.label)}
      <fieldset class="template-block">
        <legend><strong>{t.label}</strong></legend>

        <p>
          <label for={t.subject.key}><strong>Subject</strong></label><br>
          <input
            type="text"
            id={t.subject.key}
            class="template-input"
            bind:value={values[t.subject.key]}
          >
        </p>
        <p>
          <button type="button"
                  onclick={() => save(t.subject.key)}
                  disabled={saving[t.subject.key]}>
            {saving[t.subject.key] ? 'Saving…' : 'Save subject'}
          </button>
          {#if flashVisible(t.subject.key)}<em class="ok">saved</em>{/if}
        </p>
        <FormMessage error={saveErrors[t.subject.key]} />

        <p>
          <label for={t.body.key}><strong>Body</strong></label><br>
          <textarea
            id={t.body.key}
            class="template-textarea"
            rows="8"
            bind:value={values[t.body.key]}
          ></textarea>
        </p>
        <p>
          <button type="button"
                  onclick={() => save(t.body.key)}
                  disabled={saving[t.body.key]}>
            {saving[t.body.key] ? 'Saving…' : 'Save body'}
          </button>
          {#if flashVisible(t.body.key)}<em class="ok">saved</em>{/if}
        </p>
        <FormMessage error={saveErrors[t.body.key]} />
      </fieldset>
    {/each}
  {/if}
</section>

<style>
  .template-block {
    margin-bottom: 16px;
    border: 1px solid #d1d5db;
    padding: 12px;
    border-radius: 4px;
  }
  .template-input,
  .template-textarea {
    width: 100%;
    max-width: 720px;
    box-sizing: border-box;
    font-family: inherit;
    font-size: 14px;
    padding: 4px 6px;
  }
  .template-textarea {
    font-family: monospace;
  }
  .retention-input {
    width: 5em;
    font-family: inherit;
    font-size: 14px;
    padding: 2px 4px;
    margin: 0 4px;
  }
  .ok { color: #047857; margin-left: 8px; }
  .error { color: #b91c1c; }
  .vars { border-collapse: collapse; }
  .vars th, .vars td { padding: 2px 12px 2px 0; text-align: left; font-weight: normal; }
  .vars th code { font-weight: bold; }
</style>

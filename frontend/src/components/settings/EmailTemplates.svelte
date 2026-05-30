<script>
  import { api } from '../../lib/api.js';

  // The 6 boilerplate Configuration keys. The backend service for each
  // document type falls back to a built-in default when the Configuration
  // row is absent — those defaults are shown as placeholder hints below
  // each field so the user knows what to expect if they leave it blank.

  const TEMPLATES = [
    {
      label: 'Estimate',
      subject: {
        key: 'estimate_email_subject_template',
        default: 'Estimate {document_number} from {our_business_name}',
      },
      body: {
        key: 'estimate_email_body_template',
        default:
          'Hi {contact_fname},\n\n' +
          'Please find attached our estimate {document_number} for {job_name}. ' +
          'Let us know if you have any questions.\n\n' +
          'Thanks,\n{our_user_name}',
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
          'Thanks,\n{our_user_name}',
      },
    },
  ];

  // Variables list for the helper section below. Per-document-type aliases
  // (estimate_number / po_number / invoice_number / vendor_name) are
  // captured in a note so the table stays compact.
  const COMMON_VARS = [
    ['{contact_fname}', 'Recipient first name'],
    ['{contact_lname}', 'Recipient last name'],
    ['{contact_business}', 'Recipient business name (blank if none)'],
    ['{our_business_name}', 'Our business name (from Configuration)'],
    ['{our_user_name}', 'Sending user’s first name'],
    ['{job_number}', 'Job number (Estimate / Invoice only)'],
    ['{job_name}', 'Job name (Estimate / Invoice only)'],
    ['{document_number}', 'The document’s own number (EST-…, PO-…, INV-…)'],
    ['{object_url}', 'Customer-facing URL for the document (stub today; see LATER.md)'],
  ];

  let values = $state({});      // {key: stored value}
  let saving = $state({});      // {key: bool}
  let savedFlash = $state({});  // {key: timestamp ms of last successful save}
  let loadError = $state(null);
  let loading = $state(true);

  async function load() {
    loading = true;
    loadError = null;
    try {
      const all = await api.get('/api/settings/');
      const next = {};
      for (const t of TEMPLATES) {
        next[t.subject.key] = all[t.subject.key] ?? '';
        next[t.body.key] = all[t.body.key] ?? '';
      }
      values = next;
    } catch (e) {
      loadError = e.message;
    } finally {
      loading = false;
    }
  }

  async function save(key) {
    saving = { ...saving, [key]: true };
    try {
      await api.patch('/api/settings/', { [key]: values[key] });
      savedFlash = { ...savedFlash, [key]: Date.now() };
    } catch (e) {
      alert(`Save failed: ${e.message}`);
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
  <h3>Email Templates</h3>
  <p>
    Boilerplate subject and body used when sending an Estimate, Purchase Order, or
    Invoice via email. Leave a field blank to use the built-in default shown as
    the placeholder. Each field has its own Save button.
  </p>

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
            placeholder={t.subject.default}
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

        <p>
          <label for={t.body.key}><strong>Body</strong></label><br>
          <textarea
            id={t.body.key}
            class="template-textarea"
            rows="8"
            bind:value={values[t.body.key]}
            placeholder={t.body.default}
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
      </fieldset>
    {/each}

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
          <code>{'{vendor_name}'}</code> on the Purchase Order template, and
          <code>{'{invoice_number}'}</code> on the Invoice template. Unknown
          placeholders render literally (no crashes), so it is safe to try one
          and check the result on a Send page.
        </small>
      </p>
    </fieldset>
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
  .ok { color: #047857; margin-left: 8px; }
  .error { color: #b91c1c; }
  .vars { border-collapse: collapse; }
  .vars th, .vars td { padding: 2px 12px 2px 0; text-align: left; font-weight: normal; }
  .vars th code { font-weight: bold; }
</style>

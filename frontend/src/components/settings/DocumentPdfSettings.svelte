<script>
  import { api } from '../../lib/api.js';
  import { triageError } from '../../lib/errorTriage.js';
  import { showError } from '../../stores/messages.js';
  import FormMessage from '../FormMessage.svelte';
  import FieldError from '../FieldError.svelte';

  // Branding for the three locally rendered document PDFs. The letterhead
  // (logo + company block) is shared; each document has its own four text
  // slots. Keys mirror apps/core/pdf_branding.py — `<kind>_pdf_text_<slot>`.

  const LOGO_URL = '/api/settings/pdf-logo/';
  const POSITION_KEY = 'pdf_logo_position';
  const POSITIONS = [['left', 'Left'], ['center', 'Center'], ['right', 'Right']];
  const COMPANY_KEYS = [
    'pdf_company_name', 'pdf_company_address', 'pdf_company_phone', 'pdf_company_email',
  ];
  const LETTERHEAD = 'letterhead';

  const DOCUMENTS = [
    { kind: 'estimate', label: 'Estimate' },
    { kind: 'change_order', label: 'Change Order' },
    { kind: 'po', label: 'Purchase Order' },
  ];
  const SLOTS = [
    ['below_header', 'Below the header', 'Printed under the document title, above the customer / vendor block.'],
    ['above_lines', 'Above the line items', 'Printed just before the line table.'],
    ['below_totals', 'Below the totals', 'Printed after the totals — terms, validity, a signature line.'],
    ['page_footer', 'Page footer', 'Repeated at the bottom of every page.'],
  ];

  const VARS = [
    ['{contact_fname}', 'Recipient first name'],
    ['{contact_lname}', 'Recipient last name'],
    ['{contact_business}', 'Recipient business name (blank if none)'],
    ['{document_number}', 'The document’s own number (EST-…, CO-…, PO-…)'],
    ['{job_number}', 'Job number (Estimate / Change Order only)'],
    ['{job_name}', 'Job name (Estimate / Change Order only)'],
    ['{object_url}', 'Customer portal link (Estimate / Change Order only)'],
    ['{page}', 'Current page number (page footer only)'],
    ['{page_count}', 'Total number of pages (page footer only)'],
  ];

  const textKey = (kind, slot) => `${kind}_pdf_text_${slot}`;
  const slotKeys = (kind) => SLOTS.map(([slot]) => textKey(kind, slot));

  let values = $state({});      // {key: stored value}
  let logo = $state('');        // data URI, '' when unset
  let logoFile = $state(null);
  let logoErrors = $state({});
  let logoBusy = $state(false);
  let saving = $state({});      // {group: bool}
  let savedFlash = $state({});  // {group: timestamp ms of last successful save}
  let saveErrors = $state({});  // {group: form-footer error message}
  let loadError = $state(null);
  let loading = $state(true);

  async function load() {
    loading = true;
    loadError = null;
    try {
      const [all, logoData] = await Promise.all([
        api.get('/api/settings/'), api.get(LOGO_URL),
      ]);
      const next = { [POSITION_KEY]: all[POSITION_KEY] ?? 'left' };
      for (const key of COMPANY_KEYS) next[key] = all[key] ?? '';
      for (const doc of DOCUMENTS) {
        for (const key of slotKeys(doc.kind)) next[key] = all[key] ?? '';
      }
      values = next;
      logo = logoData.logo ?? '';
    } catch (e) {
      loadError = e.message;
    } finally {
      loading = false;
    }
  }

  // Save one group (the letterhead, or one document's text) in a single PATCH.
  async function saveGroup(group, keys) {
    saving = { ...saving, [group]: true };
    saveErrors = { ...saveErrors, [group]: '' };
    try {
      await api.patch('/api/settings/', Object.fromEntries(keys.map((k) => [k, values[k]])));
      savedFlash = { ...savedFlash, [group]: Date.now() };
    } catch (e) {
      const t = triageError(e);
      if (t.overlay) {
        showError(t.overlay);
      } else {
        // Field-keyed errors come back keyed by the config key itself —
        // fold them into this group's footer message.
        const fieldText = Object.values(t.fields).flat().join(' ');
        saveErrors = {
          ...saveErrors,
          [group]: [t.message, fieldText].filter(Boolean).join(' ') || 'Save failed.',
        };
      }
    } finally {
      saving = { ...saving, [group]: false };
    }
  }

  function flashVisible(group) {
    const t = savedFlash[group];
    if (!t) return false;
    return (Date.now() - t) < 3000;
  }

  async function uploadLogo() {
    logoErrors = {};
    if (!logoFile) {
      logoErrors = { logo: ['Choose an image file to upload.'] };
      return;
    }
    logoBusy = true;
    try {
      const fd = new FormData();
      fd.append('logo', logoFile);
      const result = await api.postMultipart(LOGO_URL, fd);
      logo = result.logo;
      logoFile = null;
    } catch (e) {
      const t = triageError(e);
      if (t.overlay) showError(t.overlay);
      else logoErrors = t.message ? { logo: [t.message] } : t.fields;
    } finally {
      logoBusy = false;
    }
  }

  async function removeLogo() {
    logoErrors = {};
    logoBusy = true;
    try {
      await api.delete(LOGO_URL);
      logo = '';
    } catch (e) {
      const t = triageError(e);
      if (t.overlay) showError(t.overlay);
      else logoErrors = { logo: [t.message || 'Could not remove the logo.'] };
    } finally {
      logoBusy = false;
    }
  }

  load();
</script>

<section>
  <h3>Document PDFs</h3>
  <p>
    Branding for the PDF attached when an Estimate, Change Order, or Purchase
    Order is emailed. Invoices attach the PDF QuickBooks renders, so their
    look is set in QuickBooks.
  </p>

  {#if loading}
    <p>Loading document settings&hellip;</p>
  {:else if loadError}
    <p class="error">Could not load settings: {loadError}</p>
  {:else}
    <fieldset class="block">
      <legend><strong>Letterhead</strong></legend>
      <p><small>Shared by all three documents. Anything left blank is not printed.</small></p>

      {#if logo}
        <p><img class="logo-preview" src={logo} alt="Current logo"></p>
      {:else}
        <p><em>No logo uploaded.</em></p>
      {/if}
      <p>
        <label for="pdf_logo_file"><strong>Logo image</strong></label><br>
        <input
          type="file"
          id="pdf_logo_file"
          accept="image/png,image/jpeg"
          onchange={(e) => { logoFile = e.currentTarget.files?.[0] ?? null; }}
        >
      </p>
      <FieldError errors={logoErrors} field="logo" />
      <p><small>PNG or JPEG, 1 MB or smaller.</small></p>
      <p>
        <button type="button" onclick={uploadLogo} disabled={logoBusy}>
          {logoBusy ? 'Working…' : 'Upload logo'}
        </button>
        {#if logo}
          <button type="button" onclick={removeLogo} disabled={logoBusy}>Remove logo</button>
        {/if}
      </p>

      <p>
        <strong>Logo position</strong><br>
        {#each POSITIONS as [value, label]}
          <label class="radio">
            <input type="radio" name="pdf_logo_position" {value}
                   bind:group={values[POSITION_KEY]}>
            {label}
          </label>
        {/each}
      </p>

      <p>
        <label for="pdf_company_name"><strong>Company name</strong></label><br>
        <input type="text" id="pdf_company_name" class="text-input"
               bind:value={values.pdf_company_name}>
      </p>
      <p>
        <label for="pdf_company_address"><strong>Address</strong></label><br>
        <textarea id="pdf_company_address" class="text-area" rows="3"
                  bind:value={values.pdf_company_address}></textarea>
      </p>
      <p>
        <label for="pdf_company_phone"><strong>Phone</strong></label><br>
        <input type="text" id="pdf_company_phone" class="text-input"
               bind:value={values.pdf_company_phone}>
      </p>
      <p>
        <label for="pdf_company_email"><strong>Email</strong></label><br>
        <input type="text" id="pdf_company_email" class="text-input"
               bind:value={values.pdf_company_email}>
      </p>
      <p>
        <button type="button"
                onclick={() => saveGroup(LETTERHEAD, [POSITION_KEY, ...COMPANY_KEYS])}
                disabled={saving[LETTERHEAD]}>
          {saving[LETTERHEAD] ? 'Saving…' : 'Save letterhead'}
        </button>
        {#if flashVisible(LETTERHEAD)}<em class="ok">saved</em>{/if}
      </p>
      <FormMessage error={saveErrors[LETTERHEAD]} />
    </fieldset>

    <fieldset class="block">
      <legend><strong>Available variables</strong></legend>
      <table class="vars">
        <tbody>
          {#each VARS as [name, desc]}
            <tr><th><code>{name}</code></th><td>{desc}</td></tr>
          {/each}
        </tbody>
      </table>
      <p>
        <small>
          Usable in any text box below. <code>{'{estimate_number}'}</code>,
          <code>{'{change_order_number}'}</code>, <code>{'{po_number}'}</code>
          and <code>{'{vendor_name}'}</code> also work on their own documents.
          An unknown variable prints exactly as typed, so check the preview
          after saving.
        </small>
      </p>
    </fieldset>

    {#each DOCUMENTS as doc (doc.kind)}
      <fieldset class="block">
        <legend><strong>{doc.label}</strong></legend>
        {#each SLOTS as [slot, label, hint]}
          <p>
            <label for={textKey(doc.kind, slot)}><strong>{label}</strong></label><br>
            <textarea
              id={textKey(doc.kind, slot)}
              class="text-area"
              rows={slot === 'page_footer' ? 2 : 4}
              bind:value={values[textKey(doc.kind, slot)]}
            ></textarea><br>
            <small>{hint}</small>
          </p>
        {/each}
        <p>
          <button type="button"
                  onclick={() => saveGroup(doc.kind, slotKeys(doc.kind))}
                  disabled={saving[doc.kind]}>
            {saving[doc.kind] ? 'Saving…' : `Save ${doc.label} text`}
          </button>
          {#if flashVisible(doc.kind)}<em class="ok">saved</em>{/if}
          <a class="preview" href={`/api/settings/pdf-preview/?document=${doc.kind}`}
             target="_blank" rel="noopener">Preview {doc.label} PDF</a>
        </p>
        <FormMessage error={saveErrors[doc.kind]} />
        <p><small>The preview is a sample document using the saved settings — save first.</small></p>
      </fieldset>
    {/each}
  {/if}
</section>

<style>
  .block {
    margin-bottom: 16px;
    border: 1px solid #d1d5db;
    padding: 12px;
    border-radius: 4px;
  }
  .text-input,
  .text-area {
    width: 100%;
    max-width: 720px;
    box-sizing: border-box;
    font-family: inherit;
    font-size: 14px;
    padding: 4px 6px;
  }
  .logo-preview {
    max-height: 80px;
    max-width: 240px;
    border: 1px solid #d1d5db;
  }
  .radio { margin-right: 16px; }
  .preview { margin-left: 16px; }
  .ok { color: #047857; margin-left: 8px; }
  .error { color: #b91c1c; }
  .vars { border-collapse: collapse; }
  .vars th, .vars td { padding: 2px 12px 2px 0; text-align: left; font-weight: normal; }
  .vars th code { font-weight: bold; }
</style>

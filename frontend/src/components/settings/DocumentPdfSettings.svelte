<script>
  import { onDestroy } from 'svelte';
  import { api, errorMessage } from '../../lib/api.js';
  import { triageError } from '../../lib/errorTriage.js';
  import { showError } from '../../stores/messages.js';
  import FormMessage from '../FormMessage.svelte';
  import LoadState from '../LoadState.svelte';
  import FieldError from '../FieldError.svelte';
  import RichTextEditor from '../RichTextEditor.svelte';

  // Branding for the three locally rendered document PDFs. The letterhead
  // (logo + company block) is shared; each document has its own four text
  // slots. Keys mirror apps/core/pdf_branding.py — `<kind>_pdf_text_<slot>`.
  //
  // Each document shows a live preview beside its form: after a pause in
  // typing, the unsaved letterhead + that document's text go to the preview
  // endpoint, which renders the real PDF and returns its pages as images.
  // Previewing never saves — the Save buttons still do that.

  // Wait this long after the last edit before requesting a preview (tests
  // pass 0).
  let { previewDelay = 500 } = $props();

  const LOGO_URL = '/api/settings/pdf-logo/';
  const PREVIEW_URL = '/api/settings/pdf-preview/';
  const POSITION_KEY = 'pdf_logo_position';
  const POSITIONS = [['left', 'Left'], ['center', 'Center'], ['right', 'Right']];
  const COMPANY_KEYS = [
    'pdf_company_name', 'pdf_company_address', 'pdf_company_phone', 'pdf_company_email',
  ];
  // [key, label, singleLine] — all rich text, like the document slots.
  const COMPANY_FIELDS = [
    ['pdf_company_name', 'Company name', true],
    ['pdf_company_address', 'Address', false],
    ['pdf_company_phone', 'Phone', true],
    ['pdf_company_email', 'Email', true],
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
  // Every preview window: the letterhead's own (its band cropped from the top
  // of a page), then each document's sample.
  const PREVIEWS = [
    { kind: LETTERHEAD, label: 'Letterhead', caption: 'the top of every document' },
    ...DOCUMENTS.map((doc) => ({ ...doc, caption: `sample ${doc.label.toLowerCase()}` })),
  ];
  // The keys a preview takes as drafts (pdf_branding.preview_draft_keys).
  const previewKeys = (kind) => (kind === LETTERHEAD
    ? [POSITION_KEY, ...COMPANY_KEYS]
    : [POSITION_KEY, ...COMPANY_KEYS, ...slotKeys(kind)]);

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
  // {kind: {pages: [PNG data URI], pdfUrl: blob URL, rendered, loading, error}}
  let previews = $state(Object.fromEntries(PREVIEWS.map((p) => [
    p.kind, { pages: [], pdfUrl: '', rendered: false, loading: false, error: '' },
  ])));
  const previewTimers = {};
  const previewSeq = {};    // latest request number per kind; older replies are dropped

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
      loadError = errorMessage(e, 'Could not load the document settings.');
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

  // A data: URI can't be opened as a top-level tab, so the full-size PDF is
  // served from a blob URL instead.
  function pdfBlobUrl(dataUri) {
    const bytes = Uint8Array.from(atob(dataUri.split(',', 2)[1]), (c) => c.charCodeAt(0));
    return URL.createObjectURL(new Blob([bytes], { type: 'application/pdf' }));
  }

  async function refreshPreview(kind, drafts) {
    const seq = (previewSeq[kind] ?? 0) + 1;
    previewSeq[kind] = seq;
    previews[kind].loading = true;
    try {
      const result = await api.post(PREVIEW_URL, { document: kind, values: drafts });
      if (seq !== previewSeq[kind]) return;
      const old = previews[kind].pdfUrl;
      previews[kind].pdfUrl = pdfBlobUrl(result.pdf);
      if (old) URL.revokeObjectURL(old);
      previews[kind].pages = result.pages;
      previews[kind].rendered = true;
      previews[kind].error = '';
    } catch (e) {
      if (seq !== previewSeq[kind]) return;
      const t = triageError(e);
      // Shown in the preview pane, never the overlay: a preview fires on
      // every pause in typing, and a dead server would otherwise stack popups.
      previews[kind].error = t.overlay || t.message
        || Object.values(t.fields).flat().join(' ') || 'Could not render the preview.';
    } finally {
      if (seq === previewSeq[kind]) previews[kind].loading = false;
    }
  }

  for (const { kind } of PREVIEWS) {
    $effect(() => {
      if (loading || loadError) return;
      const drafts = Object.fromEntries(previewKeys(kind).map((k) => [k, values[k] ?? '']));
      logo;   // the saved logo prints too — re-render when it is uploaded or removed
      const timer = setTimeout(() => refreshPreview(kind, drafts), previewDelay);
      previewTimers[kind] = timer;
      return () => clearTimeout(timer);
    });
  }

  onDestroy(() => {
    for (const { kind } of PREVIEWS) {
      clearTimeout(previewTimers[kind]);
      previewSeq[kind] = Infinity;   // drop any reply still in flight
      if (previews[kind].pdfUrl) URL.revokeObjectURL(previews[kind].pdfUrl);
    }
  });

  load();
</script>

{#snippet previewPane(target)}
  {@const preview = previews[target.kind]}
  <aside class="doc-preview" aria-label={`${target.label} preview`}>
    <p class="preview-head">
      <small>
        <strong>Preview</strong> — {target.caption}, unsaved edits included
        {#if preview.loading}<em class="updating">updating…</em>{/if}
      </small>
    </p>
    {#if preview.pages.length}
      <a class="preview-pages" href={preview.pdfUrl || undefined}
         target="_blank" rel="noopener"
         aria-label={`Open the ${target.label} preview PDF`}>
        {#each preview.pages as src, i (i)}
          <img {src} alt={`${target.label} preview, page ${i + 1}`}>
        {/each}
      </a>
      <p><small>Click to open full size.</small></p>
    {:else if preview.rendered && !preview.error}
      <p class="preview-empty"><small>Nothing set — the letterhead is left off every document.</small></p>
    {:else if !preview.error}
      <p class="preview-empty"><small>Rendering preview&hellip;</small></p>
    {/if}
    <FormMessage error={preview.error} />
  </aside>
{/snippet}

<section>
  <h3>Document PDFs</h3>
  <p>
    Branding for the PDF attached when an Estimate, Change Order, or Purchase
    Order is emailed. Invoices attach the PDF QuickBooks renders, so their
    look is set in QuickBooks.
  </p>

  <LoadState {loading} error={loadError} loadingText="Loading document settings&hellip;">
    <fieldset class="settings-block">
      <legend><strong>Letterhead</strong></legend>
      <div class="doc-layout">
        <div class="doc-form">
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

          {#each COMPANY_FIELDS as [key, label, singleLine] (key)}
            <div class="field">
              <RichTextEditor id={key} {label} {singleLine} bind:value={values[key]} />
            </div>
          {/each}
          <p>
            <button type="button"
                    onclick={() => saveGroup(LETTERHEAD, [POSITION_KEY, ...COMPANY_KEYS])}
                    disabled={saving[LETTERHEAD]}>
              {saving[LETTERHEAD] ? 'Saving…' : 'Save letterhead'}
            </button>
            {#if flashVisible(LETTERHEAD)}<em class="ok">saved</em>{/if}
          </p>
          <FormMessage error={saveErrors[LETTERHEAD]} />
        </div>
        {@render previewPane(PREVIEWS[0])}
      </div>
    </fieldset>

    <fieldset class="settings-block">
      <legend><strong>Available variables</strong></legend>
      <dl class="vars">
        {#each VARS as [name, desc]}
          <dt><code>{name}</code></dt><dd>{desc}</dd>
        {/each}
      </dl>
      <p>
        <small>
          Usable in any text box below. <code>{'{estimate_number}'}</code>,
          <code>{'{change_order_number}'}</code>, <code>{'{po_number}'}</code>
          and <code>{'{vendor_name}'}</code> also work on their own documents.
          An unknown variable prints exactly as typed — the preview beside
          each document shows it. Format a variable as a whole: one split
          by formatting part-way through also prints as typed.
        </small>
      </p>
    </fieldset>

    {#each DOCUMENTS as doc (doc.kind)}
      <fieldset class="settings-block">
        <legend><strong>{doc.label}</strong></legend>
        <div class="doc-layout">
          <div class="doc-form">
            {#each SLOTS as [slot, label, hint] (slot)}
              <div class="field">
                <RichTextEditor id={textKey(doc.kind, slot)} {label}
                                bind:value={values[textKey(doc.kind, slot)]} />
                <small>{hint}</small>
              </div>
            {/each}
            <p>
              <button type="button"
                      onclick={() => saveGroup(doc.kind, slotKeys(doc.kind))}
                      disabled={saving[doc.kind]}>
                {saving[doc.kind] ? 'Saving…' : `Save ${doc.label} text`}
              </button>
              {#if flashVisible(doc.kind)}<em class="ok">saved</em>{/if}
            </p>
            <FormMessage error={saveErrors[doc.kind]} />
          </div>

          {@render previewPane(PREVIEWS.find((p) => p.kind === doc.kind))}
        </div>
      </fieldset>
    {/each}
  </LoadState>
</section>

<style>
  .field { margin: 0 0 14px; }
  .logo-preview {
    max-height: 80px;
    max-width: 240px;
    border: 1px solid var(--border-subtle);
  }
  .radio { margin-right: 16px; }
  .doc-layout {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 300px;
    gap: 16px;
    align-items: start;
  }
  .doc-preview {
    position: sticky;
    top: 8px;
  }
  .preview-head { margin: 0 0 6px; }
  .updating { color: #888; margin-left: 6px; }
  .preview-pages {
    display: block;
    max-height: 420px;
    overflow-y: auto;
    border: 1px solid var(--border-subtle);
    background: var(--border-subtle);
  }
  .preview-pages img {
    display: block;
    width: 100%;
    height: auto;
    background: #fff;
  }
  .preview-pages img + img { margin-top: 6px; }
  .preview-empty {
    border: 1px dashed var(--border-control);
    padding: 24px 8px;
    text-align: center;
    color: #888;
  }
  @media (max-width: 900px) {
    .doc-layout { grid-template-columns: minmax(0, 1fr); }
    .doc-preview { position: static; max-width: 360px; }
  }
  .ok { color: #047857; margin-left: 8px; }
  .vars { gap: 2px 12px; }
  .vars dt { font-weight: normal; }
  .vars dt code { font-weight: bold; }
</style>

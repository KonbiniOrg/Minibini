<script>
  import { onDestroy } from 'svelte';
  import { api, errorMessage } from '../../lib/api.js';
  import { triageError } from '../../lib/errorTriage.js';
  import { showError } from '../../stores/messages.js';
  import FormMessage from '../FormMessage.svelte';
  import LoadState from '../LoadState.svelte';
  import FieldError from '../FieldError.svelte';
  import RichTextEditor from '../RichTextEditor.svelte';
  import PdfCanvas from './PdfCanvas.svelte';

  // The three locally rendered document PDFs. Company details (logo, name,
  // address, phone, email) are one shared set; each document has its own,
  // fully independent layout — rows of columns holding blocks — and page
  // footer, arranged and edited on a drawing of its page (PdfCanvas). Keys
  // mirror apps/core/pdf_branding.py and apps/core/pdf_layout.py.
  //
  // The canvas is a browser drawing; "Print view" shows the real PDF: after
  // a pause in editing, the unsaved company text, footer and layout go to
  // the preview endpoint, which renders it with WeasyPrint and returns its
  // pages as images. Neither saves — the Save buttons do that.

  // Wait this long after the last edit before requesting a preview (tests
  // pass 0).
  let { previewDelay = 500 } = $props();

  const LOGO_URL = '/api/settings/pdf-logo/';
  const IMAGES_URL = '/api/settings/pdf-images/';
  const PREVIEW_URL = '/api/settings/pdf-preview/';
  const layoutUrl = (kind) => `/api/settings/pdf-layout/${kind}/`;
  const canvasUrl = (kind) => `/api/settings/pdf-canvas/${kind}/`;
  const COMPANY = 'company';
  // [key, label, singleLine] — all rich text.
  const COMPANY_FIELDS = [
    ['pdf_company_name', 'Company name', true],
    ['pdf_company_address', 'Address', false],
    ['pdf_company_phone', 'Phone', true],
    ['pdf_company_email', 'Email', true],
  ];
  const COMPANY_KEYS = COMPANY_FIELDS.map(([key]) => key);

  const DOCUMENTS = [
    { kind: 'estimate', label: 'Estimate' },
    { kind: 'change_order', label: 'Change Order' },
    { kind: 'po', label: 'Purchase Order' },
  ];
  const footerKey = (kind) => `${kind}_pdf_text_page_footer`;

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

  const copy = (value) => JSON.parse(JSON.stringify(value));

  let values = $state({});      // {key: value} — company text + footers, unsaved edits included
  let savedValues = $state({}); // {key: stored value} — what Save would change from
  let images = $state([]);      // the image library: [{id, name, src}]
  let imageErrors = $state({});
  let imageBusy = $state(false);
  let logo = $state('');        // data URI, '' when unset
  let logoFile = $state(null);
  let logoErrors = $state({});
  let logoBusy = $state(false);
  let layouts = $state({});     // {kind: draft layout}
  let savedLayouts = $state({}); // {kind: JSON of the stored layout}
  let defaults = {};            // {kind: built-in default layout}
  let catalog = $state(null);   // blocks + column presets (same for every kind)
  let canvasParts = $state({}); // {kind: {blocks, stylesheet}} — the canvas's drawing material
  let view = $state('canvas');  // 'canvas' | 'print'
  let doc = $state('estimate'); // the document being arranged
  let copyFrom = $state('');
  let saving = $state({});      // {group: bool}
  let savedFlash = $state({});  // {group: true while its "saved" note shows}
  const flashTimers = {};
  let saveErrors = $state({});  // {group: form-footer error message}
  let loadError = $state(null);
  let loading = $state(true);
  // {pages: [PNG data URI], pdfUrl: blob URL, loading, error} — the selected
  // document's preview.
  let preview = $state({ pages: [], pdfUrl: '', loading: false, error: '' });
  let previewTimer;
  let previewSeq = 0;           // latest request number; older replies are dropped

  const current = $derived(DOCUMENTS.find((d) => d.kind === doc));
  const company = $derived({
    logo,
    ...Object.fromEntries(COMPANY_KEYS.map((key) => [key.replace('pdf_', ''), values[key] ?? ''])),
  });
  const companyDirty = $derived(COMPANY_KEYS.some((k) => values[k] !== savedValues[k]));
  // A document has unsaved changes when its layout or footer differ from the
  // stored ones — or the company details do (its Save saves those too).
  const dirty = (kind) => layouts[kind] !== undefined && (
    JSON.stringify(layouts[kind]) !== savedLayouts[kind]
    || values[footerKey(kind)] !== savedValues[footerKey(kind)]
    || companyDirty);
  const unsaved = $derived(dirty(doc));

  async function load() {
    loading = true;
    loadError = null;
    try {
      const [all, logoData, imageData, ...perDocument] = await Promise.all([
        api.get('/api/settings/'), api.get(LOGO_URL), api.get(IMAGES_URL),
        ...DOCUMENTS.map((d) => api.get(layoutUrl(d.kind))),
        ...DOCUMENTS.map((d) => api.get(canvasUrl(d.kind))),
      ]);
      const layoutData = perDocument.slice(0, DOCUMENTS.length);
      DOCUMENTS.forEach((d, i) => { canvasParts[d.kind] = perDocument[DOCUMENTS.length + i]; });
      const next = {};
      for (const key of COMPANY_KEYS) next[key] = all[key] ?? '';
      for (const d of DOCUMENTS) next[footerKey(d.kind)] = all[footerKey(d.kind)] ?? '';
      values = next;
      savedValues = { ...next };
      logo = logoData.logo ?? '';
      images = imageData.images ?? [];
      DOCUMENTS.forEach((d, i) => {
        layouts[d.kind] = layoutData[i].layout;
        savedLayouts[d.kind] = JSON.stringify(layoutData[i].layout);
        defaults[d.kind] = layoutData[i].default;
      });
      catalog = layoutData[0].catalog;
    } catch (e) {
      loadError = errorMessage(e, 'Could not load the document settings.');
    } finally {
      loading = false;
    }
  }

  function failSave(group, e) {
    const t = triageError(e);
    if (t.overlay) {
      showError(t.overlay);
      return;
    }
    // Field-keyed errors come back keyed by the config key (or `layout`) —
    // fold them into this group's footer message.
    const fieldText = Object.values(t.fields).flat().join(' ');
    saveErrors = {
      ...saveErrors,
      [group]: [t.message, fieldText].filter(Boolean).join(' ') || 'Save failed.',
    };
  }

  async function saveCompany() {
    saving = { ...saving, [COMPANY]: true };
    saveErrors = { ...saveErrors, [COMPANY]: '' };
    try {
      const sent = Object.fromEntries(COMPANY_KEYS.map((k) => [k, values[k]]));
      await api.patch('/api/settings/', sent);
      savedValues = { ...savedValues, ...sent };
      flash(COMPANY);
    } catch (e) {
      failSave(COMPANY, e);
    } finally {
      saving = { ...saving, [COMPANY]: false };
    }
  }

  // Save one document: its layout, then its footer — and the company
  // details too when they were edited (on the page or above).
  async function saveDocument(kind) {
    saving = { ...saving, [kind]: true };
    saveErrors = { ...saveErrors, [kind]: '' };
    try {
      const result = await api.put(layoutUrl(kind), { layout: $state.snapshot(layouts[kind]) });
      layouts[kind] = result.layout;
      savedLayouts[kind] = JSON.stringify(result.layout);
      const sent = { [footerKey(kind)]: values[footerKey(kind)] };
      if (companyDirty) for (const k of COMPANY_KEYS) sent[k] = values[k];
      await api.patch('/api/settings/', sent);
      savedValues = { ...savedValues, ...sent };
      flash(kind);
    } catch (e) {
      failSave(kind, e);
    } finally {
      saving = { ...saving, [kind]: false };
    }
  }

  // Show a group's "saved" note for three seconds.
  function flash(group) {
    savedFlash = { ...savedFlash, [group]: true };
    clearTimeout(flashTimers[group]);
    flashTimers[group] = setTimeout(() => { savedFlash = { ...savedFlash, [group]: false }; }, 3000);
  }

  // A different document: its preview starts over rather than showing the
  // last document's pages under the new name.
  function selectDocument(kind) {
    if (kind === doc) return;
    doc = kind;
    previewSeq += 1;
    preview.pages = [];
    preview.error = '';
  }

  function copyLayout(from) {
    copyFrom = '';
    if (from) layouts[doc] = copy(layouts[from]);
  }

  // Add a file to the image library. Resolves to the new image; rejects
  // with the API error (the canvas shows it in the block's tools).
  async function addImage(file) {
    const fd = new FormData();
    fd.append('image', file);
    const image = await api.postMultipart(IMAGES_URL, fd);
    images = [...images, image];
    return image;
  }

  async function uploadImage(input) {
    const file = input.files?.[0];
    input.value = '';
    if (!file) return;
    imageErrors = {};
    imageBusy = true;
    try {
      await addImage(file);
    } catch (e) {
      const t = triageError(e);
      if (t.overlay) showError(t.overlay);
      else imageErrors = t.message ? { image: [t.message] } : t.fields;
    } finally {
      imageBusy = false;
    }
  }

  // Canvas uploads: the error comes back as one sentence for its toolbar.
  async function addImageFromCanvas(file) {
    try {
      return await addImage(file);
    } catch (e) {
      const t = triageError(e);
      throw new Error(t.overlay || t.message || Object.values(t.fields).flat().join(' ')
        || 'Could not upload the image.');
    }
  }

  async function removeImage(image) {
    imageErrors = {};
    try {
      await api.delete(`${IMAGES_URL}${image.id}/`);
      images = images.filter((i) => i.id !== image.id);
    } catch (e) {
      const t = triageError(e);
      if (t.overlay) showError(t.overlay);
      else imageErrors = { image: [t.message || 'Could not remove the image.'] };
    }
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

  async function refreshPreview(body) {
    const seq = ++previewSeq;
    preview.loading = true;
    try {
      const result = await api.post(PREVIEW_URL, body);
      if (seq !== previewSeq) return;
      const old = preview.pdfUrl;
      preview.pdfUrl = pdfBlobUrl(result.pdf);
      if (old) URL.revokeObjectURL(old);
      preview.pages = result.pages;
      preview.error = '';
    } catch (e) {
      if (seq !== previewSeq) return;
      const t = triageError(e);
      // Shown in the preview pane, never the overlay: a preview fires on
      // every pause in editing, and a dead server would otherwise stack popups.
      preview.error = t.overlay || t.message
        || Object.values(t.fields).flat().join(' ') || 'Could not render the preview.';
    } finally {
      if (seq === previewSeq) preview.loading = false;
    }
  }

  // Print view only: the canvas needs no server render.
  $effect(() => {
    if (loading || loadError || !layouts[doc] || view !== 'print') return;
    const body = {
      document: doc,
      values: Object.fromEntries(
        [...COMPANY_KEYS, footerKey(doc)].map((k) => [k, values[k] ?? ''])),
      layout: $state.snapshot(layouts[doc]),
    };
    JSON.stringify(layouts[doc]);   // track every nested edit, not just the swap
    logo;   // the saved logo prints too — re-render when it is uploaded or removed
    clearTimeout(previewTimer);
    const timer = setTimeout(() => refreshPreview(body), previewDelay);
    previewTimer = timer;
    return () => clearTimeout(timer);
  });

  onDestroy(() => {
    for (const timer of Object.values(flashTimers)) clearTimeout(timer);
    clearTimeout(previewTimer);
    previewSeq = Infinity;   // drop any reply still in flight
    if (preview.pdfUrl) URL.revokeObjectURL(preview.pdfUrl);
  });

  load();
</script>

<section>
  <h3>Document PDFs</h3>
  <p>
    The PDF attached when an Estimate, Change Order, or Purchase Order is
    emailed. Invoices attach the PDF QuickBooks renders, so their look is
    set in QuickBooks.
  </p>

  <LoadState {loading} error={loadError} loadingText="Loading document settings&hellip;">
    <fieldset class="settings-block">
      <legend><strong>Company details</strong></legend>
      <p>
        <small>
          Shared by all three documents — each document's layout decides
          where (and whether) they print. Anything left blank is not printed.
        </small>
      </p>

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

      {#each COMPANY_FIELDS as [key, label, singleLine] (key)}
        <div class="field">
          <RichTextEditor id={key} {label} {singleLine} bind:value={values[key]} />
        </div>
      {/each}
      <p>
        <button type="button" onclick={saveCompany} disabled={saving[COMPANY]}>
          {saving[COMPANY] ? 'Saving…' : 'Save company details'}
        </button>
        {#if savedFlash[COMPANY]}<em class="ok">saved</em>{/if}
      </p>
      <FormMessage error={saveErrors[COMPANY]} />
    </fieldset>

    <fieldset class="settings-block">
      <legend><strong>Images</strong></legend>
      <p>
        <small>
          Pictures to place on any document with an Image block. PNG or JPEG,
          1 MB or smaller each. Removing one takes it off every document
          that placed it.
        </small>
      </p>
      {#if images.length}
        <ul class="image-library">
          {#each images as image (image.id)}
            <li>
              <img src={image.src} alt={image.name}>
              <span>{image.name}</span>
              <button type="button" aria-label={`Remove ${image.name}`} onclick={() => removeImage(image)}>
                Remove
              </button>
            </li>
          {/each}
        </ul>
      {:else}
        <p><em>No images yet.</em></p>
      {/if}
      <p>
        <label for="pdf_image_file"><strong>Add an image</strong></label><br>
        <input type="file" id="pdf_image_file" accept="image/png,image/jpeg" disabled={imageBusy}
               onchange={(e) => uploadImage(e.currentTarget)}>
        {#if imageBusy}<em>Uploading…</em>{/if}
      </p>
      <FieldError errors={imageErrors} field="image" />
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
          Usable in text blocks and page footers. <code>{'{estimate_number}'}</code>,
          <code>{'{change_order_number}'}</code>, <code>{'{po_number}'}</code>
          and <code>{'{vendor_name}'}</code> also work on their own documents.
          An unknown variable prints exactly as typed — the preview shows it.
          Format a variable as a whole: one split by formatting part-way
          through also prints as typed.
        </small>
      </p>
    </fieldset>

    <fieldset class="settings-block">
      <legend><strong>Document layouts</strong></legend>
      <div class="doc-tabs" role="tablist" aria-label="Document">
        {#each DOCUMENTS as d (d.kind)}
          <button type="button" role="tab" aria-selected={doc === d.kind}
                  class:active={doc === d.kind} onclick={() => selectDocument(d.kind)}>
            {d.label}{#if dirty(d.kind)}&nbsp;*{/if}
          </button>
        {/each}
      </div>

      {#if catalog && layouts[doc] && canvasParts[doc]}
        <div role="tabpanel" aria-label={`${current.label} layout`}>
          <p>
            <small>
              Drag blocks around the page — between blocks to stack them, to a
              column's edge to sit beside it, between rows for a new row — and
              drag a column's grip to resize; drop a Divider on a border for a
              line. Click a block for its tools; any text — company details
              and title included — and the page footer edit right where you
              click. Save saves the layout, its footer and any company-detail
              edits. A row with columns is kept together on one page.
            </small>
          </p>
          <div class="doc-actions-bar">
          <p class="row-actions doc-actions">
            <button type="button" class="save" onclick={() => saveDocument(doc)} disabled={saving[doc]}>
              {saving[doc] ? 'Saving…' : `Save ${current.label}`}
            </button>
            {#if unsaved}<em class="unsaved">unsaved changes</em>
            {:else if savedFlash[doc]}<em class="ok">saved</em>{/if}
            <span class="sep"></span>
            <button type="button" onclick={() => { layouts[doc] = copy(defaults[doc]); }}>
              Reset to default
            </button>
            <select aria-label="Copy layout from" bind:value={copyFrom}
                    onchange={(e) => copyLayout(e.currentTarget.value)}>
              <option value="">Copy layout from…</option>
              {#each DOCUMENTS.filter((d) => d.kind !== doc) as d (d.kind)}
                <option value={d.kind}>{d.label}</option>
              {/each}
            </select>
            <span class="spacer"></span>
            <button type="button" aria-pressed={view === 'canvas'} onclick={() => { view = 'canvas'; }}>
              Edit page
            </button>
            <button type="button" aria-pressed={view === 'print'} onclick={() => { view = 'print'; }}>
              Print view
            </button>
          </p>
          <FormMessage error={saveErrors[doc]} />
          </div>

          {#if view === 'canvas'}
            {#key doc}
              <PdfCanvas bind:layout={layouts[doc]} bind:footer={values[footerKey(doc)]}
                         {catalog} kind={doc} parts={canvasParts[doc]} {company} {images}
                         onCompany={(type, html) => { values[`pdf_${type}`] = html; }}
                         onUploadImage={addImageFromCanvas} />
            {/key}
          {:else}
            <section class="doc-preview" aria-label={`${current.label} preview`}>
              <p class="preview-head">
                <small>
                  <strong>Print view</strong> — the real PDF of a sample {current.label.toLowerCase()}, unsaved edits included
                  {#if preview.loading}<em class="updating">updating…</em>{/if}
                </small>
              </p>
              {#if preview.pages.length}
                <a class="preview-pages" href={preview.pdfUrl || undefined}
                   target="_blank" rel="noopener"
                   aria-label={`Open the ${current.label} preview PDF`}>
                  {#each preview.pages as src, i (i)}
                    <img {src} alt={`${current.label} preview, page ${i + 1}`}>
                  {/each}
                </a>
                <p><small>Click to open full size.</small></p>
              {:else if !preview.error}
                <p class="preview-empty"><small>Rendering preview&hellip;</small></p>
              {/if}
              <FormMessage error={preview.error} />
            </section>
          {/if}
        </div>
      {/if}
    </fieldset>
  </LoadState>
</section>

<style>
  .field { margin: 0 0 14px; }
  .logo-preview {
    max-height: 80px;
    max-width: 240px;
    border: 1px solid var(--border-subtle);
  }
  .doc-tabs { display: flex; gap: 4px; margin-bottom: 10px; }
  .doc-tabs button.active { font-weight: bold; background: #fff; border-color: #2a6ebb; }
  /* Save and the page's tools stay in reach while the tall page scrolls. */
  .doc-actions-bar {
    position: sticky;
    top: 0;
    z-index: 10;
    background: #fff;
    padding: 6px 0;
    border-bottom: 1px solid var(--border-subtle, #ddd);
    margin-bottom: 8px;
  }
  .doc-actions-bar :global(.form-message), .doc-actions-bar p { margin: 0; }
  .doc-actions { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; }
  .doc-actions .spacer { flex: 1; }
  .doc-actions .sep { width: 12px; }
  .doc-actions .save { font-weight: bold; }
  .image-library { list-style: none; padding: 0; display: flex; flex-wrap: wrap; gap: 10px; }
  .image-library li {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 2px;
    width: 120px;
    font-size: 12px;
    overflow-wrap: anywhere;
    text-align: center;
  }
  .image-library img { max-width: 120px; max-height: 80px; border: 1px solid var(--border-subtle); }
  .doc-preview { max-width: 820px; }
  .preview-head { margin: 0 0 6px; }
  .updating { color: #888; margin-left: 6px; }
  .preview-pages {
    display: block;
    max-height: 1200px;
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
  .ok { color: #047857; margin-left: 8px; }
  .unsaved { color: #92400e; margin-left: 8px; }
  .vars { gap: 2px 12px; }
  .vars dt { font-weight: normal; }
  .vars dt code { font-weight: bold; }
</style>

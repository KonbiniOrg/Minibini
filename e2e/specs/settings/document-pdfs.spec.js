// Document PDFs on Settings → Documents: the shared company details (logo
// upload/remove, company text), each document's independent layout arranged
// by dragging blocks around a drawing of its page, the in-place text and
// footer editing, and the real-PDF print view. The spec starts and ends the
// layouts it touches at their defaults and removes its logo at the end; the
// company text it saves is harmless to other specs (it only decorates PDFs).
import { expect, test } from '@playwright/test';
import { apiAs } from '../../fixtures/api.js';
import { personas } from '../../fixtures/personas.js';

test.use({ storageState: personas.configtime.storageState });

// A valid 1x1 PNG.
const PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==',
  'base64');

async function openDocumentsTab(page) {
  await page.goto('/#/settings');
  await page.getByRole('button', { name: 'Documents' }).click();
  await expect(page.getByRole('heading', { name: 'Document PDFs' })).toBeVisible();
}

const layouts = (page) => page.getByRole('group', { name: 'Document layouts' });
const sheet = (page, kind) => layouts(page).getByRole('region', { name: `${kind} page` });

async function resetAndSave(page, tab, label) {
  await layouts(page).getByRole('tab', { name: tab }).click();
  await layouts(page).getByRole('button', { name: 'Reset to default' }).click();
  await layouts(page).getByRole('button', { name: `Save ${label}` }).click();
  await expect(layouts(page).getByText('saved', { exact: true })).toBeVisible();
}

// Press on `source`, move in steps to the point `at(box)` picks in
// `target`'s box, release — real pointer events, as a user's drag. Both are
// measured after scrolling the source into view (the mouse only reaches
// what is on screen).
async function dragTo(page, source, target, at) {
  await source.scrollIntoViewIfNeeded();
  const box = await source.boundingBox();
  const { x, y } = at(await target.boundingBox());
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 + 10, box.y + box.height / 2 + 10, { steps: 3 });
  await page.mouse.move(x, y, { steps: 12 });
  await page.mouse.up();
}

test('company details, arranging a page by dragging, editing in place, print view', async ({ page }) => {
  const company = `E2E Shop ${Date.now().toString(36)}`;
  const terms = `Valid 30 days ${Date.now().toString(36)}`;

  await openDocumentsTab(page);
  // Start the documents this spec touches from their default layouts.
  await resetAndSave(page, 'Purchase Order', 'Purchase Order');
  await resetAndSave(page, 'Estimate', 'Estimate');

  // Company details are shared and saved on their own; the canvas draws them.
  const details = page.getByRole('group', { name: 'Company details' });
  await details.getByRole('textbox', { name: 'Company name' }).fill(company);
  await details.getByRole('button', { name: 'Save company details' }).click();
  await expect(details.getByText('saved', { exact: true })).toBeVisible();
  await expect(sheet(page, 'estimate').getByText(company)).toBeVisible();

  // A non-image is rejected under the file input; a real image uploads and
  // appears on the page.
  await details.getByLabel('Logo image').setInputFiles({
    name: 'logo.png', mimeType: 'image/png', buffer: Buffer.from('not an image'),
  });
  await details.getByRole('button', { name: 'Upload logo' }).click();
  await expect(details.getByText('That file is not a readable image.')).toBeVisible();
  await details.getByLabel('Logo image').setInputFiles({
    name: 'logo.png', mimeType: 'image/png', buffer: PNG,
  });
  await details.getByRole('button', { name: 'Upload logo' }).click();
  await expect(details.getByAltText('Current logo')).toBeVisible();
  await expect(sheet(page, 'estimate').getByRole('img', { name: 'Logo' })).toBeVisible();

  let wrote = false;
  page.on('request', (req) => {
    if (['PUT', 'PATCH'].includes(req.method()) && req.url().includes('/api/settings/')) wrote = true;
  });

  const editor = layouts(page);
  const title = sheet(page, 'estimate').getByRole('button', { name: 'Title block' });

  // Any text edits on the page with one click — the caret lands where the
  // click did, so the keyboard types straight in. The company name is the
  // shared value: the Company details form follows.
  await sheet(page, 'estimate').getByRole('button', { name: 'Company name block' }).click();
  await page.keyboard.press('End');
  await page.keyboard.type(' Ltd');
  await expect(details.getByRole('textbox', { name: 'Company name' })).toHaveText(`${company} Ltd`);
  await title.click();
  await expect(editor.getByRole('textbox', { name: 'Title text' })).toBeFocused();
  await page.keyboard.type('Quotation');
  await expect(editor.getByText('unsaved changes')).toBeVisible();

  // Drag a Text block from the palette to the right edge of the title: it
  // lands beside it, splitting the title's row into two columns.
  await expect(editor.getByRole('slider', { name: 'Row 2 column split' })).toHaveCount(0);
  await dragTo(page, editor.getByRole('button', { name: 'Add Text' }), title,
    (b) => ({ x: b.x + b.width - 10, y: b.y + b.height / 2 }));
  const split = editor.getByRole('slider', { name: 'Row 2 column split' });
  await expect(split).toHaveAttribute('aria-valuetext', '1/2-1/2');

  // The new block is selected and its editor focused: just type.
  await expect(editor.getByRole('textbox', { name: 'Text', exact: true })).toBeFocused();
  await page.keyboard.type(terms);
  // The fuller toolbar: strike the text through.
  await page.keyboard.press('ControlOrMeta+a');
  await editor.getByRole('toolbar', { name: 'Text formatting' })
    .getByRole('button', { name: 'Strikethrough' }).click();
  await expect(editor.getByRole('toolbar', { name: 'Text tools' })).toBeVisible();
  await editor.getByRole('button', { name: 'Align block right' }).click();

  // Drag the column divider left: it snaps to ⅓ + ⅔.
  await dragTo(page, split, split.locator('..'),
    (b) => ({ x: b.x + b.width * 0.3, y: b.y + b.height / 2 }));
  await expect(split).toHaveAttribute('aria-valuetext', '1/3-2/3');

  // Column gap, then Divider lines dragged onto borders: between the title
  // and text columns, and under the details row.
  await editor.getByRole('combobox', { name: 'Column gap' }).selectOption({ label: 'Gap: Large' });
  const textCell = sheet(page, 'estimate').getByRole('button', { name: 'Text block' });
  await dragTo(page, editor.getByRole('button', { name: 'Add Divider' }), textCell,
    (b) => ({ x: b.x + 4, y: b.y + b.height / 2 }));
  await expect(editor.getByRole('button', { name: 'Line between columns 1 and 2 of row 2' }))
    .toBeVisible();
  const detailsBlock = sheet(page, 'estimate').getByRole('button', { name: 'Details block' });
  await dragTo(page, editor.getByRole('button', { name: 'Add Divider' }), detailsBlock,
    (b) => ({ x: b.x + b.width / 2, y: b.y + b.height + 3 }));
  await expect(editor.getByRole('button', { name: 'Line below row 3' })).toBeVisible();
  await editor.getByRole('button', { name: 'Add Spacer' }).click();
  await editor.getByRole('button', { name: 'Indent' }).click();
  await editor.getByRole('button', { name: 'Right side' }).click();
  await expect(editor.getByText('↔ Indent — right, medium')).toBeVisible();

  // An image: uploaded to the library, placed with an Image block.
  const library = page.getByRole('group', { name: 'Images' });
  await library.getByLabel('Add an image').setInputFiles({
    name: 'photo.png', mimeType: 'image/png', buffer: PNG,
  });
  await expect(library.getByAltText('photo.png')).toBeVisible();
  await editor.getByRole('button', { name: 'Add Image' }).click();
  await editor.getByRole('combobox', { name: 'Image', exact: true }).selectOption({ label: 'photo.png' });
  await expect(sheet(page, 'estimate').getByRole('img', { name: 'photo.png' })).toBeVisible();

  // The footer edits in place too.
  await editor.getByRole('button', { name: 'Edit page footer' }).click();
  await editor.getByRole('textbox', { name: 'Page footer' }).fill('Page {page} of {page_count}');
  await expect(editor.getByText('unsaved changes')).toBeVisible();

  // Print view renders the real PDF from the unsaved draft; nothing is written.
  const previewed = page.waitForRequest((req) =>
    req.method() === 'POST' && req.url().includes('/api/settings/pdf-preview/'));
  await editor.getByRole('button', { name: 'Print view' }).click();
  const body = (await previewed).postDataJSON();
  const titleRow = body.layout.rows.find((r) => r.cells.flat().some((b) => b.type === 'title'));
  expect(titleRow.columns).toBe('1/3-2/3');
  expect(titleRow.cells[0][0]).toEqual({ type: 'title', align: 'left', heading: 'Quotation' });
  expect(titleRow.cells[1]).toEqual([{ type: 'text', align: 'right', html: `<p><s>${terms}</s></p>` }]);
  expect(titleRow.gap).toBe('large');
  expect(titleRow.column_lines).toEqual([true]);
  const detailsRow = body.layout.rows.find((r) => r.cells.flat().some((b) => b.type === 'details'));
  expect(detailsRow.line_below).toBe(true);
  expect(body.layout.rows.at(-2).cells[0]).toEqual([
    { type: 'spacer', orientation: 'horizontal', size: 'medium', side: 'right' },
  ]);
  const [image] = body.layout.rows.at(-1).cells[0];
  expect(image).toMatchObject({ type: 'image', size: 'medium' });
  expect(image.image).toMatch(/^[0-9a-f]{32}$/);
  expect(body.values.pdf_company_name).toBe(`<p>${company} Ltd</p>`);
  expect(body.values.estimate_pdf_text_page_footer).toBe('<p>Page {page} of {page_count}</p>');
  await expect(editor.getByAltText('Estimate preview, page 1')).toHaveAttribute('src', /^data:image\/png;base64,/);
  const full = editor.getByRole('link', { name: 'Open the Estimate preview PDF' });
  await expect(full).toHaveAttribute('href', /^blob:/);
  expect(wrote).toBe(false);

  // Save, reload: the arrangement and footer persisted.
  await editor.getByRole('button', { name: 'Edit page' }).click();
  await editor.getByRole('button', { name: 'Save Estimate' }).click();
  await expect(editor.getByText('saved', { exact: true })).toBeVisible();
  await openDocumentsTab(page);
  const saved = sheet(page, 'estimate');
  await expect(saved.getByText(terms)).toBeVisible();
  await expect(saved.getByRole('heading', { name: 'Quotation' })).toBeVisible();
  // The strikethrough survived the server's sanitizer and the save.
  await expect(saved.locator('s', { hasText: terms })).toBeVisible();
  await expect(saved.getByRole('img', { name: 'photo.png' })).toBeVisible();
  // The document's Save saved the company name edited on the page.
  await expect(page.getByRole('group', { name: 'Company details' })
    .getByRole('textbox', { name: 'Company name' })).toHaveText(`${company} Ltd`);
  await expect(layouts(page).getByRole('slider', { name: 'Row 2 column split' }))
    .toHaveAttribute('aria-valuetext', '1/3-2/3');
  await expect(layouts(page).getByRole('button', { name: 'Edit page footer' }))
    .toHaveText('Page {page} of {page_count}');

  // Drag the text block below the line items: a new row there.
  const lines = saved.getByRole('button', { name: 'Line items block' });
  await dragTo(page, saved.getByRole('button', { name: 'Text block' }), lines,
    (b) => ({ x: b.x + b.width / 2, y: b.y + b.height + 6 }));
  // The title's row is one column again; the text sits below the lines.
  await expect(layouts(page).getByRole('slider', { name: 'Row 2 column split' })).toHaveCount(0);
  const linesBox = await lines.boundingBox();
  const textBox = await saved.getByRole('button', { name: 'Text block' }).boundingBox();
  expect(textBox.y).toBeGreaterThan(linesBox.y + linesBox.height - 1);

  // The purchase order's layout is independent: copying is a one-off draft.
  await layouts(page).getByRole('tab', { name: 'Purchase Order' }).click();
  await expect(sheet(page, 'po').getByText(terms)).toHaveCount(0);
  await layouts(page).getByRole('combobox', { name: 'Copy layout from' })
    .selectOption({ label: 'Estimate' });
  await expect(sheet(page, 'po').getByText(terms)).toBeVisible();

  // Clean up: default layouts back, image and logo removed.
  await openDocumentsTab(page);
  await resetAndSave(page, 'Estimate', 'Estimate');
  const images = page.getByRole('group', { name: 'Images' });
  await images.getByRole('button', { name: 'Remove photo.png' }).click();
  await expect(images.getByAltText('photo.png')).toHaveCount(0);
  const reloaded = page.getByRole('group', { name: 'Company details' });
  await reloaded.getByRole('button', { name: 'Remove logo' }).click();
  await expect(reloaded.getByAltText('Current logo')).toHaveCount(0);
  await expect(reloaded.getByText('No logo uploaded.')).toBeVisible();
});

test('the server rejects a layout without its line items', async ({ page }) => {
  const resp = await page.request.put('/api/settings/pdf-layout/po/', {
    data: { layout: { version: 1, rows: [{ columns: 'full', cells: [[{ type: 'title' }]] }] } },
    headers: { 'X-CSRFToken': (await page.context().cookies())
      .find((c) => c.name === 'csrftoken')?.value ?? '' },
  });
  expect(resp.status()).toBe(400);
  expect((await resp.json()).layout.join(' ')).toContain('line items');
});

test('a user without can_manage_config cannot reach the branding endpoints', async ({ browser }) => {
  const context = await browser.newContext({ storageState: personas.worker.storageState });
  expect((await context.request.get('/api/settings/pdf-logo/')).status()).toBe(403);
  expect((await context.request.get('/api/settings/pdf-layout/estimate/')).status()).toBe(403);
  expect((await context.request.get('/api/settings/pdf-canvas/estimate/')).status()).toBe(403);
  expect((await context.request.get('/api/settings/pdf-images/')).status()).toBe(403);
  await context.close();
  const worker = await apiAs(personas.worker);
  try {
    const preview = await worker.postRaw('/api/settings/pdf-preview/', { document: 'estimate' });
    expect(preview.status()).toBe(403);
  } finally {
    await worker.dispose();
  }
});

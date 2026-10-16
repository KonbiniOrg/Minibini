// Document PDF branding on Settings → Documents: the shared letterhead
// (logo upload/remove, logo position, company block), a document's text
// slots, and the live preview beside each document. The spec removes its
// logo at the end; the text it saves is harmless to other specs (it only
// decorates PDFs).
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

test('letterhead, text slots, logo and preview roundtrip', async ({ page }) => {
  const company = `E2E Shop ${Date.now().toString(36)}`;
  const terms = `Valid 30 days — ref {document_number} ${Date.now().toString(36)}`;

  await openDocumentsTab(page);

  // Letterhead: company block + logo position, saved together.
  const letterhead = page.getByRole('group', { name: 'Letterhead' });
  await letterhead.getByRole('textbox', { name: 'Company name' }).fill(company);
  await letterhead.getByRole('radio', { name: 'Center' }).check();
  await letterhead.getByRole('button', { name: 'Save letterhead' }).click();
  await expect(letterhead.getByText('saved')).toBeVisible();

  // The letterhead has its own preview: the band cropped from the top of a
  // page, re-rendered from unsaved edits.
  const band = letterhead.getByAltText('Letterhead preview, page 1');
  await expect(band).toHaveAttribute('src', /^data:image\/png;base64,/);
  const bandSrc = await band.getAttribute('src');
  const bandDims = await band.evaluate((img) => [img.naturalWidth, img.naturalHeight]);
  expect(bandDims[0]).toBeGreaterThan(bandDims[1]);
  await letterhead.getByRole('radio', { name: 'Right' }).check();
  await expect(band).not.toHaveAttribute('src', bandSrc);
  await letterhead.getByRole('radio', { name: 'Center' }).check();

  // A non-image is rejected under the file input.
  await letterhead.getByLabel('Logo image').setInputFiles({
    name: 'logo.png', mimeType: 'image/png', buffer: Buffer.from('not an image'),
  });
  await letterhead.getByRole('button', { name: 'Upload logo' }).click();
  await expect(letterhead.getByText('That file is not a readable image.')).toBeVisible();
  await expect(letterhead.getByAltText('Current logo')).toHaveCount(0);

  // A real image uploads and is shown.
  await letterhead.getByLabel('Logo image').setInputFiles({
    name: 'logo.png', mimeType: 'image/png', buffer: PNG,
  });
  await letterhead.getByRole('button', { name: 'Upload logo' }).click();
  await expect(letterhead.getByAltText('Current logo')).toBeVisible();

  // One document's text slots.
  const estimate = page.getByRole('group', { name: 'Estimate', exact: true });
  // Rich text: the terms are typed, then bolded and enlarged from the toolbar.
  const totals = estimate.getByRole('textbox', { name: 'Below the totals' });
  await totals.fill(terms);
  await totals.press('ControlOrMeta+a');
  await totals.press('ControlOrMeta+b');
  await estimate.getByRole('toolbar', { name: 'Below the totals formatting' })
    .getByRole('combobox', { name: 'Text size' }).selectOption('Large');

  // A numbered list: two typed lines, then the toolbar's list button.
  const aboveLines = estimate.getByRole('textbox', { name: 'Above the line items' });
  await aboveLines.click();
  await aboveLines.press('ControlOrMeta+a');
  await aboveLines.pressSequentially('Cut to size');
  await aboveLines.press('Enter');
  await aboveLines.pressSequentially('Deburr');
  await aboveLines.press('ControlOrMeta+a');
  await estimate.getByRole('toolbar', { name: 'Above the line items formatting' })
    .getByRole('button', { name: 'Numbered list' }).click();
  await estimate.getByRole('button', { name: 'Save Estimate text' }).click();
  await expect(estimate.getByText('saved')).toBeVisible();

  // Everything persisted across a reload.
  await openDocumentsTab(page);
  const reloaded = page.getByRole('group', { name: 'Letterhead' });
  await expect(reloaded.getByRole('textbox', { name: 'Company name' })).toHaveText(company);
  await expect(reloaded.getByRole('radio', { name: 'Center' })).toBeChecked();
  await expect(reloaded.getByAltText('Current logo')).toBeVisible();
  const savedTotals = page.getByRole('group', { name: 'Estimate', exact: true })
    .getByRole('textbox', { name: 'Below the totals' });
  await expect(savedTotals).toHaveText(terms);
  await expect(savedTotals.locator('strong span.size-large')).toHaveText(terms);
  const savedSteps = page.getByRole('group', { name: 'Estimate', exact: true })
    .getByRole('textbox', { name: 'Above the line items' });
  await expect(savedSteps.locator('ol > li')).toHaveText(['Cut to size', 'Deburr']);

  // The live preview re-renders from unsaved typing, and saving is still
  // a separate, deliberate step.
  const estimateNow = page.getByRole('group', { name: 'Estimate', exact: true });
  const pageImage = estimateNow.getByAltText('Estimate preview, page 1');
  await expect(pageImage).toHaveAttribute('src', /^data:image\/png;base64,/);
  const savedSrc = await pageImage.getAttribute('src');
  let patched = false;
  page.on('request', (req) => {
    if (req.method() === 'PATCH' && req.url().includes('/api/settings/')) patched = true;
  });
  const previewed = page.waitForRequest((req) =>
    req.method() === 'POST' && req.url().includes('/api/settings/pdf-preview/')
    && req.postDataJSON().values.estimate_pdf_text_below_header === '<p>Unsaved draft</p>');
  await estimateNow.getByRole('textbox', { name: 'Below the header' }).fill('Unsaved draft');
  await previewed;
  await expect(pageImage).not.toHaveAttribute('src', savedSrc);
  expect(patched).toBe(false);

  // The preview opens full size as a PDF in a new tab.
  const full = estimateNow.getByRole('link', { name: 'Open the Estimate preview PDF' });
  await expect(full).toHaveAttribute('href', /^blob:/);
  await expect(full).toHaveAttribute('target', '_blank');

  // Remove the logo.
  await reloaded.getByRole('button', { name: 'Remove logo' }).click();
  await expect(reloaded.getByAltText('Current logo')).toHaveCount(0);
  await expect(reloaded.getByText('No logo uploaded.')).toBeVisible();
});

test('a user without can_manage_config cannot reach the branding endpoints', async ({ browser }) => {
  const context = await browser.newContext({ storageState: personas.worker.storageState });
  const logo = await context.request.get('/api/settings/pdf-logo/');
  expect(logo.status()).toBe(403);
  await context.close();
  const worker = await apiAs(personas.worker);
  try {
    const preview = await worker.postRaw('/api/settings/pdf-preview/', { document: 'estimate' });
    expect(preview.status()).toBe(403);
  } finally {
    await worker.dispose();
  }
});

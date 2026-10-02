// Document PDF branding on Settings → Documents: the shared letterhead
// (logo upload/remove, logo position, company block), a document's text
// slots, and the sample-PDF preview. The spec removes its logo at the end;
// the text it saves is harmless to other specs (it only decorates PDFs).
import { expect, test } from '@playwright/test';
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
  await estimate.getByRole('textbox', { name: 'Below the totals' }).fill(terms);
  await estimate.getByRole('button', { name: 'Save Estimate text' }).click();
  await expect(estimate.getByText('saved')).toBeVisible();

  // Everything persisted across a reload.
  await openDocumentsTab(page);
  const reloaded = page.getByRole('group', { name: 'Letterhead' });
  await expect(reloaded.getByRole('textbox', { name: 'Company name' })).toHaveValue(company);
  await expect(reloaded.getByRole('radio', { name: 'Center' })).toBeChecked();
  await expect(reloaded.getByAltText('Current logo')).toBeVisible();
  await expect(
    page.getByRole('group', { name: 'Estimate', exact: true })
      .getByRole('textbox', { name: 'Below the totals' }),
  ).toHaveValue(terms);

  // The preview link serves a PDF built from the saved settings.
  const link = page.getByRole('link', { name: 'Preview Estimate PDF' });
  const href = await link.getAttribute('href');
  expect(href).toBe('/api/settings/pdf-preview/?document=estimate');
  const preview = await page.request.get(href);
  expect(preview.status()).toBe(200);
  expect(preview.headers()['content-type']).toBe('application/pdf');
  expect((await preview.body()).subarray(0, 4).toString()).toBe('%PDF');

  // Remove the logo.
  await reloaded.getByRole('button', { name: 'Remove logo' }).click();
  await expect(reloaded.getByAltText('Current logo')).toHaveCount(0);
  await expect(reloaded.getByText('No logo uploaded.')).toBeVisible();
});

test('a user without can_manage_config cannot reach the branding endpoints', async ({ browser }) => {
  const context = await browser.newContext({ storageState: personas.worker.storageState });
  const logo = await context.request.get('/api/settings/pdf-logo/');
  expect(logo.status()).toBe(403);
  const preview = await context.request.get('/api/settings/pdf-preview/?document=estimate');
  expect(preview.status()).toBe(403);
  await context.close();
});

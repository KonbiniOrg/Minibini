// Flat-fee schemes (docs/plans/2026-08-16-flat-fee-schemes.md): one shared
// flat_fee RateScheme (rate locked $0), each ServiceItem carrying its own
// amount; the amount resolves into line price at pick time and Task.rate at
// crystallization. This journey creates the scheme + a "Delivery" item
// through the real UI (configtime persona: settings + catalog), then
// consumes them on an estimate (finjobs persona) through acceptance.
import { expect, test } from '@playwright/test';
import { apiAs } from '../../fixtures/api.js';
import { personas } from '../../fixtures/personas.js';

const stamp = `e2e-ff-${Date.now().toString(36)}`;
const schemeName = `${stamp} Flat fee`;
const itemName = `${stamp} Delivery`;

test.describe('flat-fee catalog authoring (configtime)', () => {
  test.use({ storageState: personas.configtime.storageState });

  test('create a Flat fee scheme and an Amount-bearing Delivery item via UI', async ({ page }) => {
    await test.step('Scheme manager: Flat fee mode locks money to the items', async () => {
      await page.goto('/#/settings');
      await page.getByRole('button', { name: 'Pricing' }).click();
      await expect(page.getByRole('heading', { name: 'Rate Schemes' })).toBeVisible();
      await page.getByRole('button', { name: 'Add Rate Scheme' }).click();
      const dialog = page.getByRole('dialog');
      await dialog.getByLabel(/Name/).fill(schemeName);
      await dialog.getByLabel(/Algorithm/).selectOption('flat_fee');
      // No rate input; the explanation replaces it.
      // \s+ because the source wraps the sentence across lines and Playwright
      // regex matching runs against the raw (un-normalized) text.
      await expect(dialog.getByText(/amount lives\s+on each Service Item/)).toBeVisible();
      await expect(dialog.getByText('Rate *')).toHaveCount(0);
      await expect(dialog.getByText('Modifiers')).toHaveCount(0);
      await dialog.getByLabel('Unit').selectOption('ea');
      // First non-fallback accounting category.
      const acSelect = dialog.getByLabel(/Accounting Category/);
      await acSelect.selectOption({ index: 1 });
      await dialog.getByRole('button', { name: 'Save' }).click();
      await expect(page.getByRole('dialog')).toHaveCount(0);
      // Scoped to the table row — the new scheme also appears as an option
      // in the Default Rate Scheme dropdown (strict-mode collision).
      await expect(page.getByRole('cell', { name: schemeName })).toBeVisible();
    });

    await test.step('Catalog: Delivery item carries its own Amount — no modifier wording', async () => {
      await page.goto('/#/catalog/service-items');
      await page.getByRole('button', { name: 'Add Service Item' }).click();
      await page.getByLabel(/Name/).fill(itemName);
      const schemeSelect = page.getByLabel(/Rate Scheme/);
      await schemeSelect.selectOption({ label: new RegExp(schemeName) }).catch(async () => {
        // selectOption by label regex isn't supported everywhere — resolve the value.
        const value = await schemeSelect.locator(`option:has-text("${schemeName}")`).getAttribute('value');
        await schemeSelect.selectOption(value);
      });
      const amount = page.getByLabel(/Amount/);
      await expect(amount).toBeVisible();
      // The word "modifier" never renders on the flat-fee path (scoped to
      // the edit form, not the list table behind it).
      await expect(page.getByText(/Default Modifiers/)).toHaveCount(0);
      await amount.fill('50.00');
      await page.getByRole('button', { name: 'Save' }).click();
      await expect(page.getByLabel(/Amount/)).toHaveCount(0); // form closed
      await expect(page.getByText(itemName)).toBeVisible();
    });
  });
});

test.describe('flat-fee consumption on an estimate (finjobs)', () => {
  test.use({ storageState: personas.finjobs.storageState });

  test('Delivery prices the line at its amount; acceptance stamps the task and auto-releases', async ({ page }) => {
    const api = await apiAs(personas.finjobs);
    const contact = (await api.get('/api/contacts/?page_size=1')).results[0];
    const job = await api.post('/api/jobs/', { name: `${stamp} job`, contact: contact.contact_id });
    const estimate = await api.post('/api/estimates/', { job: job.job_id });

    // The catalog item from the authoring test (serial suite: it exists).
    const items = await api.get(`/api/service-items/?search=${encodeURIComponent(itemName)}`);
    const item = (items.results || items).find((s) => s.template_name === itemName);
    test.skip(!item, 'authoring test did not run first');
    expect(item.display_rate).toBe('50.00');

    await test.step('Add line → picker shows the amount → line lands 1 × $50', async () => {
      await page.goto(`/#/jobs/${job.job_id}/estimate/${estimate.estimate_id}`);
      await page.getByRole('button', { name: 'Add line' }).click();
      const dialog = page.getByRole('dialog');
      await dialog.getByPlaceholder(/search/i).fill(itemName);
      const row = dialog.getByRole('button', { name: new RegExp(itemName) });
      await expect(row).toContainText('50.00');
      await row.dispatchEvent('mousedown');
      // The follow-up add form (service pick): create with default qty 1.
      const addForm = page.getByRole('dialog');
      await addForm.getByRole('button', { name: /Add|Create/ }).click();
      const lineRow = page.locator('table.line-items-table tbody tr').filter({ hasText: itemName }).first();
      await expect(lineRow).toBeVisible();
      await expect(lineRow).toContainText('50.00');
    });

    await test.step('Accept via API → catalog line crystallizes task rate=50, job auto-releases', async () => {
      // mark-open requires a deliverable.
      await api.post(`/api/jobs/${job.job_id}/deliverables/`, {
        description: `${stamp} deliverable`, qty_ordered: '1', units: 'ea',
      });
      await api.patch(`/api/estimates/${estimate.estimate_id}/`, { status: 'open' });
      await api.patch(`/api/estimates/${estimate.estimate_id}/`, { status: 'accepted' });

      const fullJob = await api.get(`/api/jobs/${job.job_id}/`);
      expect(fullJob.status).toBe('in_progress'); // all-catalog → auto-release
      const task = (fullJob.tasks || []).find((t) => t.name === itemName);
      expect(task).toBeTruthy();
      expect(String(task.rate)).toMatch(/^50(\.00)?$/);
    });

    await api.dispose();
  });
});

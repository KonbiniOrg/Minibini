// RM 2026-08-11 — material-ness derives from the accounting category: the
// "Is this a material?" checkbox is retired everywhere. A freeform hand line
// IS a material exactly when its chosen AC is the configured
// default_material_accounting_category; any other AC makes a plain line. At
// acceptance the material line establishes a Material atom; the plain line
// crystallizes nothing (no-fee-surface.spec.js owns that half in depth).
//
// Built fresh (job + draft estimate) — same precedent as
// no-fee-surface.spec.js; the seed's configured Materials AC is read from
// /api/settings/.
import { expect, test } from '@playwright/test';
import { apiAs } from '../../fixtures/api.js';
import { personas } from '../../fixtures/personas.js';

test.use({ storageState: personas.finjobs.storageState });

const stamp = `e2e-matac-${Date.now().toString(36)}`;

test('freeform line with the Materials AC becomes a material (no checkbox anywhere); other ACs make a plain line', async ({ page }) => {
  const api = await apiAs(personas.finjobs);
  const contact = (await api.get('/api/contacts/?page_size=1')).results[0];

  // /api/settings/ needs can_manage_config — read the configured Materials
  // AC with the configtime persona, then do everything else as finjobs.
  const configApi = await apiAs(personas.configtime);
  const settings = await configApi.get('/api/settings/');
  await configApi.dispose();
  const matAcId = Number(settings.default_material_accounting_category);
  test.skip(!matAcId, 'seed gap: no default_material_accounting_category configured');
  const cats = await api.get('/api/accounting-categories/');
  const otherCat = (cats.results || cats)
    .find((c) => c.is_active !== false && !c.is_deposit && c.id !== matAcId);
  const matCat = (cats.results || cats).find((c) => c.id === matAcId);

  const job = await api.post('/api/jobs/', {
    name: `${stamp} job`, contact: contact.contact_id,
  });
  const estimate = await api.post('/api/estimates/', { job: job.job_id });

  const matLineDesc = `${stamp} raw stock`;
  await test.step('Add line → freeform: picker has no material checkbox; choosing the Materials AC saves the line', async () => {
    await page.goto(`/#/jobs/${job.job_id}/estimate/${estimate.estimate_id}`);
    await page.getByRole('button', { name: 'Add line' }).click();
    const picker = page.getByRole('dialog');
    await expect(picker.getByRole('button', { name: 'Add Line' })).toBeVisible();
    await expect(picker.getByRole('checkbox')).toHaveCount(0);
    await picker.getByPlaceholder(/search/i).fill(matLineDesc);
    await picker.getByRole('button', { name: 'Add Line' }).click();

    const form = page.getByRole('dialog');
    await form.getByLabel(/Quantity/).fill('3');
    await form.getByLabel(/^Price/).fill('40');
    await form.getByLabel(/Accounting Category/)
      .selectOption({ label: `${matCat.code} - ${matCat.name}` });
    await form.getByRole('button', { name: 'Add', exact: true }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);

    await expect(
      page.locator('table.line-items-table tr').filter({ hasText: matLineDesc }).first()
    ).toBeVisible();
  });

  await test.step('The saved line derived is_material=true; a second line on another AC derived false', async () => {
    const detail = await api.get(`/api/estimates/${estimate.estimate_id}/`);
    const matLine = detail.line_items.find((li) => li.description === matLineDesc);
    expect(matLine.is_material).toBe(true);

    const plain = await api.post(`/api/estimates/${estimate.estimate_id}/line-items/`, {
      description: `${stamp} design retainer`, qty: '1', units: 'ea',
      price: '100.00', accounting_category: otherCat.id,
    });
    expect(plain.is_material).toBe(false);
  });

  await test.step('Acceptance establishes a Material for the material-AC line only', async () => {
    await api.post(`/api/jobs/${job.job_id}/deliverables/`, {
      description: `${stamp} deliverable`, qty_ordered: '1', units: 'ea',
    });
    await api.patch(`/api/estimates/${estimate.estimate_id}/`, { status: 'open' });
    await api.patch(`/api/estimates/${estimate.estimate_id}/`, { status: 'accepted' });

    // Crystallization writes the claim: the material-AC line now carries a
    // source row resolving to the established Material; the plain line
    // stays sourceless (document-only).
    const detail = await api.get(`/api/estimates/${estimate.estimate_id}/`);
    const matLine = detail.line_items.find((li) => li.description === matLineDesc);
    const plainLine = detail.line_items.find(
      (li) => li.description === `${stamp} design retainer`);
    expect(matLine.sources.length).toBe(1);
    expect(matLine.sources[0].source_type).toBe('material');
    expect(plainLine.sources.length).toBe(0);
  });

  await api.dispose();
});

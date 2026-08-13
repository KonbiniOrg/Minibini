// Make Deliverable button (better-fees spec §6, RM 2026-08-12): a per-line
// estimate-edit action that mints a Deliverable from the line's
// description/qty/units with a source_line provenance FK. The FK suppresses
// the button once used, and removing a linked line asks whether the
// deliverable goes too (three-way dialog). Built fresh via API, same idiom
// as material-from-ac.spec.js.
import { expect, test } from '@playwright/test';
import { apiAs } from '../../fixtures/api.js';
import { personas } from '../../fixtures/personas.js';

test.use({ storageState: personas.finjobs.storageState });

const stamp = `e2e-mkdel-${Date.now().toString(36)}`;

test('Make Deliverable mints a linked deliverable, suppresses itself, and line removal offers the three-way choice', async ({ page }) => {
  const api = await apiAs(personas.finjobs);
  const contact = (await api.get('/api/contacts/?page_size=1')).results[0];
  const cats = await api.get('/api/accounting-categories/');
  const category = (cats.results || cats)
    .find((c) => c.is_active !== false && !c.is_deposit && !c.is_fallback);

  const job = await api.post('/api/jobs/', {
    name: `${stamp} job`, contact: contact.contact_id,
  });
  const estimate = await api.post('/api/estimates/', { job: job.job_id });
  const lineA = await api.post(`/api/estimates/${estimate.estimate_id}/line-items/`, {
    description: `${stamp} chairs`, qty: '3', units: 'ea', price: '500.00',
    accounting_category: category.id,
  });
  const lineB = await api.post(`/api/estimates/${estimate.estimate_id}/line-items/`, {
    description: `${stamp} table`, qty: '1', units: 'ea', price: '900.00',
    accounting_category: category.id,
  });

  const lineRow = (desc) =>
    page.locator('table.line-items-table tr')
      .filter({ hasText: desc })
      .filter({ has: page.locator('button', { hasText: 'Edit' }) });

  await test.step('Button mints the deliverable and suppresses itself', async () => {
    await page.goto(`/#/jobs/${job.job_id}/estimate/${estimate.estimate_id}`);
    const rowA = lineRow(`${stamp} chairs`);
    await expect(rowA.getByRole('button', { name: 'Make Deliverable' })).toBeVisible();
    await rowA.getByRole('button', { name: 'Make Deliverable' }).click();
    await expect(rowA.getByRole('button', { name: 'Make Deliverable' })).toHaveCount(0);

    const deliverables = await api.get(`/api/jobs/${job.job_id}/deliverables/`);
    const rows = deliverables.results || deliverables;
    const minted = rows.find((d) => d.description === `${stamp} chairs`);
    expect(minted).toBeTruthy();
    expect(Number(minted.qty_ordered)).toBe(3);
    expect(minted.units).toBe('ea');
  });

  await test.step('Removing a linked line: "keep deliverable" leaves it on the job', async () => {
    const rowA = lineRow(`${stamp} chairs`);
    await rowA.getByRole('button', { name: 'Remove' }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toContainText('Remove the deliverable as well?');
    await dialog.getByRole('button', { name: 'Remove line, keep deliverable' }).click();
    await expect(lineRow(`${stamp} chairs`)).toHaveCount(0);

    const deliverables = await api.get(`/api/jobs/${job.job_id}/deliverables/`);
    const rows = deliverables.results || deliverables;
    expect(rows.some((d) => d.description === `${stamp} chairs`)).toBe(true);
  });

  await test.step('Removing a linked line: "remove both" deletes the deliverable too', async () => {
    await api.post(
      `/api/estimates/${estimate.estimate_id}/line-items/${lineB.line_item_id}/make-deliverable/`);
    await page.reload();
    const rowB = lineRow(`${stamp} table`);
    await rowB.getByRole('button', { name: 'Remove' }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toContainText('Remove the deliverable as well?');
    await dialog.getByRole('button', { name: 'Remove line and deliverable' }).click();
    await expect(lineRow(`${stamp} table`)).toHaveCount(0);

    const deliverables = await api.get(`/api/jobs/${job.job_id}/deliverables/`);
    const rows = deliverables.results || deliverables;
    expect(rows.some((d) => d.description === `${stamp} table`)).toBe(false);
  });

  await api.dispose();
});

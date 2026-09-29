// Change-order deliverables gate (RM, feature/est-fixes 2026-09-29): the CO
// sibling of estimate-lifecycle/send-deliverables-gate.spec.js. Removing a
// deliverable is a legitimate CO diff, but the job can't be left with none —
// the server refuses to open such a CO (ChangeOrderService.
// assert_job_has_deliverables) and the panel's "Send to customer" pre-empts
// that by opening the deliverables editor with a notice. Deleting the last
// row in the CO's own deliverables section must re-arm the gate AND refresh
// the job-context band above it (the shared deliverables store), with no
// reload. Built fresh via API, same idiom as make-deliverable.spec.js.
import { expect, test } from '@playwright/test';
import { apiAs } from '../../fixtures/api.js';
import { personas } from '../../fixtures/personas.js';

test.use({ storageState: personas.finjobs.storageState });

const stamp = `e2e-cogate-${Date.now().toString(36)}`;
const NOTICE = 'Deliverables are required before this change order can be sent.';

test('Send to customer on a CO whose job has no deliverables routes through the deliverables editor', async ({ page }) => {
  const api = await apiAs(personas.finjobs);
  const contact = (await api.get('/api/contacts/?page_size=1')).results[0];
  const cats = await api.get('/api/accounting-categories/');
  const category = (cats.results || cats)
    .find((c) => c.is_active !== false && !c.is_deposit && !c.is_fallback);

  // Accepted estimate + one deliverable, job on hold → a draft CO.
  const job = await api.post('/api/jobs/', { name: `${stamp} job`, contact: contact.contact_id });
  const estimate = await api.post('/api/estimates/', { job: job.job_id });
  await api.post(`/api/estimates/${estimate.estimate_id}/line-items/`, {
    description: `${stamp} panel`, qty: '1', units: 'ea', price: '100.00',
    accounting_category: category.id,
  });
  await api.post(`/api/jobs/${job.job_id}/deliverables/`, {
    description: `${stamp} panel`, qty_ordered: '1', units: 'ea',
  });
  await api.patch(`/api/estimates/${estimate.estimate_id}/`, { status: 'open' });
  await api.patch(`/api/estimates/${estimate.estimate_id}/`, { status: 'accepted' });
  await api.post(`/api/jobs/${job.job_id}/hold/`, { reason: `${stamp} CO` });
  const co = await api.post('/api/change-orders/', { job: job.job_id });

  await page.goto(`/#/jobs/${job.job_id}/change-order/${co.change_order_id}`);
  const toggle = page.locator('.context-band-toggle');
  if ((await toggle.getAttribute('aria-expanded')) !== 'true') await toggle.click();
  const band = page.locator('.context-band .deliverables-panel');
  await expect(band).toContainText(`${stamp} panel`);

  await test.step('With a deliverable, Send to customer goes straight to the send page', async () => {
    await page.getByRole('button', { name: 'Send to customer' }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await expect(page).toHaveURL(new RegExp(`#/change-orders/${co.change_order_id}/send$`));
    await page.goBack();
    await expect(page.getByRole('button', { name: 'Send to customer' })).toBeVisible();
  });

  await test.step('Deleting the last row in the CO section refreshes the band above it (no reload)', async () => {
    const section = page.locator('section').filter({ has: page.getByRole('heading', { name: 'Deliverables' }) });
    await section.getByRole('button', { name: 'Delete' }).click();
    await expect(band).toContainText('No deliverables yet');
  });

  await test.step('Server guard: the CO cannot be marked open while the job has no deliverables', async () => {
    const resp = await api.patchRaw(`/api/change-orders/${co.change_order_id}/`, { status: 'open' });
    expect(resp.status()).toBe(400);
    expect(await resp.text()).toContain('no deliverables');
  });

  await test.step('Send to customer now opens the editor with the CO notice; Cancel stays put', async () => {
    await page.getByRole('button', { name: 'Send to customer' }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog.getByRole('heading', { name: 'Edit deliverables' })).toBeVisible();
    await expect(dialog.getByText(NOTICE)).toBeVisible();
    await dialog.getByRole('button', { name: 'Cancel' }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await expect(page).toHaveURL(new RegExp(`#/jobs/${job.job_id}/change-order/${co.change_order_id}$`));
  });

  await test.step('Add a deliverable through the gate → Save → lands on the send page', async () => {
    await page.getByRole('button', { name: 'Send to customer' }).click();
    const dialog = page.getByRole('dialog');
    await dialog.getByRole('button', { name: '+ Add row' }).click();
    await dialog.locator('tbody tr').last().locator('input').first().fill(`${stamp} replacement`);
    await dialog.getByRole('button', { name: 'Save' }).click();
    await expect(page).toHaveURL(new RegExp(`#/change-orders/${co.change_order_id}/send$`));
    const rows = await api.get(`/api/jobs/${job.job_id}/deliverables/`);
    expect((rows.results || rows).map((r) => r.description)).toContain(`${stamp} replacement`);
  });

  await api.dispose();
});

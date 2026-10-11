// Send Email deliverables gate (RM, feature/est-fixes 2026-09-28). The
// server refuses to open an estimate on a job with no deliverables
// (EstimateService.mark_open, jobs-and-tasks.md §12.3). Rather than let the
// user fill in the email form and then hit that error, the estimate panel's
// "Send Email" on such a job opens the deliverables editor with a
// "required" notice; saving at least one row carries on to the send page.
// The same editor opened from the job-context band's own link shows no
// notice. Send affordances are buttons in every state (RM 2026-09-29); the
// email step is DocumentSendModal over the panel (2026-10-10). Opening the
// send modal does no email work, so this stays clear of the live-SMTP
// exemption noted in change-orders/send-gate.spec.js.
import { expect, test } from '@playwright/test';
import { apiAs } from '../../fixtures/api.js';
import { personas } from '../../fixtures/personas.js';

test.use({ storageState: personas.finjobs.storageState });

const stamp = `e2e-sendgate-${Date.now().toString(36)}`;
const NOTICE = 'Deliverables are required before this estimate can be sent.';

test('Send Email on a job with no deliverables routes through the deliverables editor', async ({ page }) => {
  const api = await apiAs(personas.finjobs);
  const contact = (await api.get('/api/contacts/?page_size=1')).results[0];
  const job = await api.post('/api/jobs/', { name: `${stamp} job`, contact: contact.contact_id });
  const estimate = await api.post('/api/estimates/', { job: job.job_id });

  await page.goto(`/#/jobs/${job.job_id}/estimate/${estimate.estimate_id}`);

  await test.step('Send Email opens the editor with the required notice', async () => {
    await page.getByRole('button', { name: 'Send Email' }).click();
    const dialog = page.getByRole('dialog', { name: 'Edit deliverables' });
    await expect(dialog.getByRole('heading', { name: 'Edit deliverables' })).toBeVisible();
    await expect(dialog.getByText(NOTICE)).toBeVisible();
  });

  await test.step('Cancel → stays on the estimate, nothing sent', async () => {
    await page.getByRole('dialog').getByRole('button', { name: 'Cancel' }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await expect(page).toHaveURL(new RegExp(`#/jobs/${job.job_id}/estimate/${estimate.estimate_id}$`));
    await expect(page.getByRole('button', { name: 'Send Email' })).toBeVisible();
  });

  await test.step('The band\'s own Edit deliverables path shows no notice', async () => {
    const toggle = page.locator('.context-band-toggle');
    if ((await toggle.getAttribute('aria-expanded')) !== 'true') await toggle.click();
    await page.locator('.context-band .deliverables-panel').getByRole('button', { name: 'Add deliverables' }).click();
    const dialog = page.getByRole('dialog', { name: 'Edit deliverables' });
    await expect(dialog.getByRole('heading', { name: 'Edit deliverables' })).toBeVisible();
    await expect(dialog.getByText(NOTICE)).toHaveCount(0);
    await dialog.getByRole('button', { name: 'Cancel' }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);
  });

  await test.step('Add a deliverable via Send Email → Save → opens the send modal', async () => {
    await page.getByRole('button', { name: 'Send Email' }).click();
    const dialog = page.getByRole('dialog', { name: 'Edit deliverables' });
    await dialog.getByRole('button', { name: '+ Add row' }).click();
    await dialog.locator('tbody tr').last().locator('input').first().fill(`${stamp} widget`);
    await dialog.getByRole('button', { name: 'Save' }).click();
    const send = page.getByRole('dialog', { name: 'Send estimate' });
    await expect(send.getByRole('heading', { name: 'Send Estimate' })).toBeVisible();
    await expect(page).toHaveURL(new RegExp(`#/jobs/${job.job_id}/estimate/${estimate.estimate_id}$`));
    await send.getByRole('button', { name: 'Cancel' }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);

    const rows = await api.get(`/api/jobs/${job.job_id}/deliverables/`);
    expect((rows.results || rows).map((r) => r.description)).toContain(`${stamp} widget`);
  });

  await test.step('Back on the estimate, Send Email goes straight to the send modal now', async () => {
    await page.goto(`/#/jobs/${job.job_id}/estimate/${estimate.estimate_id}`);
    await page.getByRole('button', { name: 'Send Email' }).click();
    await expect(page.getByRole('dialog', { name: 'Edit deliverables' })).toHaveCount(0);
    await expect(page.getByRole('dialog', { name: 'Send estimate' })).toBeVisible();
    await page.getByRole('dialog', { name: 'Send estimate' }).getByRole('button', { name: 'Cancel' }).click();
  });

  await test.step('Deleting the last deliverable from the job-context band re-arms the gate without a reload', async () => {
    await page.goto(`/#/jobs/${job.job_id}/estimate/${estimate.estimate_id}`);
    const toggle = page.locator('.context-band-toggle');
    if ((await toggle.getAttribute('aria-expanded')) !== 'true') await toggle.click();
    await page.locator('.context-band .deliverables-panel').getByRole('button', { name: 'Edit' }).click();
    const dialog = page.getByRole('dialog', { name: 'Edit deliverables' });
    await dialog.locator('tbody tr').filter({ hasText: '' }).first().getByRole('button', { name: 'Delete' }).click();
    await dialog.getByRole('button', { name: 'Save' }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await expect(page.locator('.context-band .deliverables-panel')).toContainText('No deliverables yet');
    // The panel's Send Email learned about it through the deliverables store.
    await page.getByRole('button', { name: 'Send Email' }).click();
    await expect(page.getByRole('dialog', { name: 'Edit deliverables' }).getByText(NOTICE)).toBeVisible();
    await page.getByRole('dialog', { name: 'Edit deliverables' }).getByRole('button', { name: 'Cancel' }).click();
  });

  await api.dispose();
});

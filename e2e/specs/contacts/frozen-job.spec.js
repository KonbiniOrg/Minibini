// A closed job on an inactive contact is frozen (spec §5): banner, refused
// reopen, swap to a same-business contact unfreezes it.
import { expect, test } from '@playwright/test';
import { personas } from '../../fixtures/personas.js';
import { apiAs } from '../../fixtures/api.js';

test.use({ storageState: personas.finjobs.storageState });

test('frozen banner, refused reopen, contact swap unfreezes', async ({ page }) => {
  const api = await apiAs(personas.finjobs);
  const stamp = `e2e-${Date.now().toString(36)}`;
  let biz, a, b, job;
  try {
    a = await api.post('/api/contacts/', { first_name: `${stamp}-A`, last_name: 'Frz', email: `${stamp}-a@example.invalid` });
    biz = await api.post('/api/businesses/', { business_name: `${stamp} Frz Co`, default_contact_id: a.contact_id });
    await api.patch(`/api/contacts/${a.contact_id}/`, { business_id: biz.business_id });
    b = await api.post('/api/contacts/', { first_name: `${stamp}-B`, last_name: 'Frz', email: `${stamp}-b@example.invalid`, business_id: biz.business_id });
    job = await api.post('/api/jobs/', { name: `${stamp} frozen`, contact: b.contact_id });
    await api.patch(`/api/jobs/${job.job_id}/`, { status: 'rejected' });        // closed
    await api.post(`/api/contacts/${b.contact_id}/deactivate/`, {});
  } finally { await api.dispose(); }

  await page.goto(`/#/jobs/${job.job_id}`);
  await test.step('Banner names the inactive contact and offers Change contact…', async () => {
    await expect(page.getByText(/Frozen:/)).toBeVisible();
    await expect(page.getByRole('status').getByRole('link', { name: `${stamp}-B Frz` })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Change contact…' })).toBeVisible();
  });
  await test.step('Reopen is refused with the freeze sentence', async () => {
    const api2 = await apiAs(personas.finjobs);
    try {
      const resp = await api2.patchRaw(`/api/jobs/${job.job_id}/`, { status: 'submitted' });
      expect(resp.status()).toBe(400);
      expect((await resp.json()).detail).toContain('is inactive');
    } finally { await api2.dispose(); }
  });
  await test.step('Change contact… to A (same business) → banner gone; reopen now works', async () => {
    await page.getByRole('button', { name: 'Change contact…' }).click();
    const dialog = page.getByRole('dialog', { name: 'Change contact' });
    await dialog.getByPlaceholder(/contact/i).fill(`${stamp}-A`);
    await dialog.getByRole('button', { name: new RegExp(`${stamp}-A Frz`) }).click();
    await dialog.getByRole('button', { name: 'Save' }).click();
    await expect(page.getByText(/Frozen:/)).toHaveCount(0);
    const api3 = await apiAs(personas.finjobs);
    try { expect((await api3.patchRaw(`/api/jobs/${job.job_id}/`, { status: 'submitted' })).status()).toBe(200); }
    finally { await api3.dispose(); }
  });
});

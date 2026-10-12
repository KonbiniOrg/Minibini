// Deactivate / reactivate contacts and businesses (spec §4, §7.3–7.4).
import { expect, test } from '@playwright/test';
import { personas } from '../../fixtures/personas.js';
import { apiAs } from '../../fixtures/api.js';

test.use({ storageState: personas.finjobs.storageState });

async function freshBusiness(api, stamp, contacts = 2) {
  const first = await api.post('/api/contacts/', { first_name: `${stamp}-A`, last_name: 'Status', email: `${stamp}-a@example.invalid` });
  const biz = await api.post('/api/businesses/', { business_name: `${stamp} Status Co`, default_contact_id: first.contact_id });
  await api.patch(`/api/contacts/${first.contact_id}/`, { business_id: biz.business_id });
  const others = [];
  for (let i = 1; i < contacts; i++) {
    others.push(await api.post('/api/contacts/', { first_name: `${stamp}-${i}`, last_name: 'Status', email: `${stamp}-${i}@example.invalid`, business_id: biz.business_id }));
  }
  return { biz, first, others };
}

test('contact with an open job is blocked; a free contact deactivates, vanishes from the default list, shows under Inactive and in search', async ({ page }) => {
  const api = await apiAs(personas.finjobs);
  const stamp = `e2e-${Date.now().toString(36)}`;
  let biz, first, others, job;
  try {
    ({ biz, first, others } = await freshBusiness(api, stamp));
    job = await api.post('/api/jobs/', { name: `${stamp} job`, contact: others[0].contact_id });
  } finally { await api.dispose(); }

  await page.goto(`/#/contacts/${others[0].contact_id}`);
  await test.step('Deactivate → blocker sentence names the open job', async () => {
    await page.getByRole('button', { name: 'Deactivate' }).click();
    await expect(page.getByText(new RegExp(`1 open job \\(${job.job_number}\\)`))).toBeVisible();
  });
  await test.step('Cancel the job via the API, then Deactivate succeeds and the badge appears', async () => {
    const api2 = await apiAs(personas.finjobs);
    try { await api2.patch(`/api/jobs/${job.job_id}/`, { status: 'rejected' }); } finally { await api2.dispose(); }
    await page.getByRole('button', { name: 'Deactivate' }).click();
    await expect(page.locator('.customer-header').getByText('inactive')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Reactivate' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Edit' })).toHaveCount(0);
  });
  await test.step('Default list hides it; Inactive shows it; global search shows it with the badge', async () => {
    await page.goto('/#/contacts');
    await page.getByPlaceholder(/Search all contacts/).fill(`${stamp}-1`);
    await expect(page.getByText('No results found.')).toBeVisible();
    await page.getByRole('button', { name: 'Inactive' }).click();
    await expect(page.getByRole('link', { name: `${stamp}-1 Status` })).toBeVisible();
    await page.goto(`/#/search?q=${encodeURIComponent(`${stamp}-1`)}`);
    await expect(page.getByRole('link', { name: `${stamp}-1 Status` })).toBeVisible();
    await expect(page.getByText('inactive').first()).toBeVisible();
  });
});

test('business deactivation confirms with the contact count, cascades, and reactivation brings everyone back', async ({ page }) => {
  const api = await apiAs(personas.finjobs);
  const stamp = `e2e-${Date.now().toString(36)}`;
  let biz;
  try { ({ biz } = await freshBusiness(api, stamp, 3)); } finally { await api.dispose(); }

  await page.goto(`/#/businesses/${biz.business_id}`);
  await page.getByRole('button', { name: 'Deactivate' }).click();
  const dialog = page.getByRole('dialog', { name: 'Deactivate business' });
  await expect(dialog.getByText(/its 3 contact/)).toBeVisible();
  await dialog.getByRole('button', { name: 'Continue' }).click();
  await expect(page.locator('.customer-header').getByText('inactive')).toBeVisible();
  const contacts = page.locator('[data-section="contacts"]');
  await expect(contacts.getByText('inactive')).toHaveCount(3);
  await page.getByRole('button', { name: 'Reactivate' }).click();
  await expect(page.locator('.customer-header').getByText('inactive')).toHaveCount(0);
  await expect(contacts.getByText('inactive')).toHaveCount(0);
});

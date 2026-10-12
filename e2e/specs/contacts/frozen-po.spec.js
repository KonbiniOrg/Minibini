// A closed PO whose vendor contact is inactive is frozen (spec §5.2): banner
// with "Change contact…", swap to a same-vendor contact unfreezes it.
import { expect, test } from '@playwright/test';
import { personas } from '../../fixtures/personas.js';
import { apiAs } from '../../fixtures/api.js';

test.use({ storageState: personas.finjobs.storageState });

test('frozen PO banner, contact swap unfreezes', async ({ page }) => {
  const api = await apiAs(personas.finjobs);
  const stamp = `e2e-${Date.now().toString(36)}`;
  let biz, a, b, po;
  try {
    a = await api.post('/api/contacts/', { first_name: `${stamp}-A`, last_name: 'Pfz', email: `${stamp}-a@example.invalid` });
    biz = await api.post('/api/businesses/', { business_name: `${stamp} Pfz Co`, default_contact_id: a.contact_id });
    await api.patch(`/api/contacts/${a.contact_id}/`, { business_id: biz.business_id });
    b = await api.post('/api/contacts/', { first_name: `${stamp}-B`, last_name: 'Pfz', email: `${stamp}-b@example.invalid`, business_id: biz.business_id });
    po = await api.post('/api/purchase-orders/', { business: biz.business_id, contact: b.contact_id });
    await api.post(`/api/purchase-orders/${po.po_id}/line-items/`, { description: `${stamp} stock`, qty: '1', units: 'none', price: '10.00' });
    await api.patch(`/api/purchase-orders/${po.po_id}/`, { status: 'issued' });
    await api.post(`/api/purchase-orders/${po.po_id}/cancel/`, { reason: 'e2e freeze' });               // closed
    await api.post(`/api/contacts/${b.contact_id}/deactivate/`, {});
  } finally { await api.dispose(); }

  await page.goto(`/#/purchase-orders/${po.po_id}`);
  await test.step('Banner names the inactive contact and offers Change contact…', async () => {
    await expect(page.getByText(/Frozen:/)).toBeVisible();
    await expect(page.getByRole('button', { name: 'Change contact…' })).toBeVisible();
  });
  await test.step('Change contact… to A (same vendor) → banner gone', async () => {
    await page.getByRole('button', { name: 'Change contact…' }).click();
    const dialog = page.getByRole('dialog', { name: 'Change contact' });
    await dialog.getByPlaceholder(/contact/i).fill(`${stamp}-A`);
    await dialog.getByRole('button', { name: new RegExp(`${stamp}-A Pfz`) }).click();
    await dialog.getByRole('button', { name: 'Save' }).click();
    await expect(page.getByText(/Frozen:/)).toHaveCount(0);
  });
});

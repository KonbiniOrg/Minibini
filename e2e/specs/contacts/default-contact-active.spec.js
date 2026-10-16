// The default contact of an active business can only be deleted or moved
// when another ACTIVE contact can take over (RM 2026-10-11): the page hides
// Delete… while every sibling is inactive, the API refuses it outright, and
// reactivating a sibling restores the affordance.
import { expect, test } from '@playwright/test';
import { personas } from '../../fixtures/personas.js';
import { apiAs } from '../../fixtures/api.js';

test.use({ storageState: personas.finjobs.storageState });

test('default contact: Delete… hidden and refused while siblings are inactive; back once one is active', async ({ page }) => {
  const api = await apiAs(personas.finjobs);
  const stamp = `e2e-${Date.now().toString(36)}`;
  let a, b, biz, other;
  try {
    const oc = await api.post('/api/contacts/', { first_name: `${stamp}-O`, last_name: 'Dflt', email: `${stamp}-o@example.invalid` });
    other = await api.post('/api/businesses/', { business_name: `${stamp} Other Co`, default_contact_id: oc.contact_id });
    await api.patch(`/api/contacts/${oc.contact_id}/`, { business_id: other.business_id });
    a = await api.post('/api/contacts/', { first_name: `${stamp}-A`, last_name: 'Dflt', email: `${stamp}-a@example.invalid` });
    biz = await api.post('/api/businesses/', { business_name: `${stamp} Dflt Co`, default_contact_id: a.contact_id });
    await api.patch(`/api/contacts/${a.contact_id}/`, { business_id: biz.business_id });
    b = await api.post('/api/contacts/', { first_name: `${stamp}-B`, last_name: 'Dflt', email: `${stamp}-b@example.invalid`, business_id: biz.business_id });
    await api.post(`/api/contacts/${b.contact_id}/deactivate/`, {});
  } finally { await api.dispose(); }

  await page.goto(`/#/contacts/${a.contact_id}`);
  await test.step('Only sibling inactive: the default contact offers Deactivate but no Delete…', async () => {
    await expect(page.getByRole('button', { name: 'Deactivate' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Delete…' })).toHaveCount(0);
  });
  await test.step('Guard: the API refuses the delete and the move with the "no other active contact" sentence', async () => {
    const api2 = await apiAs(personas.finjobs);
    try {
      // (A null business_id is dropped by the viewset before the service — a
      // pre-existing quirk — so the move is exercised against another business.)
      const resp = await api2.patchRaw(`/api/contacts/${a.contact_id}/`, { business_id: other.business_id });
      expect(resp.status()).toBe(400);
      expect((await resp.json()).detail).toContain('no other active contact');
      let deleted = false;
      try { await api2.del(`/api/contacts/${a.contact_id}/?confirm=true`); deleted = true; } catch { /* refused */ }
      expect(deleted).toBe(false);
    } finally { await api2.dispose(); }
  });
  await test.step('Reactivate the sibling → Delete… is offered again', async () => {
    const api3 = await apiAs(personas.finjobs);
    try { await api3.post(`/api/contacts/${b.contact_id}/reactivate/`, {}); } finally { await api3.dispose(); }
    await page.reload();
    await expect(page.getByRole('button', { name: 'Delete…' })).toBeVisible();
  });
});

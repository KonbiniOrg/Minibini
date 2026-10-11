// Catalog merge and write-off are modals (2026-10-10; they were bordered
// in-page panels — docs/ui-flows/Inventory.md §write-off / §merge).
import { expect, test } from '@playwright/test';
import { apiAs } from '../../fixtures/api.js';
import { personas } from '../../fixtures/personas.js';

test.use({ storageState: personas.finjobs.storageState });

const stamp = `e2e-${Date.now().toString(36)}`;

test('Merge items modal folds a discard into a keep item', async ({ page }) => {
  const api = await apiAs(personas.finjobs);
  const cat = (await api.get('/api/accounting-categories/?page_size=1')).results[0];
  const mk = (suffix) => api.post('/api/inventory/', {
    code: `${stamp}-${suffix}`, description: `${stamp} ${suffix}`, units: 'ea',
    purchase_price: '1.00', selling_price: '2.00', accounting_category: cat.id,
  });
  const keep = await mk('KEEP');
  const discard = await mk('DISCARD');

  await page.goto('/#/catalog');
  await page.getByRole('button', { name: 'Merge items' }).click();
  const dialog = page.getByRole('dialog', { name: 'Merge items' });
  await expect(dialog).toBeVisible();
  await dialog.getByLabel('Keep (survivor):').selectOption(String(keep.inventory_item_id));
  await dialog.getByLabel('Discard (folded in & deleted):').selectOption(String(discard.inventory_item_id));
  await dialog.getByRole('button', { name: 'Merge', exact: true }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);

  await expect(page.getByRole('row', { name: new RegExp(`${stamp}-KEEP`) })).toBeVisible();
  await expect(page.getByRole('row', { name: new RegExp(`${stamp}-DISCARD`) })).toHaveCount(0);
  await api.dispose();
});

test('Write off modal records a partial write-off', async ({ page }) => {
  const api = await apiAs(personas.finjobs);
  const items = (await api.get('/api/inventory/?is_active=true&page_size=100')).results;
  const stocked = items.find((it) => Number(it.qty_on_hand) >= 1);
  await api.dispose();
  test.skip(!stocked, 'seed gap: no active inventory item with stock on hand');

  await page.goto('/#/catalog');
  const row = page.getByRole('row', { name: new RegExp(`^${stocked.code} `) }).first();
  await row.getByRole('button', { name: 'write off' }).click();
  const dialog = page.getByRole('dialog', { name: 'Write off' });
  await expect(dialog).toContainText(`Write off — ${stocked.code}`);
  await dialog.getByLabel('Quantity to write off:').fill('0.5');
  await dialog.getByLabel('Reason (optional):').fill(`${stamp} e2e partial`);
  await dialog.getByRole('button', { name: 'Confirm write-off' }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
});

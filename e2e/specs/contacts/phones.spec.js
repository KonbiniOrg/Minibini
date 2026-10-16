// Phone list editor round trip (contacts refine, 2026-10-11 —
// docs/plans/2026-10-11-contacts-refine-design.md §7.1).
import { expect, test } from '@playwright/test';
import { personas } from '../../fixtures/personas.js';
import { apiAs } from '../../fixtures/api.js';

test.use({ storageState: personas.finjobs.storageState });

test('add two numbers, reorder, save; the detail shows the new primary first', async ({ page }) => {
  const api = await apiAs(personas.finjobs);
  const stamp = `e2e-${Date.now().toString(36)}`;
  let contact;
  try {
    contact = await api.post('/api/contacts/', { first_name: stamp, last_name: 'Phones', email: `${stamp}@example.invalid` });
  } finally { await api.dispose(); }

  await page.goto(`/#/contacts/${contact.contact_id}`);
  await page.getByRole('button', { name: 'Edit' }).click();
  const dialog = page.getByRole('dialog', { name: 'Edit contact' });
  await test.step('Add phone twice, fill number + label', async () => {
    await dialog.getByRole('button', { name: 'Add phone' }).click();
    await dialog.getByLabel('Phone 1 number').fill('555-0100');
    await dialog.getByLabel('Phone 1 label').fill('cell');
    await dialog.getByRole('button', { name: 'Add phone' }).click();
    await dialog.getByLabel('Phone 2 number').fill('555-0200');
    await dialog.getByLabel('Phone 2 label').fill('A/P');
  });
  await test.step('Move phone 2 up → it becomes primary; Save', async () => {
    await dialog.getByRole('button', { name: 'Move phone 2 up' }).click();
    await expect(dialog.getByLabel('Phone 1 number')).toHaveValue('555-0200');
    await dialog.getByRole('button', { name: 'Save' }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);
  });
  await test.step('Detail lists A/P first; the list page shows the primary', async () => {
    const panel = page.locator('.identity .panel').first();
    const numbers = await panel.locator('dd a[href^="tel:"]').allTextContents();
    expect(numbers).toEqual(['555-0200', '555-0100']);
    await page.goto('/#/contacts');
    await page.getByPlaceholder(/Search all contacts/).fill('555 0200');
    await expect(page.getByRole('link', { name: `${stamp} Phones` })).toBeVisible();
  });
});

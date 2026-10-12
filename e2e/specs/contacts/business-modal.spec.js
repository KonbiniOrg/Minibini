// Business create/edit moved from /businesses/new + /:id/edit pages into
// BusinessFormModal (2026-10-10). Create runs check-name → contact →
// business and lands on the new business; edit stays on the detail page;
// a name collision is an in-modal sub-state.
import { expect, test } from '@playwright/test';
import { personas } from '../../fixtures/personas.js';

test.use({ storageState: personas.finjobs.storageState });

const stamp = `e2e-${Date.now().toString(36)}`;

test('list → New Business modal → create lands on the business; Edit stays; duplicate name is a sub-state', async ({ page }) => {
  await page.goto('/#/contacts');
  await page.getByRole('button', { name: 'New Business' }).click();
  const dialog = page.getByRole('dialog', { name: 'New business' });
  await expect(dialog).toBeVisible();

  const name = `${stamp} Biz`;

  await test.step('create → navigates to the new business', async () => {
    await dialog.getByLabel('Business Name *').fill(name);
    await dialog.getByLabel('First Name *').fill('Ann');
    await dialog.getByLabel('Last Name *').fill(stamp);
    await dialog.getByLabel('Email *').fill(`${stamp}-biz@example.invalid`);
    const dialogContact = dialog.getByRole('group', { name: 'Default Contact' });
    await dialogContact.getByRole('button', { name: 'Add phone' }).click();
    await dialogContact.getByLabel('Phone 1 number').fill('555-0101');
    await dialog.getByRole('button', { name: 'Create' }).click();
    await expect(page).toHaveURL(/#\/businesses\/\d+$/);
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await expect(page.getByText(name).first()).toBeVisible();
  });

  await test.step('Edit → save stays on the detail page', async () => {
    await page.getByRole('button', { name: 'Edit' }).click();
    const edit = page.getByRole('dialog', { name: 'Edit business' });
    await edit.getByLabel('Business Name *').fill(`${name} Renamed`);
    await edit.getByRole('button', { name: 'Save' }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await expect(page).toHaveURL(/#\/businesses\/\d+$/);
    await expect(page.getByText(`${name} Renamed`).first()).toBeVisible();
  });

  await test.step('duplicate name → notice inside the same modal → Go Back keeps the values', async () => {
    await page.goto('/#/contacts');
    await page.getByRole('button', { name: 'New Business' }).click();
    const dup = page.getByRole('dialog', { name: 'New business' });
    await dup.getByLabel('Business Name *').fill(`${name} Renamed`);
    await dup.getByLabel('First Name *').fill('Dup');
    await dup.getByLabel('Last Name *').fill('Licate');
    await dup.getByLabel('Email *').fill(`${stamp}-dup@example.invalid`);
    const dupContact = dup.getByRole('group', { name: 'Default Contact' });
    await dupContact.getByRole('button', { name: 'Add phone' }).click();
    await dupContact.getByLabel('Phone 1 number').fill('555-0102');
    await dup.getByRole('button', { name: 'Create' }).click();
    await expect(dup.getByText('This business may already exist')).toBeVisible();
    await expect(page.getByRole('dialog')).toHaveCount(1);
    await dup.getByRole('button', { name: 'Go Back and Edit' }).click();
    await expect(dup.getByLabel('Business Name *')).toHaveValue(`${name} Renamed`);
    await dup.getByRole('button', { name: 'Cancel' }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);
  });
});

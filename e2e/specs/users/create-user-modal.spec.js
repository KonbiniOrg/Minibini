// User creation moved from /users/new into UserCreateModal over the users
// list (2026-10-10); a create lands on the new user's detail page.
import { expect, test } from '@playwright/test';
import { personas } from '../../fixtures/personas.js';

test.use({ storageState: personas.configtime.storageState });

const stamp = `e2e-${Date.now().toString(36)}`;

test('users list → New user modal → create lands on the user', async ({ page }) => {
  await page.goto('/#/users');
  await page.getByRole('button', { name: 'New user' }).click();
  const dialog = page.getByRole('dialog', { name: 'New user' });
  await expect(dialog).toBeVisible();
  await dialog.getByLabel('Username *').fill(stamp);
  await dialog.getByLabel('Email *').fill(`${stamp}@example.invalid`);
  await dialog.getByLabel('First name *').fill('New');
  await dialog.getByLabel('Last name *').fill('User');
  await dialog.getByLabel('Password *', { exact: true }).fill('e2e_password_1');
  await dialog.getByLabel('Confirm password *').fill('e2e_password_1');
  await dialog.getByRole('button', { name: 'Create user' }).click();
  await expect(page).toHaveURL(/#\/users\/\d+$/);
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(page.getByRole('heading', { name: `User: ${stamp}` })).toBeVisible();
});

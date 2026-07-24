// Payment-terms manager on Settings → Business: modal create/edit, the
// two-phase confirm delete, and the new term appearing in a business
// form's assignment select. (The terms QBO import panel needs a live QBO
// connection — backend+Vitest territory, like the other import panels.)
import { expect, test } from '@playwright/test';
import { personas } from '../../fixtures/personas.js';

// Superuser: the manager is config-gated but the business-form check
// needs jobs powers too.
test.use({ storageState: personas.superuser.storageState });

test('terms CRUD roundtrip and business-form visibility', async ({ page }) => {
  await page.goto('/#/settings');
  await page.getByRole('button', { name: 'Business' }).click();
  await expect(page.getByRole('heading', { name: 'Payment terms' })).toBeVisible();

  // Create via the modal (scope to it — the settings form has its own Save).
  await page.getByRole('button', { name: '+ New terms' }).click();
  const createModal = page.getByLabel('New payment terms');
  await createModal.getByRole('textbox', { name: 'Name' }).fill('Net 45 E2E');
  await createModal.getByRole('spinbutton', { name: 'Days until due' }).fill('45');
  await createModal.getByRole('button', { name: 'Save' }).click();
  const row = page.locator('tr', { hasText: 'Net 45 E2E' });
  await expect(row).toBeVisible();
  await expect(row).toContainText('45');

  // Duplicate name is rejected in the modal, under the name field.
  await page.getByRole('button', { name: '+ New terms' }).click();
  await createModal.getByRole('textbox', { name: 'Name' }).fill('net 45 e2e');
  await createModal.getByRole('button', { name: 'Save' }).click();
  await expect(createModal.getByText(/already exist/i)).toBeVisible();
  await createModal.getByRole('button', { name: 'Cancel' }).click();

  // Edit via the modal.
  await row.getByRole('button', { name: 'Edit' }).click();
  const editModal = page.getByLabel('Edit payment terms');
  await editModal.getByRole('textbox', { name: 'Name' }).fill('Net 45 EOM E2E');
  await editModal.getByRole('button', { name: 'Save' }).click();
  await expect(page.locator('tr', { hasText: 'Net 45 EOM E2E' })).toBeVisible();

  // The new term is offered on the business form's assignment select.
  await page.goto('/#/businesses/new');
  await expect(page.locator('#terms option', { hasText: 'Net 45 EOM E2E' }))
    .toHaveCount(1);

  // Two-phase delete: accept the confirm quoting the impact.
  await page.goto('/#/settings');
  await page.getByRole('button', { name: 'Business' }).click();
  const doomed = page.locator('tr', { hasText: 'Net 45 EOM E2E' });
  await expect(doomed).toBeVisible();
  page.on('dialog', (d) => {
    expect(d.message()).toContain('Net 45 EOM E2E');
    d.accept();
  });
  await doomed.getByRole('button', { name: 'Delete' }).click();
  await expect(page.locator('tr', { hasText: 'Net 45 EOM E2E' })).toHaveCount(0);
});

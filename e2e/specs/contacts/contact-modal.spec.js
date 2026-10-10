// Contact create/edit moved from /contacts/new + /:id/edit pages into
// ContactFormModal (2026-10-10). The modal opens over the current page; a
// create lands on the new contact, an edit stays on the detail page, and
// duplicate detection is an in-modal sub-state.
import { expect, test } from '@playwright/test';
import { personas } from '../../fixtures/personas.js';

const stamp = `e2e-${Date.now().toString(36)}`;

test.describe('with can_manage_jobs', () => {
  test.use({ storageState: personas.finjobs.storageState });

  test('list → New Contact modal → create lands on the contact; Edit stays; duplicate is a sub-state', async ({ page }) => {
    await page.goto('/#/contacts');
    await page.getByRole('button', { name: 'New Contact' }).click();
    const dialog = page.getByRole('dialog', { name: 'New contact' });
    await expect(dialog).toBeVisible();

    await test.step('create → navigates to the new contact', async () => {
      await dialog.getByLabel('First Name *').fill(stamp);
      await dialog.getByLabel('Last Name *').fill('Modal');
      await dialog.getByLabel('Email *').fill(`${stamp}@example.invalid`);
      await dialog.getByLabel('Mobile').fill('555-0100'); // a phone is required server-side
      await dialog.getByRole('button', { name: 'Create' }).click();
      await expect(page).toHaveURL(/#\/contacts\/\d+$/);
      await expect(page.getByRole('dialog')).toHaveCount(0);
      await expect(page.getByText(`${stamp} Modal`).first()).toBeVisible();
    });

    await test.step('Edit → save stays on the detail page', async () => {
      await page.getByRole('button', { name: 'Edit' }).click();
      const edit = page.getByRole('dialog', { name: 'Edit contact' });
      await edit.getByLabel('Last Name *').fill('Renamed');
      await edit.getByRole('button', { name: 'Save' }).click();
      await expect(page.getByRole('dialog')).toHaveCount(0);
      await expect(page).toHaveURL(/#\/contacts\/\d+$/);
      await expect(page.getByText(`${stamp} Renamed`).first()).toBeVisible();
    });

    await test.step('duplicate email → notice inside the same modal → Go Back keeps the values', async () => {
      await page.goto('/#/contacts');
      await page.getByRole('button', { name: 'New Contact' }).click();
      const dup = page.getByRole('dialog', { name: 'New contact' });
      await dup.getByLabel('First Name *').fill('Dup');
      await dup.getByLabel('Last Name *').fill('Licate');
      await dup.getByLabel('Email *').fill(`${stamp}@example.invalid`);
      await dup.getByLabel('Mobile').fill('555-0100');
      await dup.getByRole('button', { name: 'Create' }).click();
      await expect(dup.getByText('This contact may already exist')).toBeVisible();
      await expect(page.getByRole('dialog')).toHaveCount(1);
      await dup.getByRole('button', { name: 'Go Back and Edit' }).click();
      await expect(dup.getByLabel('First Name *')).toHaveValue('Dup');
      await dup.getByRole('button', { name: 'Cancel' }).click();
      await expect(page.getByRole('dialog')).toHaveCount(0);
    });
  });
});

test.describe('without can_manage_jobs', () => {
  test.use({ storageState: personas.worker.storageState });

  test('a worker sees no New Contact button', async ({ page }) => {
    await page.goto('/#/contacts');
    await expect(page.getByRole('heading', { name: /Contacts/ })).toBeVisible();
    await expect(page.getByRole('button', { name: 'New Contact' })).toHaveCount(0);
  });
});

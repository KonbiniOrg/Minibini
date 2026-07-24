// Global tag deletion from the combined Contacts & Businesses list: a tag
// applied to both a contact and a business is removed from both in one
// action via the tag-filter chip's "x", after an impact-count confirm.
// Workers without can_manage_jobs never see the delete affordance.
import { expect, test } from '@playwright/test';
import { personas } from '../../fixtures/personas.js';
import { apiAs } from '../../fixtures/api.js';

const CONTACT_ID = 1; // Aisha Hamilton
const BUSINESS_ID = 1; // Abinari

test.describe('Global tag deletion', () => {
  test.use({ storageState: personas.finjobs.storageState });

  let tagName;

  test.beforeEach(async () => {
    tagName = `e2e-rush-${Date.now().toString(36)}`;
    const api = await apiAs(personas.finjobs);
    await api.post(`/api/contacts/${CONTACT_ID}/add-tag/`, { name: tagName });
    await api.post(`/api/businesses/${BUSINESS_ID}/add-tag/`, { name: tagName });
    await api.dispose();
  });

  test('deleting a tag chip removes it from every contact and business', async ({ page }) => {
    await page.goto('/#/contacts');

    const chipWrap = page.locator('.tag-chip-wrap', { hasText: tagName });
    await expect(chipWrap).toBeVisible();
    await chipWrap.getByRole('button', { name: `Delete "${tagName}" everywhere` }).click();

    // Impact-count confirm names both affected entities.
    await expect(page.getByText(`Delete tag "${tagName}"?`)).toBeVisible();
    await expect(page.getByText('This removes it from 1 contact(s) and 1 business(es).')).toBeVisible();

    await page.getByRole('button', { name: 'Yes, delete' }).click();

    // Chip is gone from the filter row, and the tag no longer shows on
    // either row's tag cell.
    await expect(page.locator('.tag-chip-wrap', { hasText: tagName })).toHaveCount(0);
    const aishaRow = page.locator('tr', { hasText: 'Aisha Hamilton' });
    await expect(aishaRow.getByText(tagName)).toHaveCount(0);
    const abinariRow = page.locator('tr', { hasText: 'Abinari' });
    await expect(abinariRow.getByText(tagName)).toHaveCount(0);
  });

  test('cancelling the confirm leaves the tag in place', async ({ page }) => {
    await page.goto('/#/contacts');

    const chipWrap = page.locator('.tag-chip-wrap', { hasText: tagName });
    await chipWrap.getByRole('button', { name: `Delete "${tagName}" everywhere` }).click();
    await expect(page.getByText(`Delete tag "${tagName}"?`)).toBeVisible();

    await page.getByRole('button', { name: 'Cancel' }).click();
    await expect(page.getByText(`Delete tag "${tagName}"?`)).toHaveCount(0);
    await expect(page.locator('.tag-chip-wrap', { hasText: tagName })).toBeVisible();
  });
});

test.describe('Global tag deletion — permission guard', () => {
  test.use({ storageState: personas.worker.storageState });

  test('a worker without can_manage_jobs sees tag chips with no delete control', async ({ page }) => {
    const tagName = `e2e-guard-${Date.now().toString(36)}`;
    const api = await apiAs(personas.finjobs);
    await api.post(`/api/contacts/${CONTACT_ID}/add-tag/`, { name: tagName });
    await api.dispose();

    await page.goto('/#/contacts');
    const chipWrap = page.locator('.tag-chip-wrap', { hasText: tagName });
    await expect(chipWrap).toBeVisible();
    await expect(chipWrap.getByRole('button', { name: `Delete "${tagName}" everywhere` })).toHaveCount(0);
  });
});

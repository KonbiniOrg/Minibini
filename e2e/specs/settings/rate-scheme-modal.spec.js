// Rate-scheme manager on Settings → Pricing. The add/edit form moved from an
// inline fieldset in the page flow into the shared Modal shell (2026-07-30),
// joining every other record create/edit surface. Behaviour is unchanged —
// this covers the shell wiring in the real app: the form opens in a dialog,
// Escape closes it, and a create still round-trips.
import { expect, test } from '@playwright/test';
import { apiAs } from '../../fixtures/api.js';
import { personas } from '../../fixtures/personas.js';

test.use({ storageState: personas.configtime.storageState });

const stamp = `e2e-rs-${Date.now().toString(36)}`;

async function openPricingTab(page) {
  await page.goto('/#/settings');
  await page.getByRole('button', { name: 'Pricing' }).click();
  await expect(page.getByRole('heading', { name: 'Rate Schemes' })).toBeVisible();
}

test('add form opens in the modal shell, Escape closes it', async ({ page }) => {
  await openPricingTab(page);

  await page.getByRole('button', { name: 'Add Rate Scheme' }).click();
  const modal = page.getByLabel('New Rate Scheme');
  await expect(modal).toBeVisible();
  // The fields are inside the dialog, not loose in the page.
  await expect(modal.getByRole('textbox', { name: 'Name' })).toBeVisible();

  await page.keyboard.press('Escape');
  await expect(modal).toBeHidden();
  // ...and the list underneath is still there.
  await expect(page.getByRole('button', { name: 'Add Rate Scheme' })).toBeVisible();
});

test('creating a scheme through the modal round-trips to the list', async ({ page }) => {
  await openPricingTab(page);

  await page.getByRole('button', { name: 'Add Rate Scheme' }).click();
  const modal = page.getByLabel('New Rate Scheme');
  await modal.getByRole('textbox', { name: 'Name' }).fill(stamp);
  await modal.getByRole('spinbutton', { name: 'Rate' }).fill('42');
  // Default algorithm is elapsed_time, whose unit is locked to 'hour' (see
  // the unit-lock test below) — pick entered_qty here so Unit label is a
  // free <select> this generic create test can exercise.
  await modal.getByLabel('Algorithm *').selectOption('entered_qty');
  await modal.getByLabel('Unit').selectOption({ index: 1 });
  await modal.getByLabel('Accounting Category').selectOption({ index: 1 });
  await modal.getByRole('button', { name: 'Save' }).click();

  await expect(modal).toBeHidden();
  await expect(page.locator('tr', { hasText: stamp })).toBeVisible();
});

test('editing an existing scheme opens the modal prefilled', async ({ page }) => {
  // Built here rather than found in the seed: every scheme now offers Edit
  // regardless of reference count (supersession removed, task-owned-money
  // Phase 1 — see specs/settings/rate-scheme-presets.spec.js for that
  // coverage). A fresh scheme just keeps this test isolated from other
  // specs mutating seeded rows.
  const name = `${stamp}-edit`;
  const api = await apiAs(personas.configtime);
  const cats = await api.get('/api/accounting-categories/');
  const units = await api.get('/api/settings/units/');
  await api.post('/api/rate-schemes/', {
    name, description: '', algorithm: 'elapsed_time', rate: '19',
    unit_label: units.find((u) => u !== 'none') || units[0],
    modifiers: [], accounting_category: (cats.results || cats)[0].id,
  });
  await api.dispose();

  await openPricingTab(page);
  const row = page.locator('tr', { hasText: name });
  await row.getByRole('button', { name: 'Edit' }).click();

  const modal = page.getByLabel('Edit Rate Scheme');
  await expect(modal).toBeVisible();
  await expect(modal.getByRole('textbox', { name: 'Name' })).toHaveValue(name);
});

test('elapsed-time schemes lock the unit to hour; switching algorithm frees it again', async ({ page }) => {
  // Time-based billing/scheduling is denominated in 'hour' (apps/core/units.py
  // HOUR_UNIT) — elapsed_time schemes are pinned to it everywhere, including
  // this form.
  await openPricingTab(page);
  await page.getByRole('button', { name: 'Add Rate Scheme' }).click();
  const modal = page.getByLabel('New Rate Scheme');

  await modal.getByLabel('Algorithm *').selectOption('elapsed_time');
  const unitControl = modal.getByLabel('Unit');
  await expect(unitControl).toBeVisible();
  await expect(unitControl).toBeDisabled();
  await expect(unitControl).toHaveValue('hour');

  await modal.getByLabel('Algorithm *').selectOption('entered_qty');
  const unitSelect = modal.getByLabel('Unit');
  await expect(unitSelect).toBeVisible();
  await expect(unitSelect).toBeEnabled();
  // A real, empty-by-default <select> — not the locked stand-in.
  await expect(unitSelect).toHaveValue('');
});

test('Settings → Setup → Units: hour and none carry no Remove button', async ({ page }) => {
  await page.goto('/#/settings');
  await page.getByRole('button', { name: 'Setup' }).click();
  await expect(page.getByRole('heading', { name: 'Units' })).toBeVisible();

  const hourRow = page.locator('tr', { hasText: 'hour' });
  const noneRow = page.locator('tr', { hasText: 'none' });
  await expect(hourRow).toBeVisible();
  await expect(noneRow).toBeVisible();
  await expect(hourRow.getByRole('button', { name: 'Remove' })).toHaveCount(0);
  await expect(noneRow.getByRole('button', { name: 'Remove' })).toHaveCount(0);
});

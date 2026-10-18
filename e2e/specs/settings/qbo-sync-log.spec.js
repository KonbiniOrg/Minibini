// Settings → QBO Log tab (Settings.md §2): the read-only QBOSyncLog table.
// Leans entirely on the seed's three qbo.qbosynclog rows (a cron-style
// customer reactivate, a superuser invoice create, a failed expense push) —
// the log is append-only and has no UI write path, so nothing is created.
import { expect, test } from '@playwright/test';
import { personas } from '../../fixtures/personas.js';
import { apiAs } from '../../fixtures/api.js';

test.use({ storageState: personas.configtime.storageState });

async function openLogTab(page) {
  await page.goto('/#/settings');
  await page.getByRole('button', { name: 'QBO Log' }).click();
  await expect(page.getByRole('heading', { name: 'QBO Log' })).toBeVisible();
}

test('QBO Log tab lists every seeded sync attempt, newest first', async ({ page }) => {
  await openLogTab(page);

  await test.step('Tab shows one row per log entry: seeded rows are listed', async () => {
    await expect(page.locator('tr', { hasText: 'expense #3' })).toBeVisible();
    await expect(page.locator('tr', { hasText: 'invoice #1' })).toBeVisible();
    await expect(page.locator('tr', { hasText: 'customer #5' })).toBeVisible();
  });

  await test.step('Newest first: the failed expense push (latest) is the top row', async () => {
    const firstRow = page.locator('table.data-table tbody tr').first();
    await expect(firstRow).toContainText('expense #3');
  });

  await test.step('Failed row carries its status pill and error text', async () => {
    const failed = page.locator('tr', { hasText: 'expense #3' });
    await expect(failed.locator('.status-badge')).toHaveText('failed');
    await expect(failed).toContainText('QuickBooks is not connected.');
    const ok = page.locator('tr', { hasText: 'invoice #1' });
    await expect(ok.locator('.status-badge')).toHaveText('success');
  });

  await test.step('Status filter: Failed narrows to the failed row only', async () => {
    await page.getByLabel('Status').selectOption('failed');
    await expect(page.locator('tr', { hasText: 'expense #3' })).toBeVisible();
    await expect(page.locator('tr', { hasText: 'invoice #1' })).toHaveCount(0);
    await expect(page.locator('tr', { hasText: 'customer #5' })).toHaveCount(0);
  });

  await test.step('Entity filter: Invoice shows the invoice row (status reset to All first)', async () => {
    await page.getByLabel('Status').selectOption('');
    await page.getByLabel('Entity').selectOption('invoice');
    await expect(page.locator('tr', { hasText: 'invoice #1' })).toBeVisible();
    await expect(page.locator('tr', { hasText: 'expense #3' })).toHaveCount(0);
  });
});

test('config admin sees the QBO Sync Failures panel on the Accounting tab without a permission error', async ({ page }) => {
  await page.goto('/#/settings');
  const panel = page.locator('section.qbo-sync-failures');
  await expect(panel.getByRole('heading', { name: 'QBO Sync Failures' })).toBeVisible();
  await expect(panel.getByRole('alert')).toHaveCount(0);
  // Seed has no sync_failed money records, so the panel reports the empty state.
  await expect(panel.getByText('No QBO sync failures.')).toBeVisible();
});

test('guard: a worker with no atoms is refused the sync-log API', async () => {
  const api = await apiAs(personas.worker);
  try {
    const res = await api.getRaw('/api/qbo/sync-log/');
    expect(res.status()).toBe(403);
  } finally {
    await api.dispose();
  }
});

test('a financials-only user can read the sync log too', async () => {
  const api = await apiAs(personas.finjobs);
  try {
    const data = await api.get('/api/qbo/sync-log/');
    expect(data.count).toBeGreaterThanOrEqual(3);
  } finally {
    await api.dispose();
  }
});

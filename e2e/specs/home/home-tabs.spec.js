// Home tab reorganization: the Work tab is task-centric (Current Tasks →
// Jobs I manage → Recent, with Recent Jobs gone), and the timeslips/work-
// sessions table moved to the Shifts tab as "My Timeslips", sitting between
// My Shifts and My Change Requests.
import { expect, test } from '@playwright/test';
import { personas } from '../../fixtures/personas.js';

test.use({ storageState: personas.worker.storageState });

test('Work tab: Current Tasks, Jobs I manage, Recent — no Recent Jobs', async ({ page }) => {
  await page.goto('/#/');
  await expect(page.getByRole('heading', { name: 'Current Tasks' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Jobs I manage' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Recent', exact: true })).toBeVisible();
  // The retired Recent Jobs list must be gone.
  await expect(page.getByRole('heading', { name: 'Recent Jobs' })).toHaveCount(0);
});

test('Shifts tab: My Timeslips sits between My Shifts and My Change Requests', async ({ page }) => {
  await page.goto('/#/');
  await page.getByRole('button', { name: 'Shifts' }).click();
  await expect(page.getByRole('heading', { name: 'My Timeslips' })).toBeVisible();

  const headings = await page.getByRole('heading', { level: 3 }).allInnerTexts();
  const shifts = headings.indexOf('My Shifts');
  const slips = headings.indexOf('My Timeslips');
  const reqs = headings.indexOf('My Change Requests');
  expect(shifts).toBeGreaterThanOrEqual(0);
  expect(slips).toBeGreaterThan(shifts);
  expect(reqs).toBeGreaterThan(slips);
});

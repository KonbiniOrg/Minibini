// PM visibility: the "jobs managed by X" list now appears on the home page
// ("Jobs I manage") and the user-detail page ("Jobs managed"), and the job
// board's per-worker column header links to that user's PM-filtered list.
// The list itself is the same PmJobList component in all three places.
import { expect, test } from '@playwright/test';
import { apiAs } from '../../fixtures/api.js';
import { personas } from '../../fixtures/personas.js';

// Superuser bypasses every atom, so one persona can both create the job
// (setting project_manager) and view the user-admin detail page.
test.use({ storageState: personas.superuser.storageState });

const stamp = `e2e-${Date.now().toString(36)}`;
let me;
let job;

test.beforeAll(async () => {
  const api = await apiAs(personas.superuser);
  me = await api.get('/api/auth/me/');
  const contact = (await api.get('/api/contacts/?page_size=1')).results[0];
  // A job managed by the persona under test — the flow under test IS this
  // job's appearance in the PM-scoped lists (e2e-testing.md §2 layering rule).
  job = await api.post('/api/jobs/', {
    name: `${stamp} pm-visibility`,
    contact: contact.contact_id,
    project_manager: me.id,
  });
  await api.dispose();
});

test('home page "Jobs I manage" lists jobs the current user manages', async ({ page }) => {
  await page.goto('/#/');
  // Work tab is the default landing tab.
  await expect(page.getByRole('heading', { name: 'Jobs I manage' })).toBeVisible();
  await expect(page.getByText(job.job_number).first()).toBeVisible();
});

test('user-detail "Jobs managed" lists that user\'s jobs', async ({ page }) => {
  await page.goto(`/#/users/${me.id}`);
  await expect(page.getByRole('heading', { name: 'Jobs managed' })).toBeVisible();
  await expect(page.getByText(job.job_number).first()).toBeVisible();
});

test('board worker-column header links to that user\'s PM-filtered job list', async ({ page }) => {
  await page.goto('/#/jobs/board');
  // Worker columns only render for the In-Progress lane when tasks are
  // assigned; skip cleanly if the seed has no such column on this run.
  const workerLink = page.locator('a.worker-name').first();
  const hasColumn = await workerLink.count();
  test.skip(!hasColumn, 'seed gap: no worker columns on the board');

  const href = await workerLink.getAttribute('href');
  expect(href).toMatch(/^#\/jobs\?pm=\d+$/);

  await workerLink.click();
  await expect(page.getByRole('heading', { name: /Jobs managed by/ })).toBeVisible();
});

// Creating a job from scratch in the SPA. The board is the jobs landing page
// (the sidebar's "Jobs" link), so it carries the New Job entry point — before
// this, /jobs/new was only reachable from a contact/business detail page or by
// typing the URL. RM 2026-07-31: the form itself becomes a Modal later; this
// spec asserts the flow, not the form's chrome.
import { expect, test } from '@playwright/test';
import { apiAs } from '../../fixtures/api.js';
import { personas } from '../../fixtures/personas.js';

const stamp = `e2e-${Date.now().toString(36)}`;

test.describe('with can_manage_jobs', () => {
  test.use({ storageState: personas.finjobs.storageState });

  let contact;

  test.beforeAll(async () => {
    const api = await apiAs(personas.finjobs);
    contact = (await api.get('/api/contacts/?page_size=1')).results[0];
    await api.dispose();
  });

  test('board → New Job → create lands on the new job', async ({ page }) => {
    await page.goto('/#/jobs/board');
    await page.getByRole('link', { name: 'New Job' }).click();
    await expect(page.getByRole('heading', { name: 'New Job' })).toBeVisible();

    // Contact is the one required field — pick it through the type-ahead.
    // Scope to the picker's listbox: the project-manager <select>'s native
    // <option>s carry role=option too.
    await page.getByPlaceholder('Search contacts…').fill(contact.last_name);
    await page.getByRole('listbox').getByRole('option').first().click();

    const jobName = `${stamp} board-new-job`;
    await page.getByLabel('Name', { exact: true }).fill(jobName);
    await page.getByRole('button', { name: 'Create' }).click();

    // Lands on the created job's detail page, numbered and named. (The number
    // pattern is a Configuration key, so match the "JOB #" prefix, not a format.)
    await expect(page).toHaveURL(/#\/jobs\/\d+/);
    await expect(
      page.getByRole('heading', { name: new RegExp(`^JOB #\\S+: ${jobName}$`) })
    ).toBeVisible();
  });
});

test.describe('without can_manage_jobs', () => {
  test.use({ storageState: personas.worker.storageState });

  test('board offers no New Job entry point to a worker', async ({ page }) => {
    await page.goto('/#/jobs/board');
    // The board itself renders for everyone; only the create affordance is gated.
    await expect(page.locator('.board')).toBeVisible();
    await expect(page.getByRole('link', { name: 'New Job' })).toHaveCount(0);
  });
});

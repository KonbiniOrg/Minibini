// docs/ui-flows/Job-Overview.md §7 — Rail switch keeps the shell (issue #511).
// Every /jobs/:id[/section] route mounts the one JobWorkspace, so switching
// sections via the rail must keep the header/band/rail DOM in place with no
// visible reload (the job is revalidated in the background; that request is
// allowed, a placeholder or remount is not). Read-only — no job is mutated.
import { expect, test } from '@playwright/test';
import { findJob, loadBackdrop } from '../../fixtures/lookups.js';
import { personas } from '../../fixtures/personas.js';

test.use({ storageState: personas.finjobs.storageState });

let jobs;

test.beforeAll(async () => {
  jobs = await loadBackdrop();
});

test('§7 Rail switch keeps the shell mounted with no visible reload', async ({ page }) => {
  const job = findJob(jobs, { status: 'in_progress' }) ?? findJob(jobs, {});
  test.skip(!job, 'seed gap: no job to open');
  const jobId = job.job_id;

  await page.goto(`/#/jobs/${jobId}`);
  const rail = page.locator('.job-nav-rail');
  await expect(rail).toBeVisible();
  await expect(page.locator('.summary-block-title', { hasText: /^Scope$/ })).toBeVisible();

  // Pin the live DOM node; a remount would replace it with a new element.
  const railHandle = await rail.elementHandle();

  // The contact line arrives one fetch after the job; settle before pinning
  // the header text so the comparison below is against the finished header.
  await page.waitForLoadState('networkidle');
  const headerText = await page.locator('.job-header').innerText();
  // A placeholder below the shell would mean the workspace remounted.
  const placeholder = page.locator('.load-state.loading');

  const activeSection = page.locator('.rail-link.active');

  await test.step('overview → tasks', async () => {
    await rail.locator('.rail-link[data-section="tasks"]').click();
    await expect(page).toHaveURL(new RegExp(`#/jobs/${jobId}/tasks$`));
    await expect(activeSection).toHaveAttribute('data-section', 'tasks');
  });

  await test.step('tasks → estimates', async () => {
    await rail.locator('.rail-link[data-section="estimate"]').click();
    await expect(page).toHaveURL(new RegExp(`#/jobs/${jobId}/estimate`));
    await expect(activeSection).toHaveAttribute('data-section', 'estimate');
  });

  await test.step('estimates → history', async () => {
    await rail.locator('.rail-link[data-section="history"]').click();
    await expect(page).toHaveURL(new RegExp(`#/jobs/${jobId}/history$`));
    await expect(activeSection).toHaveAttribute('data-section', 'history');
    await expect(page.locator('.page-tabs button', { hasText: 'Summary' })).toBeVisible();
  });

  await test.step('history → overview', async () => {
    await rail.locator('.rail-link[data-section="overview"]').click();
    await expect(page).toHaveURL(new RegExp(`#/jobs/${jobId}$`));
    await expect(page.locator('.summary-block-title', { hasText: /^Scope$/ })).toBeVisible();
  });

  await test.step('the shell never remounted and the header never changed', async () => {
    expect(await railHandle.evaluate((el) => el.isConnected)).toBe(true);
    expect(await page.locator('.job-header').innerText()).toBe(headerText);
    await expect(placeholder).toHaveCount(0);
  });
});

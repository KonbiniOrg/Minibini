// Archived (imported historical) jobs, against the seeded OLD-1042 on
// contact 82 (fixtures/playwright/seed.json, appended 2026-10-20): customer
// page window labels + caveat, the read-only job page, search's Archived
// status filter, linking an email, Duplicate…, the PM-only view (no
// Delete…), and the atom-gated two-phase Delete… — last, because it removes
// the job (the DB is rebuilt every run).
import { expect, test } from '@playwright/test';
import { personas } from '../../fixtures/personas.js';
import { apiAs } from '../../fixtures/api.js';
import { loadBackdrop } from '../../fixtures/lookups.js';

const JOB_NUMBER = 'OLD-1042';
const BANNER = 'this job was imported as a historical record and cannot be changed.';

test.describe.configure({ mode: 'serial' });

test.describe('archived job', () => {
  test.use({ storageState: personas.finjobs.storageState });

  let job;
  test.beforeAll(async () => {
    job = (await loadBackdrop()).find((j) => j.job_number === JOB_NUMBER);
  });

  const summary = (page, title) =>
    page.locator('.summary-block').filter({
      has: page.locator('.summary-block-title', { hasText: new RegExp(`^${title}$`) }),
    });

  test('customer page shows the 12-month window and the archive caveat; closed list holds the archived job', async ({ page }) => {
    test.skip(!job, `seed gap: no ${JOB_NUMBER} archived job`);
    await page.goto(`/#/contacts/${job.contact}`);
    await expect(page.getByText('Invoiced (12 mo)', { exact: true })).toBeVisible();
    await expect(page.getByText('Profit (12 mo)', { exact: true })).toBeVisible();
    await expect(page.getByText('Includes archived jobs — imported labor may be incomplete.')).toBeVisible();

    const jobs = page.locator('[data-section="jobs"]');
    // Archived sorts with the closed jobs, behind "show N completed".
    await expect(jobs.getByRole('link', { name: JOB_NUMBER, exact: true })).toHaveCount(0);
    await jobs.getByRole('button', { name: /^show \d+ completed$/ }).click();
    const row = jobs.getByRole('row', { name: new RegExp(JOB_NUMBER) });
    await expect(row).toBeVisible();
    await expect(row.locator('.status-badge')).toHaveText('Archived');
    await row.getByRole('link', { name: JOB_NUMBER, exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`#/jobs/${job.job_id}$`));
    await expect(page.getByText(BANNER)).toBeVisible();
  });

  test('job page is read-only: banner, Archived pill, no edit/status/hold; Duplicate… and Delete… offered', async ({ page }) => {
    test.skip(!job, `seed gap: no ${JOB_NUMBER} archived job`);
    await page.goto(`/#/jobs/${job.job_id}`);
    const header = page.locator('.job-header');
    await test.step('banner and pill', async () => {
      await expect(header.getByRole('status')).toContainText('Archived:');
      await expect(header.getByText(BANNER)).toBeVisible();
      await expect(header.locator('.status-row .status-badge')).toHaveText('Archived');
    });
    await test.step('no Edit, no status select, no hold', async () => {
      await expect(header.getByRole('button', { name: 'Edit', exact: true })).toHaveCount(0);
      await expect(header.locator('select')).toHaveCount(0);
      await expect(page.getByRole('button', { name: /hold/i })).toHaveCount(0);
      await expect(page.getByRole('option', { name: /Hold/ })).toHaveCount(0);
    });
    await test.step('Duplicate… and Delete… are offered', async () => {
      await expect(header.getByRole('button', { name: 'Duplicate…' })).toBeVisible();
      await expect(header.getByRole('button', { name: 'Delete…' })).toBeVisible();
    });
    await test.step('Spend block says the 12.5 labor hours were imported', async () => {
      const spend = summary(page, 'Spend');
      await expect(spend).toBeVisible();
      await expect(spend).toContainText('12.5 hours imported');
    });
    await test.step('tasks page offers no add-work control', async () => {
      await page.goto(`/#/jobs/${job.job_id}/tasks`);
      await expect(page.getByText('Fabrication', { exact: true }).first()).toBeVisible();
      await expect(page.getByRole('button', { name: 'Add Work' })).toHaveCount(0);
      await expect(page.getByRole('button', { name: 'Add Expense' })).toHaveCount(0);
    });
    await test.step('history page offers no Add Note form', async () => {
      await page.goto(`/#/jobs/${job.job_id}/history`);
      await expect(page.getByRole('heading', { name: 'History' })).toBeVisible();
      await expect(page.getByRole('button', { name: 'Add Note' })).toHaveCount(0);
    });
  });

  test('search lists it under the Archived job-status filter', async ({ page }) => {
    test.skip(!job, `seed gap: no ${JOB_NUMBER} archived job`);
    // The Jobs-table row (its invoice's row also mentions the job number).
    const jobRow = page.getByRole('row', { name: new RegExp(`^${JOB_NUMBER} Reception desk`) });
    await page.goto(`/#/search?q=${JOB_NUMBER}`);
    await page.getByRole('button', { name: /Job status/ }).click();
    await page.getByRole('checkbox', { name: 'Completed' }).check();
    // Completed alone excludes it…
    await expect(page.getByText(/result/).first()).toBeVisible();
    await expect(jobRow).toHaveCount(0);
    // …Archived brings it back.
    await page.getByRole('checkbox', { name: 'Completed' }).uncheck();
    await page.getByRole('checkbox', { name: 'Archived' }).check();
    await expect(jobRow).toBeVisible();
    await expect(jobRow).toContainText('archived');
  });

  test('an email links to the archived job and shows on its email list', async ({ page }) => {
    test.skip(!job, `seed gap: no ${JOB_NUMBER} archived job`);
    // Seed email 8 is on contact 82's completed job; remember it to restore.
    const api = await apiAs(personas.finjobs);
    let originalJob;
    try { originalJob = (await api.get('/api/emails/8/')).job; } finally { await api.dispose(); }
    try {
      await page.goto('/#/email/8');
      const panel = page.getByRole('complementary');
      const jobSection = panel.locator('section', { has: page.getByRole('heading', { name: 'Job' }) });
      if (originalJob) await jobSection.getByRole('button', { name: 'Disassociate' }).click();
      await jobSection.getByRole('button', { name: 'Link existing' }).click();
      const dialog = page.getByRole('dialog', { name: 'Link to job' });
      await dialog.getByPlaceholder('Search jobs…').fill(JOB_NUMBER);
      await dialog.getByText(new RegExp(`${JOB_NUMBER} — `)).click();
      await dialog.getByRole('button', { name: 'Link to job' }).click();
      await expect(page.getByRole('dialog')).toHaveCount(0);
      await expect(jobSection.getByRole('link', { name: JOB_NUMBER })).toBeVisible();

      await page.goto(`/#/jobs/${job.job_id}/emails`);
      await expect(page.getByText(/Invoice 10289 for 07935/).first()).toBeVisible();
    } finally {
      // Restore the seed shape for other specs: back onto its original job.
      const api2 = await apiAs(personas.finjobs);
      try {
        const now = await api2.get('/api/emails/8/');
        if (now.job && now.job !== originalJob) await api2.post('/api/emails/8/unlink-from-job/', {});
        if (originalJob && now.job !== originalJob) await api2.post('/api/emails/8/link-to-job/', { job_id: originalJob });
      } finally { await api2.dispose(); }
    }
  });

  test('Duplicate… (re-estimate path) copies its tasks onto a new draft job', async ({ page }) => {
    test.skip(!job, `seed gap: no ${JOB_NUMBER} archived job`);
    await page.goto(`/#/jobs/${job.job_id}`);
    await page.getByRole('button', { name: 'Duplicate…' }).click();
    const dialog = page.getByRole('dialog', { name: 'Duplicate job' });
    await expect(dialog).toBeVisible();
    await dialog.getByRole('radio', { name: /Requires a new estimate/ }).check();
    await dialog.getByRole('button', { name: 'Duplicate', exact: true }).click();
    await expect(page).not.toHaveURL(new RegExp(`#/jobs/${job.job_id}$`));
    await expect(page).toHaveURL(/#\/jobs\/\d+$/);
    const newId = Number(page.url().match(/#\/jobs\/(\d+)$/)[1]);
    expect(newId).not.toBe(job.job_id);
    await expect(page.locator('.job-header .status-row')).toContainText('Draft');
    await expect(page.getByText(BANNER)).toHaveCount(0);

    await page.goto(`/#/jobs/${newId}/tasks`);
    await expect(page.getByText('Fabrication', { exact: true }).first()).toBeVisible();
    await expect(page.getByText('Install', { exact: true }).first()).toBeVisible();
  });

  test.describe('as the PM without the jobs atom', () => {
    test.use({ storageState: personas.worker.storageState });

    test('Duplicate… is offered but Delete… is not', async ({ page }) => {
      test.skip(!job, `seed gap: no ${JOB_NUMBER} archived job`);
      await page.goto(`/#/jobs/${job.job_id}`);
      await expect(page.getByText(BANNER)).toBeVisible();
      await expect(page.getByRole('button', { name: 'Duplicate…' })).toBeVisible();
      await expect(page.getByRole('button', { name: 'Delete…' })).toHaveCount(0);
    });
  });

  test('Delete… lists the impact, deletes on confirm, and lands on the customer', async ({ page }) => {
    test.skip(!job, `seed gap: no ${JOB_NUMBER} archived job`);
    await page.goto(`/#/jobs/${job.job_id}`);
    await page.getByRole('button', { name: 'Delete…' }).click();
    const dialog = page.getByRole('dialog', { name: 'Delete job' });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole('heading', { name: `Delete ${JOB_NUMBER}?` })).toBeVisible();
    await expect(dialog.getByText('2 task(s)', { exact: true })).toBeVisible();
    await dialog.getByRole('button', { name: 'Delete job' }).click();
    await expect(page).toHaveURL(new RegExp(`#/contacts/${job.contact}$`));

    const api = await apiAs(personas.finjobs);
    try {
      expect((await api.getRaw(`/api/jobs/${job.job_id}/`)).status()).toBe(404);
    } finally { await api.dispose(); }
  });
});

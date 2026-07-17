// docs/ui-flows/Production-Lifecycle.md §9 (the hold freeze) and §10
// (guards & permissions).
import { expect, test } from '@playwright/test';
import { apiAs, closeOpenSession } from '../../fixtures/api.js';
import { findStartableTask, loadBackdrop, pendingTasks } from '../../fixtures/lookups.js';
import { personas } from '../../fixtures/personas.js';

let jobs;
const used = new Set();

test.beforeAll(async () => {
  jobs = await loadBackdrop();
});

test.afterEach(async () => {
  await closeOpenSession(personas.worker);
});

async function jobDetail(jobId) {
  const api = await apiAs(personas.finjobs);
  const detail = await api.get(`/api/jobs/${jobId}/`);
  await api.dispose();
  return detail;
}

test.describe('manager side', () => {
  test.use({ storageState: personas.finjobs.storageState });

  test('§9 Hold — the pause freeze', async ({ page, browser }) => {
    const hit = findStartableTask(jobs, {
      jobStatus: 'in_progress', materials: 'none', minPendingTasks: 2, used,
    });
    test.skip(!hit, 'seed gap: no in_progress job with two material-less pending tasks');
    const { job, task } = hit;
    const other = pendingTasks(job).find(
      (t) => t.task_id !== task.task_id && !(job.materials || []).some((m) => m.task === t.task_id));
    test.skip(!other, 'seed gap: second material-less pending task on the job');

    // A second browser as the worker, to hold an open session.
    const workerCtx = await browser.newContext({ storageState: personas.worker.storageState });
    const workerPage = await workerCtx.newPage();

    await test.step('Hold is rejected while a timeslip on the job is open', async () => {
      await workerPage.goto(`http://localhost:9100/#/jobs/${job.job_id}/tasks/${task.task_id}`);
      await workerPage.getByRole('button', { name: 'Start Work' }).click();
      await expect(workerPage.getByText('Working on:')).toBeVisible();

      await page.goto(`/#/jobs/${job.job_id}`);
      await page.getByRole('combobox').first().selectOption('__hold');
      await page.getByLabel('Reason for hold').fill('e2e: pausing for hold-guard test');
      await page.getByRole('button', { name: 'Confirm Hold' }).click();
      // Rejected — the modal surfaces the open-timeslip error and the flag stays off.
      await expect.poll(async () => (await jobDetail(job.job_id)).on_hold).toBe(false);
      await expect(page.getByRole('button', { name: 'Confirm Hold' })).toBeVisible();
    });

    await test.step('Stop the session; hold now succeeds and the pill shows HOLD', async () => {
      await workerPage.getByRole('banner')
        .getByRole('button', { name: 'Cancel', exact: true }).click();
      await expect(workerPage.getByText('Working on:')).toHaveCount(0);

      await page.goto(`/#/jobs/${job.job_id}`);
      await page.getByRole('combobox').first().selectOption('__hold');
      await page.getByLabel('Reason for hold').fill('e2e: awaiting deposit');
      await page.getByRole('button', { name: 'Confirm Hold' }).click();
      await expect.poll(async () => (await jobDetail(job.job_id)).on_hold).toBe(true);
      await expect(page.getByText('e2e: awaiting deposit')).toBeVisible();
    });

    await test.step('While held: no new timeslips, work affordances hidden', async () => {
      await workerPage.goto(`http://localhost:9100/#/jobs/${job.job_id}/tasks/${other.task_id}`);
      await expect(workerPage.getByRole('button', { name: 'Start Work' })).toHaveCount(0);
      const api = await apiAs(personas.worker);
      const resp = await api.postRaw(`/api/tasks/${other.task_id}/start-work/`, {});
      const body = await resp.text();
      await api.dispose();
      expect(resp.status()).toBe(400);
      expect(body).toContain('hold');
    });

    await test.step('Release: the job resumes its true status; affordances return', async () => {
      await page.goto(`/#/jobs/${job.job_id}`);
      await page.getByRole('combobox').first().selectOption('__release_hold');
      await expect.poll(async () => (await jobDetail(job.job_id)).on_hold).toBe(false);
      expect((await jobDetail(job.job_id)).status).toBe('in_progress');
      // Same-fragment goto doesn't renavigate a hash router — force a reload
      // so the page re-fetches the released job.
      await workerPage.goto(`http://localhost:9100/#/jobs/${job.job_id}/tasks/${other.task_id}`);
      await workerPage.reload();
      await expect(workerPage.getByRole('button', { name: 'Start Work' })).toBeVisible();
    });

    await workerCtx.close();
  });
});

test.describe('worker guards', () => {
  test.use({ storageState: personas.worker.storageState });

  test('§10 Guards & permissions (most-missed)', async ({ page }) => {
    // Fresh backdrop: earlier tests changed job states this run. Exclude
    // PM-owned jobs — a job's PM legitimately holds manage powers on it.
    const fresh = (await loadBackdrop()).filter((j) => !j.project_manager);
    const hit = findStartableTask(fresh, { jobStatus: 'in_progress', used });
    test.skip(!hit, 'seed gap: no in_progress job with a pending task');
    const { job, task } = hit;

    await test.step('The status pill is not interactive for a worker', async () => {
      await page.goto(`/#/jobs/${job.job_id}`);
      await expect(page.getByText(job.job_number).first()).toBeVisible();
      await expect(page.getByRole('combobox')).toHaveCount(0);
    });

    await test.step('Hold, cancel-task, and work-complete are refused by the API', async () => {
      const api = await apiAs(personas.worker);
      const hold = await api.postRaw(`/api/jobs/${job.job_id}/hold/`, { reason: 'nope' });
      expect(hold.status()).toBe(403);
      const cancel = await api.postRaw(`/api/tasks/${task.task_id}/cancel/`, {});
      expect(cancel.status()).toBe(403);
      const wc = await api.postRaw(`/api/jobs/${job.job_id}/work-complete/`, {});
      expect(wc.status()).toBe(403);
      await api.dispose();
    });

    await test.step('Invalid pill transitions are rejected even for a manager', async () => {
      const api = await apiAs(personas.finjobs);
      const resp = await api.patchRaw(`/api/jobs/${job.job_id}/`, { status: 'approved' });
      expect(resp.status()).toBe(400);
      await api.dispose();
    });
  });
});

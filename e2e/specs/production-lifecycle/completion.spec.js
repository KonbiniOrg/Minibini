// docs/ui-flows/Production-Lifecycle.md §6 (complete + cascade + gate) and
// §7 (terminal freeze, cancel-task, reactivation).
import { expect, test } from '@playwright/test';
import { apiAs, closeOpenSession } from '../../fixtures/api.js';
import {
  findJob, findStartableTask, loadBackdrop, looseMaterials, pendingTasks,
} from '../../fixtures/lookups.js';
import { personas } from '../../fixtures/personas.js';

let jobs;
const used = new Set();

test.beforeAll(async () => {
  jobs = await loadBackdrop();
});

async function jobDetail(jobId) {
  const api = await apiAs(personas.finjobs);
  const detail = await api.get(`/api/jobs/${jobId}/`);
  await api.dispose();
  return detail;
}

const taskUrl = (job, task) => `/#/jobs/${job.job_id}/tasks/${task.task_id}`;

test.describe('worker side', () => {
  test.use({ storageState: personas.worker.storageState });

  test.afterEach(async () => {
    await closeOpenSession(personas.worker);
  });

  test('§6 Complete — open session closes, the cascade advances the job', async ({ page }) => {
    test.setTimeout(240_000); // works the session past the one-minute floor
    let hit = null;
    const scratch = new Set(used);
    for (;;) {
      const candidate = findStartableTask(jobs, {
        jobStatus: 'in_progress', materials: 'none', used: scratch,
      });
      if (!candidate) break;
      const open = (candidate.job.tasks || []).filter(
        (t) => !['complete', 'cancelled'].includes(t.status));
      if (open.length === 1 && open[0].status === 'pending') {
        hit = candidate; used.add(candidate.job.job_id); break;
      }
    }
    test.skip(!hit, 'seed gap: no in_progress job whose single open task is pending and material-less');
    const { job, task } = hit;

    await test.step('Work the task past the minimum so Complete has real time to settle', async () => {
      await page.goto(taskUrl(job, task));
      await page.getByRole('button', { name: 'Start Work' }).click();
      await expect(page.getByText('Working on:')).toBeVisible();
      await expect(page.getByRole('banner').getByRole('button', { name: 'Stop', exact: true }))
        .toBeVisible({ timeout: 130_000 });
    });

    await test.step('Complete: the open timeslip closes with it', async () => {
      await page.locator('.actions').getByRole('button', { name: 'Complete' }).click();
      await expect(page.getByText('Working on:')).toHaveCount(0);
      await expect.poll(async () =>
        (await jobDetail(job.job_id)).tasks.find((t) => t.task_id === task.task_id).status
      ).toBe('complete');
    });

    await test.step('Cascade: last open task terminal → job advances to work_complete', async () => {
      await expect.poll(async () => (await jobDetail(job.job_id)).status).toBe('work_complete');
    });
  });

  test('§6 Completion settle-up: a counted task always prompts before closing', async ({ page }) => {
    // A job whose ONLY pending entered_qty task we can retire without
    // disturbing the two-task job the sessions spec needs later.
    let hit = null;
    const scratch = new Set(used);
    for (;;) {
      const candidate = findStartableTask(jobs, { algorithm: 'entered_qty', used: scratch });
      if (!candidate) break;
      const enteredPending = pendingTasks(candidate.job)
        .filter((t) => t.scheme_algorithm === 'entered_qty');
      if (enteredPending.length === 1) { hit = candidate; used.add(candidate.job.job_id); break; }
    }
    test.skip(!hit, 'seed gap: no job with exactly one pending entered_qty task');
    const { job, task } = hit;

    await page.goto(taskUrl(job, task));
    await page.locator('.actions').getByRole('button', { name: 'Complete' }).click();
    await expect(page.getByRole('heading', { name: 'Settle up quantity' })).toBeVisible();
    await page.getByRole('dialog').getByLabel(/^Quantity/).fill('4');
    await page.getByRole('dialog').getByRole('button', { name: 'Complete task' }).click();
    await expect(page.getByRole('heading', { name: 'Settle up quantity' })).toHaveCount(0);
    // The modal closes optimistically before the POST lands — poll.
    await expect.poll(async () => (await jobDetail(job.job_id))
      .tasks.find((t) => t.task_id === task.task_id).status).toBe('complete');
    const after = (await jobDetail(job.job_id)).tasks.find((t) => t.task_id === task.task_id);
    expect(Number(after.actual_qty)).toBe(4);
  });

  test('§7 Terminal freeze: a complete task rejects edits and offers no actions', async ({ page }) => {
    // Some work_complete jobs finished by cancellation — walk until one has
    // a genuinely complete task.
    let job = null, done = null;
    const scratch = new Set();
    while ((job = findJob(jobs, { status: 'work_complete', used: scratch }))) {
      done = (job.tasks || []).find((t) => t.status === 'complete');
      if (done) break;
    }
    test.skip(!done, 'seed gap: no work_complete job with a complete task');

    await page.goto(taskUrl(job, done));
    await expect(page.getByRole('heading', { name: done.name })).toBeVisible();
    for (const label of ['Start Work', 'Complete', 'Block']) {
      await expect(page.locator('.actions').getByRole('button', { name: label }))
        .toHaveCount(0);
    }
    const api = await apiAs(personas.finjobs);
    // Task edits live on the job-nested route (flat /api/tasks/ is lifecycle-only).
    const resp = await api.patchRaw(
      `/api/jobs/${job.job_id}/tasks/${done.task_id}/`, { name: 'renamed' });
    const body = await resp.text();
    await api.dispose();
    expect(resp.status()).toBe(400);
    expect(body).toContain('settled');
  });
});

test.describe('manager side', () => {
  test.use({ storageState: personas.finjobs.storageState });

  test('§7 Cancel task — pending materials detach to the job as loose rows', async ({ page }) => {
    const hit = findStartableTask(jobs, {
      jobStatus: 'in_progress', materials: 'shortfall', used,
    });
    test.skip(!hit, 'seed gap: no in_progress job with a pending task carrying a pending material');
    const { job, task, mats } = hit;

    page.on('dialog', (d) => d.accept());
    await page.goto(taskUrl(job, task));
    await page.locator('.actions').getByRole('button', { name: 'Cancel', exact: true }).click();

    await expect.poll(async () =>
      (await jobDetail(job.job_id)).tasks.find((t) => t.task_id === task.task_id).status
    ).toBe('cancelled');

    const detail = await jobDetail(job.job_id);
    const detached = detail.materials.find((m) => m.material_id === mats[0].material_id);
    expect(detached.task).toBeNull();                       // loose on the job now
    expect(detached.consumption_state).toBe('pending');     // not consumed, not deleted
    expect(Number(detached.quantity)).toBe(Number(mats[0].quantity));
    expect(looseMaterials(detail).map((m) => m.material_id)).toContain(mats[0].material_id);
  });

  test('§7 Reactivation: work_complete → in_progress via the status pill', async ({ page }) => {
    const job = findJob(jobs, { status: 'work_complete', used });
    test.skip(!job, 'seed gap: no work_complete job');

    page.on('dialog', (d) => d.accept());
    await page.goto(`/#/jobs/${job.job_id}`);
    await page.getByRole('combobox').first().selectOption('in_progress');
    await expect.poll(async () => (await jobDetail(job.job_id)).status).toBe('in_progress');
  });

  test('§7 Auto-reopen: a new open task on a work_complete job pulls it back', async () => {
    const job = findJob(jobs, { status: 'work_complete', used });
    test.skip(!job, 'seed gap: a second work_complete job');
    const api = await apiAs(personas.finjobs);
    const schemes = await api.get('/api/rate-schemes/?page_size=1');
    const scheme = (schemes.results || schemes)[0];
    await api.post(`/api/jobs/${job.job_id}/tasks/`, {
      name: 'e2e reopen probe', rate_scheme: scheme.rate_scheme_id ?? scheme.id,
    });
    const after = await api.get(`/api/jobs/${job.job_id}/`);
    await api.dispose();
    expect(after.status).toBe('in_progress');
  });
});

// SEED GAP (§6): the work-complete gate needs an in_progress (or approved)
// job with a LOOSE pending material and otherwise-completable tasks; the
// current seed's loose materials sit on submitted/draft/rejected jobs only.
test('§6 The gate: a loose pending material blocks work_complete (Check Complete lists it)', async () => {
  const gateJob = findJob(loadedJobsForGate(), {});
  function loadedJobsForGate() {
    return (jobs || []).filter((j) =>
      ['in_progress', 'approved'].includes(j.status) && looseMaterials(j).length > 0);
  }
  test.skip(!gateJob, 'seed gap: no in_progress/approved job with a loose pending material');
  // Written when the seed has the shape: complete the last task → job stays
  // put; Tasks page button reads "Check Complete" and lists the material;
  // resolve via Consume/Restock → "Mark Work Complete" → work_complete;
  // /api/earmarks/ rows for the job are swept.
  test.fixme(true, 'unwritten until the seed shape exists');
});

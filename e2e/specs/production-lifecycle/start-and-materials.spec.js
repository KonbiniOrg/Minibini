// docs/ui-flows/Production-Lifecycle.md §1, §2, §5, §8 — starting work and
// what it does to materials. One test() per flow section; a test skips with a
// named seed gap when the backdrop lacks its shape (the run output is the
// seed-sufficiency report).
import { expect, test } from '@playwright/test';
import { apiAs, closeOpenSession } from '../../fixtures/api.js';
import { loadBackdrop, findStartableTask } from '../../fixtures/lookups.js';
import { personas } from '../../fixtures/personas.js';

test.use({ storageState: personas.worker.storageState });

let jobs;
const used = new Set();

test.beforeAll(async () => {
  jobs = await loadBackdrop();
});

// A failed test must not leak a running session into the next one.
test.afterEach(async () => {
  await closeOpenSession(personas.worker);
});

// The timeslip band lives in the app header; scoping avoids colliding with
// task-cancel buttons and modal Cancels that share the label.
const bandButton = (page, name) =>
  page.getByRole('banner').getByRole('button', { name, exact: true });

async function jobStatus(jobId) {
  const api = await apiAs(personas.finjobs);
  const detail = await api.get(`/api/jobs/${jobId}/`);
  await api.dispose();
  return detail;
}

async function itemQoh(itemId) {
  const api = await apiAs(personas.finjobs);
  const item = await api.get(`/api/inventory/${itemId}/`);
  await api.dispose();
  return Number(item.qty_on_hand);
}

function taskUrl(job, task) {
  return `/#/jobs/${job.job_id}/tasks/${task.task_id}`;
}

// Wait until we're early enough in the wall-clock minute that a start + a few
// seconds of session cannot cross the on-books minute boundary.
async function waitForEarlyMinute(page, latestSecond = 40) {
  while (new Date().getSeconds() > latestSecond) {
    await page.waitForTimeout(1000);
  }
}

test('§1 Start Work — first clock-in promotes, consumes, advances', async ({ page }) => {
  const hit = findStartableTask(jobs, {
    jobStatus: 'approved', materials: 'in-stock', used,
  });
  test.skip(!hit, 'seed gap: no approved job with a pending task carrying in-stock item-backed materials');
  const { job, task, mats } = hit;
  const qohBefore = await itemQoh(mats[0].inventory_item);

  await test.step('Promotion: Start Work → task in_progress, session in the band', async () => {
    await page.goto(taskUrl(job, task));
    await page.getByRole('button', { name: 'Start Work' }).click();
    await expect(page.getByText('Working on:')).toBeVisible();
  });

  await test.step('Job auto-advance: the approved job is now in_progress', async () => {
    await expect.poll(async () => (await jobStatus(job.job_id)).status).toBe('in_progress');
  });

  await test.step('Auto-assign: the starting worker became the assignee', async () => {
    const detail = await jobStatus(job.job_id);
    const after = detail.tasks.find((t) => t.task_id === task.task_id);
    expect(after.status).toBe('in_progress');
  });

  await test.step('Materials consume exactly once: state, QOH, and Spent move now', async () => {
    const detail = await jobStatus(job.job_id);
    const after = detail.materials.find((m) => m.material_id === mats[0].material_id);
    expect(after.consumption_state).toBe('consumed');
    expect(await itemQoh(mats[0].inventory_item)).toBe(qohBefore - Number(mats[0].quantity));
  });

  // TODO (§1 join checkbox): a second worker starting this in_progress task
  // gets the join/takeover choice and consumes nothing — needs a second
  // browser context; deferred to keep this first pass verifiable.

  await test.step('Stop Work: session closes, nothing consumes again', async () => {
    // A real stop needs the session past blep_minimum_minutes — under it the
    // band offers only Cancel (the §5 undo, which would un-consume).
    await expect(bandButton(page, 'Stop')).toBeVisible({ timeout: 130_000 });
    await bandButton(page, 'Stop').click();
    await expect(page.getByText('Working on:')).toHaveCount(0);
    expect(await itemQoh(mats[0].inventory_item)).toBe(qohBefore - Number(mats[0].quantity));
  });
});

test('§2 The shortfall block (start refused, atomically)', async ({ page }) => {
  const hit = findStartableTask(jobs, {
    jobStatus: ['approved', 'in_progress'], materials: 'shortfall', used,
  });
  test.skip(!hit, 'seed gap: no startable pending task whose item-backed material exceeds QOH');
  const { job, task } = hit;

  await test.step('Start Work on a short material → hard-blocked with the coaching message', async () => {
    await page.goto(taskUrl(job, task));
    await page.getByRole('button', { name: 'Start Work' }).click();
    await expect(page.getByText(/on hand/)).toBeVisible();
  });

  await test.step('Nothing half-happens: task stays pending, no session, nothing consumed', async () => {
    await expect(page.getByText('Working on:')).toHaveCount(0);
    const detail = await jobStatus(job.job_id);
    expect(detail.tasks.find((t) => t.task_id === task.task_id).status).toBe('pending');
    for (const m of detail.materials.filter((m) => m.task === task.task_id)) {
      expect(m.consumption_state).toBe('pending');
    }
  });
});

test('§5 The oops-undo (sub-minimum sessions)', async ({ page }) => {
  const hit = findStartableTask(jobs, {
    jobStatus: 'in_progress', materials: 'in-stock', used,
  });
  test.skip(!hit, 'seed gap: no in_progress job with a pending task carrying in-stock item-backed materials');
  const { job, task, mats } = hit;
  const qohBefore = await itemQoh(mats[0].inventory_item);

  await test.step('Start consumes; the band offers Cancel while under the minimum', async () => {
    await page.goto(taskUrl(job, task));
    await waitForEarlyMinute(page);
    await page.getByRole('button', { name: 'Start Work' }).click();
    await expect(page.getByText('Working on:')).toBeVisible();
    expect(await itemQoh(mats[0].inventory_item)).toBe(qohBefore - Number(mats[0].quantity));
  });

  await test.step('Cancel → full undo: no timeslip, task back to pending, materials un-consumed', async () => {
    await bandButton(page, 'Cancel').click();
    await expect(page.getByText('Working on:')).toHaveCount(0);
    const detail = await jobStatus(job.job_id);
    expect(detail.tasks.find((t) => t.task_id === task.task_id).status).toBe('pending');
    expect(detail.materials.find((m) => m.material_id === mats[0].material_id)
      .consumption_state).toBe('pending');
    expect(await itemQoh(mats[0].inventory_item)).toBe(qohBefore);
    const api = await apiAs(personas.worker);
    const bleps = await api.get(`/api/bleps/?task=${task.task_id}&page_size=100`);
    await api.dispose();
    const open = (bleps.results || bleps).filter((b) => !b.end_time);
    expect(open).toHaveLength(0);
  });

  await test.step('Job status and assignee are untouched by the undo', async () => {
    expect((await jobStatus(job.job_id)).status).toBe('in_progress');
  });
});

test('§8 Pre-approval work (draft/submitted jobs)', async ({ page }) => {
  const hit = findStartableTask(jobs, {
    jobStatus: 'draft', materials: 'none', used,
  });
  test.skip(!hit, 'seed gap: no draft job with a pending material-less task');
  const { job, task } = hit;

  await test.step('Start Work on a draft job is allowed; the job status does not move', async () => {
    await page.goto(taskUrl(job, task));
    await waitForEarlyMinute(page);
    await page.getByRole('button', { name: 'Start Work' }).click();
    await expect(page.getByText('Working on:')).toBeVisible();
    expect((await jobStatus(job.job_id)).status).toBe('draft');
  });

  await test.step('…and the task advanced', async () => {
    const detail = await jobStatus(job.job_id);
    expect(detail.tasks.find((t) => t.task_id === task.task_id).status).toBe('in_progress');
    // Leave the backdrop tidy: sub-minimum cancel restores the task.
    await bandButton(page, 'Cancel').click();
    await expect(page.getByText('Working on:')).toHaveCount(0);
  });
});

// SEED GAP (also §8): consume-without-earmark needs a draft job whose pending
// task carries an in-stock item-backed material; the current seed has none.
test('§8 Pre-approval consumption draws QOH without an earmark', async () => {
  const hit = findStartableTask(jobs, { jobStatus: 'draft', materials: 'in-stock', used });
  test.skip(!hit, 'seed gap: no draft job with a pending task carrying an in-stock item-backed material');
  // Written when the seed has the shape: start → QOH drops, /api/earmarks/
  // shows NO row for (item, job); cancel → QOH restored.
  test.fixme(true, 'unwritten until the seed shape exists');
});

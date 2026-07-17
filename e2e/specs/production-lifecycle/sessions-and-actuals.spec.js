// docs/ui-flows/Production-Lifecycle.md §3, §4, and the §5 boundary case —
// stopping counted work settles first; where actuals come from.
import { expect, test } from '@playwright/test';
import { apiAs, closeOpenSession } from '../../fixtures/api.js';
import { findStartableTask, loadBackdrop } from '../../fixtures/lookups.js';
import { personas } from '../../fixtures/personas.js';

test.use({ storageState: personas.worker.storageState });

let jobs;
const used = new Set();

test.beforeAll(async () => {
  jobs = await loadBackdrop();
});

test.afterEach(async () => {
  await closeOpenSession(personas.worker);
});

const bandButton = (page, name) =>
  page.getByRole('banner').getByRole('button', { name, exact: true });
const dialog = (page) => page.getByRole('dialog');

async function taskDetail(taskId) {
  const api = await apiAs(personas.finjobs);
  const t = await api.get(`/api/tasks/${taskId}/`);
  await api.dispose();
  return t;
}

const taskUrl = (job, task) => `/#/jobs/${job.job_id}/tasks/${task.task_id}`;

// Under blep_minimum_minutes the band offers only Cancel (the oops-undo);
// a real Stop needs the session past the on-books minute. Slow by nature —
// the config floor is one minute.
async function waitPastMinimum(page) {
  await expect(bandButton(page, 'Stop')).toBeVisible({ timeout: 130_000 });
}

test('§3 Stop Work — settle-first for counted work', async ({ page }) => {
  test.setTimeout(420_000); // two real stops, each past the one-minute floor
  // Two entered_qty pending tasks on one job: settle-on-stop + settle-on-switch.
  const hit = findStartableTask(jobs, {
    jobStatus: ['submitted', 'draft', 'in_progress', 'approved'],
    algorithm: 'entered_qty', minPendingTasks: 2, used,
  });
  test.skip(!hit, 'seed gap: no startable job with two pending entered_qty tasks');
  const { job, task } = hit;
  const second = (job.tasks || []).find(
    (t) => t.status === 'pending' && t.task_id !== task.task_id
      && t.scheme_algorithm === 'entered_qty');
  test.skip(!second, 'seed gap: second pending entered_qty task on the same job');

  await test.step('Start a counted task', async () => {
    await page.goto(taskUrl(job, task));
    await page.getByRole('button', { name: 'Start Work' }).click();
    await expect(page.getByText('Working on:')).toBeVisible();
  });

  await test.step('Settle-first on switch: starting another task prompts; cancelling aborts the switch', async () => {
    await page.goto(taskUrl(job, second));
    await page.getByRole('button', { name: 'Start Work' }).click();
    await expect(page.getByRole('heading', { name: 'Quantity this session' })).toBeVisible();
    await dialog(page).getByRole('button', { name: 'Cancel' }).click();
    // Nothing mutated: still working the first task, second still pending.
    await expect(page.getByText('Working on:')).toBeVisible();
    expect((await taskDetail(second.task_id)).status).toBe('pending');
  });

  await test.step('Settle-first on stop: the count is recorded and the session closes in one step', async () => {
    await page.goto(taskUrl(job, task));
    await waitPastMinimum(page);
    await bandButton(page, 'Stop').click();
    await expect(page.getByRole('heading', { name: 'Quantity this session' })).toBeVisible();
    await dialog(page).getByLabel(/^Quantity/).fill('3');
    await dialog(page).getByRole('button', { name: 'Add', exact: true }).click();
    await expect(page.getByText('Working on:')).toHaveCount(0);
    expect(Number((await taskDetail(task.task_id)).actual_qty)).toBe(3);
  });

  await test.step('§4 A negative increment at completion settle-up corrects the total', async () => {
    // Session prompts only take positive counts (or empty = skip); the
    // last-moment negative correction belongs to the settle-up at Complete.
    await page.locator('.actions').getByRole('button', { name: 'Complete' }).click();
    await expect(page.getByRole('heading', { name: 'Settle up quantity' })).toBeVisible();
    await dialog(page).getByLabel(/^Quantity/).fill('-1');
    await dialog(page).getByRole('button', { name: 'Complete task' }).click();
    await expect(page.getByRole('heading', { name: 'Settle up quantity' })).toHaveCount(0);
    // The modal closes optimistically before the POST lands — poll.
    await expect.poll(async () => (await taskDetail(task.task_id)).status).toBe('complete');
    expect(Number((await taskDetail(task.task_id)).actual_qty)).toBe(2);
  });
});

test('§4 Actuals — elapsed_time has no quantity entry; stop needs no prompt', async ({ page }) => {
  const hit = findStartableTask(jobs, {
    jobStatus: ['in_progress', 'submitted'], algorithm: 'elapsed_time',
    materials: 'none', used,
  });
  test.skip(!hit, 'seed gap: no startable pending elapsed_time task');
  const { job, task } = hit;

  await test.step('An elapsed task exposes no quantity input', async () => {
    await page.goto(taskUrl(job, task));
    await expect(page.getByRole('button', { name: 'Start Work' })).toBeVisible();
    // Entered-qty task pages carry an add-quantity chip; elapsed must not.
    await expect(page.getByRole('spinbutton', { name: /^Add/ })).toHaveCount(0);
  });

  await test.step('Stop closes immediately — no settle prompt (derived from timeslips)', async () => {
    await page.getByRole('button', { name: 'Start Work' }).click();
    await expect(page.getByText('Working on:')).toBeVisible();
    // Sub-minimum: the band offers Cancel; use it so the backdrop stays tidy.
    await bandButton(page, 'Cancel').click();
    await expect(page.getByRole('heading', { name: 'Quantity this session' })).toHaveCount(0);
    await expect(page.getByText('Working on:')).toHaveCount(0);
  });
});

// The LATER item (docs/designs/LATER.md "Blep cancel window measured from the
// floored minute"): the cancel window a user EXPERIENCES should be the full
// configured minute from their click. Blep.save() floors start_time to the
// minute, and both the guard and the band's Cancel/Stop flip measure from
// that floor — so a session started late in a wall-clock minute loses its
// cancel affordance early. This test states the contract, not the mechanism,
// and is EXPECTED TO FAIL until the LATER item is fixed.
test('§5 boundary: a session started just before a minute boundary can still be cancelled 50s later', async ({ page }) => {
  test.fail(true, 'known drift: cancel window measured from the floored minute (LATER.md)');
  test.setTimeout(240_000);
  const hit = findStartableTask(jobs, {
    jobStatus: ['in_progress', 'submitted'], algorithm: 'elapsed_time',
    materials: 'none', used,
  });
  test.skip(!hit, 'seed gap: no startable pending elapsed_time task');
  const { job, task } = hit;

  await page.goto(`/#/jobs/${job.job_id}/tasks/${task.task_id}`);
  // Click Start ~2s before the boundary: the floored start is ~58s "ago"
  // the moment the session begins.
  while (new Date().getSeconds() < 57) await page.waitForTimeout(500);
  await page.getByRole('button', { name: 'Start Work' }).click();
  await expect(page.getByText('Working on:')).toBeVisible();
  await page.waitForTimeout(50_000);
  // 50s of experienced session, blep_minimum_minutes=1 → Cancel must still
  // be offered (and succeed as a full undo).
  let cancelOffered = true;
  try {
    await bandButton(page, 'Cancel').click({ timeout: 3000 });
  } catch {
    cancelOffered = false; // session cleanup happens in afterEach, API-side
  }
  expect(cancelOffered,
    'the band must still offer Cancel 50s into the experienced session').toBe(true);
  await expect(page.getByText('Working on:')).toHaveCount(0);
});

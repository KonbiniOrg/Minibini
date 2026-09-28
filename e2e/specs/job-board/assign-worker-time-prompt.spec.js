// Board drag-to-worker gatekeeper: a task with no estimated worker time
// can't be scheduled, so dropping it on a worker column interrupts with a
// duration prompt (WorkerTimePromptModal). The prompt shows the task's name
// and estimated quantity for reference so the user can size the duration
// against the work (RM, feature/est-fixes 2026-09-28).
import { expect, test } from '@playwright/test';
import { apiAs } from '../../fixtures/api.js';
import { personas } from '../../fixtures/personas.js';

const stamp = `e2e-${Date.now().toString(36)}`;

test.describe('with can_manage_jobs', () => {
  test.use({ storageState: personas.finjobs.storageState });

  let job;
  let task;

  test.beforeAll(async () => {
    const api = await apiAs(personas.finjobs);
    // Layering rule: the seed has no unassigned task without a worker-time
    // estimate, so mint one on a job the board's In Progress area already
    // shows. Rate scheme 1 ("CNC routing") is minute-denominated, so est_qty
    // does NOT pair-fill est_worker_time the way an hour-unit scheme would.
    job = (await api.get('/api/jobs/board/approved/')).jobs[0];
    task = await api.post(`/api/jobs/${job.job_id}/tasks/`, {
      name: `${stamp} prompt task`, rate_scheme: 1, est_qty: '90',
    });
    await api.dispose();
  });

  test.afterAll(async () => {
    if (!task) return;
    const api = await apiAs(personas.finjobs);
    await api.del(`/api/jobs/${job.job_id}/tasks/${task.task_id}/`);
    await api.dispose();
  });

  test('dropping an unestimated task on a worker shows the task and its qty in the prompt', async ({ page }) => {
    await page.goto('/#/jobs/board');
    const card = page.locator(`[data-task-id="${task.task_id}"]`);
    await expect(card).toBeVisible();

    await test.step('Drag onto a worker column → duration prompt opens instead of assigning', async () => {
      await card.dragTo(page.locator('.worker-tasks').first());
      await expect(page.getByRole('dialog')).toBeVisible();
      await expect(page.getByRole('dialog').getByRole('button', { name: 'Assign' })).toBeVisible();
    });

    await test.step('Prompt shows the task name and estimated qty + units for reference', async () => {
      const dialog = page.getByRole('dialog');
      await expect(dialog.getByText(`${stamp} prompt task`)).toBeVisible();
      await expect(dialog.getByText(/^90(\.00)? min$/)).toBeVisible();
    });

    await test.step('Cancel → nothing assigned', async () => {
      await page.getByRole('dialog').getByRole('button', { name: 'Cancel' }).click();
      await expect(page.getByRole('dialog')).toHaveCount(0);
      const api = await apiAs(personas.finjobs);
      const fresh = await api.get(`/api/tasks/${task.task_id}/`);
      await api.dispose();
      expect(fresh.assignee).toBeNull();
    });
  });
});

// Task Description in WorkItemForm is a textarea, not a single-line input
// (2026-07-30), matching Job Description in JobEditModal. A task description
// carries the per-job work specifics, so it has to hold line breaks — and
// TaskDetailPage must render them back with the breaks intact.
import { expect, test } from '@playwright/test';
import { findJob, loadBackdrop } from '../../fixtures/lookups.js';
import { personas } from '../../fixtures/personas.js';

test.use({ storageState: personas.finjobs.storageState });

const stamp = `e2e-td-${Date.now().toString(36)}`;
const TWO_LINES = 'First pass: rough cut\nSecond pass: finish to 0.5mm';

test('a multi-line task description survives the round trip', async ({ page }) => {
  const jobs = await loadBackdrop();
  const job = findJob(jobs, { status: 'in_progress' });
  test.skip(!job, 'seed gap: no in_progress job for the tasks view');

  await page.goto(`/#/jobs/${job.job_id}/tasks`);
  await page.getByRole('button', { name: 'Add Work' }).click();
  // The picker's freeform lane: "Add Task" opens WorkItemForm in manual mode.
  await page.getByLabel('Add line').getByRole('button', { name: 'Add Task' }).click();

  const nameField = page.getByLabel('Name *');
  await expect(nameField).toBeVisible();
  // Manual mode needs a rate scheme before it will save.
  await page.getByLabel('Rate Scheme *').selectOption({ index: 1 });
  await nameField.fill(`${stamp} task`);

  // The field is a textarea, so the newline stays a newline rather than
  // being swallowed by a single-line input.
  const description = page.getByLabel('Description');
  await expect(description).toHaveJSProperty('tagName', 'TEXTAREA');
  await description.fill(TWO_LINES);
  await expect(description).toHaveValue(TWO_LINES);

  await page.getByRole('button', { name: 'Save', exact: true }).click();

  // Reopen the saved task: the description comes back with both lines, and
  // the detail page preserves the break rather than collapsing it.
  await page.getByRole('button', { name: `${stamp} task` }).click();
  const shown = page.locator('.description');
  await expect(shown).toContainText('First pass: rough cut');
  await expect(shown).toContainText('Second pass: finish to 0.5mm');
  await expect(shown).toHaveClass(/preserve-breaks/);
});

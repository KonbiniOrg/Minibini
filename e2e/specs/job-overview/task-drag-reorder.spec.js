// Issue #513 — drag-and-drop reorder on the job's Tasks tab, replacing the
// up/down arrows. A task moves several places in one gesture, its material
// rows travel with it, the new order is saved (and survives a reload), and
// the keyboard path works (Space picks up, arrows move, Space drops).
//
// Built fresh via the API (contact + a dedicated rate scheme) so the job's
// task list is exactly the three tasks under test.
import { expect, test } from '@playwright/test';
import { apiAs } from '../../fixtures/api.js';
import { personas } from '../../fixtures/personas.js';

// Tall enough that the three task rows sit mid-page: a drag near the
// viewport edge triggers dnd-kit's auto-scroll and shifts the target.
test.use({ storageState: personas.finjobs.storageState, viewport: { width: 1400, height: 1200 } });

const stamp = `e2e-drag-${Date.now().toString(36)}`;
let scheme;
let category;

test.beforeAll(async () => {
  const configApi = await apiAs(personas.configtime);
  const cats = await configApi.get('/api/accounting-categories/');
  category = (cats.results || cats)
    .find((c) => c.is_active !== false && !c.is_deposit && !c.is_fallback);
  const units = await configApi.get('/api/settings/units/');
  const unit = units.find((u) => u !== 'none' && u !== 'hour') || units[0];
  scheme = await configApi.post('/api/rate-schemes/', {
    name: `${stamp}-scheme`, description: '', algorithm: 'entered_qty',
    rate: '10.00', unit_label: unit, accounting_category: category.id, modifiers: [],
  });
  await configApi.dispose();
});

async function jobWithThreeTasks(label) {
  const api = await apiAs(personas.finjobs);
  const contact = (await api.get('/api/contacts/?page_size=1')).results[0];
  const job = await api.post('/api/jobs/', { name: `${stamp} ${label}`, contact: contact.contact_id });
  const names = ['Alpha', 'Bravo', 'Charlie'].map((n) => `${stamp} ${label} ${n}`);
  for (const name of names) {
    await api.post(`/api/jobs/${job.job_id}/tasks/`, {
      name, rate_scheme: scheme.rate_scheme_id, est_qty: '1.00',
    });
  }
  // Alpha carries a material, to prove a task's rows move as one group.
  const alpha = (await api.get(`/api/jobs/${job.job_id}/`)).tasks.find((t) => t.name === names[0]);
  await api.post(`/api/tasks/${alpha.task_id}/materials/`, {
    description: `${stamp} ${label} alpha-material`, quantity: '1.00', units: scheme.unit_label,
    unit_cost: '1.00', sell_price: '1.00', accounting_category: category.id,
  });
  await api.dispose();
  return { job, names };
}

const groups = (page) => page.locator('table.task-tree-table tbody.task-group');
const shownOrder = async (page) =>
  (await groups(page).locator('tr.task-row .link-btn').allTextContents()).map((s) => s.trim());

async function savedOrder(jobId) {
  const api = await apiAs(personas.finjobs);
  const job = await api.get(`/api/jobs/${jobId}/`);
  await api.dispose();
  return [...job.tasks].sort((a, b) => a.sort_order - b.sort_order).map((t) => t.name);
}

test('§513 drag a task from last to first; its order is saved and the arrows are gone', async ({ page }) => {
  const { job, names } = await jobWithThreeTasks('mouse');
  const [alpha, bravo, charlie] = names;

  await page.goto(`/#/jobs/${job.job_id}/tasks`);
  await expect.poll(() => shownOrder(page)).toEqual([alpha, bravo, charlie]);

  await test.step('No up/down arrows remain', async () => {
    await expect(page.getByRole('button', { name: '▲' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: '▼' })).toHaveCount(0);
  });

  await test.step('Drag Charlie by its handle above Alpha', async () => {
    const handle = page.getByRole('button', { name: `Drag to reorder ${charlie}` });
    const target = groups(page).filter({ hasText: alpha });
    // Mouse coordinates only land on what's inside the viewport.
    await handle.scrollIntoViewIfNeeded();
    const from = await handle.boundingBox();
    const to = await target.boundingBox();
    const x = from.x + from.width / 2;
    await page.mouse.move(x, from.y + from.height / 2);
    await page.mouse.down();
    // Glide at hand speed: dnd-kit animates each swap and re-checks for the
    // next one only on a later pointer move, so step in 10px moves 40ms
    // apart until the pointer is over the top of Alpha's task row.
    let y = from.y + from.height / 2;
    while (y > to.y + 12) {
      y -= 10;
      await page.mouse.move(x, y);
      await page.waitForTimeout(40);
    }
    // Pause before letting go, as a hand does: releasing mid-animation
    // drops at the position before the last swap.
    await page.waitForTimeout(300);
    await page.mouse.up();
  });

  await expect.poll(() => shownOrder(page)).toEqual([charlie, alpha, bravo]);
  await expect.poll(() => savedOrder(job.job_id)).toEqual([charlie, alpha, bravo]);

  await test.step('Alpha still owns its material row', async () => {
    await expect(groups(page).filter({ hasText: alpha })).toContainText(`${stamp} mouse alpha-material`);
  });

  await test.step('The order survives a reload', async () => {
    await page.reload();
    await expect.poll(() => shownOrder(page)).toEqual([charlie, alpha, bravo]);
  });
});

test('§513 keyboard: Space picks a task up, arrows move it, Space drops it', async ({ page }) => {
  const { job, names } = await jobWithThreeTasks('keys');
  const [alpha, bravo, charlie] = names;

  await page.goto(`/#/jobs/${job.job_id}/tasks`);
  await expect.poll(() => shownOrder(page)).toEqual([alpha, bravo, charlie]);

  await page.getByRole('button', { name: `Drag to reorder ${alpha}` }).focus();
  await page.keyboard.press('Space');
  await page.keyboard.press('ArrowDown');
  await page.keyboard.press('ArrowDown');
  await page.keyboard.press('Space');

  await expect.poll(() => shownOrder(page)).toEqual([bravo, charlie, alpha]);
  await expect.poll(() => savedOrder(job.job_id)).toEqual([bravo, charlie, alpha]);
});

test('§513 a worker without manage rights sees no drag handles', async ({ browser }) => {
  const { job, names } = await jobWithThreeTasks('worker');
  const context = await browser.newContext({ storageState: personas.worker.storageState });
  const page = await context.newPage();
  await page.goto(`/#/jobs/${job.job_id}/tasks`);
  await expect(page.getByRole('button', { name: names[0], exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: /Drag to reorder/ })).toHaveCount(0);
  await context.close();
});

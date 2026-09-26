// task-owned-money Phase 1: RateSchemes are freely editable presets now —
// supersession ("Create new version") is gone, replaced by an is_active
// retirement flag that only gates NEW task stampings (SchemeInactiveError).
// A Task stamps a permanent copy of a preset's money fields at creation
// time, so editing (or retiring) a preset never reprices or orphans a task
// that already stamped from it. Companion to specs/settings/rate-scheme-modal.spec.js
// (the modal shell mechanics) — this covers the preset-lifecycle behavior.
import { expect, test } from '@playwright/test';
import { apiAs } from '../../fixtures/api.js';
import { personas } from '../../fixtures/personas.js';

test.use({ storageState: personas.configtime.storageState });

const stamp = `e2e-rsp-${Date.now().toString(36)}`;

async function openPricingTab(page) {
  await page.goto('/#/settings');
  await page.getByRole('button', { name: 'Pricing' }).click();
  await expect(page.getByRole('heading', { name: 'Rate Schemes' })).toBeVisible();
}

async function anEnteredQtyUnit(api) {
  const units = await api.get('/api/settings/units/');
  return units.find((u) => u !== 'none' && u !== 'hour') || units[0];
}

async function makeJob() {
  const api = await apiAs(personas.finjobs);
  const contact = (await api.get('/api/contacts/?page_size=1')).results[0];
  const job = await api.post('/api/jobs/', {
    name: `${stamp} job`, contact: contact.contact_id,
  });
  await api.dispose();
  return job;
}

async function openAddTaskForm(page, job) {
  await page.goto(`/#/jobs/${job.job_id}/tasks`);
  await page.getByRole('button', { name: 'Add Work' }).click();
  // The picker's freeform lane: "Add Task" opens WorkItemForm in manual mode.
  await page.getByLabel('Add line').getByRole('button', { name: 'Add Task' }).click();
}

test('editing a preset with stamped tasks succeeds — no supersession, no 409', async ({ page }) => {
  // The seed's schemes are all heavily stamped onto tasks (find one with a
  // real reference count rather than assuming a specific seed name/pk).
  const api = await apiAs(personas.configtime);
  const schemes = (await api.get('/api/rate-schemes/?include_inactive=true')).results
    ?? (await api.get('/api/rate-schemes/?include_inactive=true'));
  const referenced = schemes.find((s) => s.reference_counts.task_count > 0);
  test.skip(!referenced, 'seed gap: no rate scheme with any stamped tasks');

  // A task that already stamped from this scheme, to prove afterward that
  // editing the preset never reprices it (task-owned money, not a live join).
  const jobs = (await api.get('/api/jobs/?page_size=100')).results;
  let stampedTask = null;
  for (const job of jobs) {
    stampedTask = (job.tasks || []).find((t) => t.source_scheme === referenced.rate_scheme_id);
    if (stampedTask) break;
  }
  await api.dispose();
  test.skip(!stampedTask, 'seed gap: could not resolve a task stamped from the referenced scheme');
  const rateBefore = stampedTask.rate;

  await openPricingTab(page);
  const row = page.locator('tr', { hasText: referenced.name });
  // The old supersession affordance ("Create new version") is gone entirely —
  // every scheme, referenced or not, offers a plain Edit now.
  await expect(row.getByRole('button', { name: 'Create new version' })).toHaveCount(0);
  await expect(row.getByRole('button', { name: 'Edit', exact: true })).toBeVisible();
  await row.getByRole('button', { name: 'Edit', exact: true }).click();

  const modal = page.getByLabel('Edit Rate Scheme');
  await expect(modal).toBeVisible();
  const newRate = (Number(referenced.rate) + 1).toFixed(2);
  await modal.getByRole('spinbutton', { name: 'Rate' }).fill(newRate);
  await modal.getByRole('button', { name: 'Save' }).click();

  // Success: the modal just closes (a 409/validation error would leave it
  // open with a FormMessage) and the list reflects the new rate.
  await expect(modal).toBeHidden();
  const updatedRow = page.locator('tr', { hasText: referenced.name });
  await expect(updatedRow.getByText(`$${newRate}/${referenced.unit_label}`)).toBeVisible();

  // The already-stamped task's OWN rate is untouched — it owns a permanent
  // copy, not a live pointer to the preset.
  const verifyApi = await apiAs(personas.configtime);
  const taskDetail = await verifyApi.get(`/api/tasks/${stampedTask.task_id}/`);
  await verifyApi.dispose();
  expect(taskDetail.rate).toBe(rateBefore);
});

test('retiring a preset hides it from the task-create dropdown', async ({ page }) => {
  const configApi = await apiAs(personas.configtime);
  const cats = await configApi.get('/api/accounting-categories/');
  const scheme = await configApi.post('/api/rate-schemes/', {
    name: `${stamp}-retire`, description: '', algorithm: 'entered_qty', rate: '5',
    unit_label: await anEnteredQtyUnit(configApi), modifiers: [],
    accounting_category: (cats.results || cats)[0].id,
  });
  await configApi.dispose();
  const job = await makeJob();

  await test.step('Before retiring: the preset is offered on task create', async () => {
    await openAddTaskForm(page, job);
    const options = await page.getByLabel('Rate Scheme *').locator('option').allTextContents();
    expect(options).toContain(scheme.name);
    await page.getByRole('button', { name: 'Cancel', exact: true }).click();
  });

  await test.step('Retire it from Settings → Pricing', async () => {
    await openPricingTab(page);
    // Keep the (about to be inactive) row visible after the toggle.
    await page.getByLabel('Show inactive rate schemes').check();
    const row = page.locator('tr', { hasText: scheme.name });
    await row.getByRole('button', { name: 'Retire' }).click();
    await expect(row.getByRole('button', { name: 'Reactivate' })).toBeVisible();
  });

  await test.step('After retiring: gone from the task-create dropdown', async () => {
    await openAddTaskForm(page, job);
    const options = await page.getByLabel('Rate Scheme *').locator('option').allTextContents();
    expect(options).not.toContain(scheme.name);
  });
});

// RM browser-testing fix: retiring/deleting the current default preset used
// to silently clear default_rate_scheme with no warning. Now Retire/Delete
// are withheld from the default row (a greyed-out "default" note stands in),
// and the server backstops with a 400 if reached any other way.
test('the default preset cannot be retired — no button, greyed-out note, guard clears once the default moves', async ({ page }) => {
  const configApi = await apiAs(personas.configtime);
  const cats = await configApi.get('/api/accounting-categories/');
  const scheme = await configApi.post('/api/rate-schemes/', {
    name: `${stamp}-guarded`, description: '', algorithm: 'entered_qty', rate: '9',
    unit_label: await anEnteredQtyUnit(configApi), modifiers: [],
    accounting_category: (cats.results || cats)[0].id,
  });
  await configApi.dispose();

  try {
    await test.step('Set it as the default preset', async () => {
      await openPricingTab(page);
      await page.locator('#default-rate-scheme').selectOption({ label: scheme.name });
      await page.getByRole('button', { name: 'Save default Rate Scheme' }).click();
      await expect(page.getByText('Default Rate Scheme saved.')).toBeVisible();
    });

    await test.step('Its row shows a "default" note, not Retire/Delete', async () => {
      const row = page.locator('tr', { hasText: scheme.name });
      await expect(row.getByText('default')).toBeVisible();
      await expect(row.getByRole('button', { name: 'Retire' })).toHaveCount(0);
      await expect(row.getByRole('button', { name: 'Delete' })).toHaveCount(0);
      // Edit stays available — only Retire/Delete are withheld.
      await expect(row.getByRole('button', { name: 'Edit', exact: true })).toBeVisible();
    });

    await test.step('Server-side backstop: a direct retire call is rejected', async () => {
      const api = await apiAs(personas.configtime);
      const resp = await api.postRaw(
        `/api/rate-schemes/${scheme.rate_scheme_id}/retire/`, {});
      expect(resp.status()).toBe(400);
      const body = await resp.json();
      expect(body.detail).toContain('change the default first');
      const stillActive = await api.get(`/api/rate-schemes/${scheme.rate_scheme_id}/`);
      expect(stillActive.is_active).toBe(true);
      await api.dispose();
    });

    await test.step('Change the default away, then Retire reappears and works', async () => {
      await openPricingTab(page);
      await page.locator('#default-rate-scheme').selectOption({ label: '-- None --' });
      await page.getByRole('button', { name: 'Save default Rate Scheme' }).click();
      await expect(page.getByText('Default Rate Scheme saved.')).toBeVisible();

      // Keep the (about to be inactive) row visible after the toggle.
      await page.getByLabel('Show inactive rate schemes').check();
      const row = page.locator('tr', { hasText: scheme.name });
      await expect(row.getByRole('button', { name: 'Retire' })).toBeVisible();
      await row.getByRole('button', { name: 'Retire' }).click();
      await expect(row.getByRole('button', { name: 'Reactivate' })).toBeVisible();
    });
  } finally {
    const cleanupApi = await apiAs(personas.configtime);
    await cleanupApi.patch('/api/settings/', { default_rate_scheme: '' });
    await cleanupApi.dispose();
  }
});

test('setting the default preset preselects it on new-task create', async ({ page }) => {
  const configApi = await apiAs(personas.configtime);
  const cats = await configApi.get('/api/accounting-categories/');
  const scheme = await configApi.post('/api/rate-schemes/', {
    name: `${stamp}-default`, description: '', algorithm: 'entered_qty', rate: '7',
    unit_label: await anEnteredQtyUnit(configApi), modifiers: [],
    accounting_category: (cats.results || cats)[0].id,
  });
  await configApi.dispose();
  const job = await makeJob();

  try {
    await test.step('Set the default preset in Settings → Pricing', async () => {
      await openPricingTab(page);
      await page.locator('#default-rate-scheme').selectOption({ label: scheme.name });
      await page.getByRole('button', { name: 'Save default Rate Scheme' }).click();
      await expect(page.getByText('Default Rate Scheme saved.')).toBeVisible();
    });

    await test.step('A new Add Task form opens with it preselected', async () => {
      await openAddTaskForm(page, job);
      await expect(page.getByLabel('Rate Scheme *')).toHaveValue(String(scheme.rate_scheme_id));
    });
  } finally {
    // Leave shop config as found — a PW_KEEP_DB rerun of just this file
    // must not leak a default preset into sibling specs' task-create forms.
    const cleanupApi = await apiAs(personas.configtime);
    await cleanupApi.patch('/api/settings/', { default_rate_scheme: '' });
    await cleanupApi.dispose();
  }
});

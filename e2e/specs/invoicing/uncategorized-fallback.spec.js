// task-owned-money Phase 3 (Tasks 3, 4, 8): a Task composed onto an invoice
// with no accounting_category of its own is auto-stamped with the
// Configuration-designated fallback category instead of being blocked
// (InvoiceWizardService._resolve_fallback_category, apps/invoicing/
// services.py), and the resulting line wears an amber
// "Uncategorized -> <name>" badge (LineItemTable.svelte) until corrected via
// the line edit modal. This spec: the config persona designates the
// fallback (Settings -> Accounting -> "Uncategorized lines" fieldset,
// explicit Save); a financials/jobs manager creates a flat (non-hour) task
// with no AC (asserting the "-- none (categorize at invoicing) --" option
// exists), composes it onto a draft invoice via Reconcile, sees the badge,
// corrects one line's AC via the line edit modal (badge clears on the
// panel's own refetch, no manual reload), composes a second null-AC task,
// and confirms the invoice's send gate passes with the fallback-stamped
// line still in place. QBO push itself is not e2e-reachable (no
// QBOConnection row in the seed -- see e2e/specs/invoice-seeding-and-send/
// draft-placeholder.spec.js's header comment); "send succeeds" is asserted
// as that pre-send gate (the enabled Send Invoice link renders because a
// fallback-stamped line still carries a non-null accounting_category, so
// allLinesHaveCategory is true) -- the same boundary every other
// send-adjacent spec in this suite stops at.
//
// The targeted-percentage-adjustment + fallback-badge coexistence warning
// (InvoicePanel's .fallback-warning-notice) is covered too: cheap to set up
// (one percentage RateScheme + one targeted adjustment-line submit, no
// estimate/CO scaffolding), since the fallback category is excluded from
// AdjustmentModal's target-category checkboxes by construction, so a
// targeted adjustment on any *other* category coexists trivially with a
// fallback-flagged line.
import { expect, test } from '@playwright/test';
import { apiAs } from '../../fixtures/api.js';
import { personas } from '../../fixtures/personas.js';

const stamp = `e2e-fac-${Date.now().toString(36)}`;
const NONE_AC_OPTION = '— none (categorize at invoicing) —';

// WizardAtomRow renders an 'available' atom as a <label> (selectable) and a
// 'claimed_by_current' one as a <span> (already composed) -- same row,
// different wrapper once Add Here fires. Match both, like
// specs/deposits/deposit-credit.spec.js's depositCreditRow helper.
function atomRow(page, name) {
  return page.locator('label, span').filter({ hasText: name }).first();
}

// Restores the fallback-AC Configuration key to unset once every test in
// this file has run, regardless of pass/fail — designating a category as
// the fallback excludes it from every normal accounting-category listing
// (AccountingCategoryViewSet.get_queryset), which would otherwise leak into
// later spec files in the same run (e.g. specs/settings/
// accounting-categories.spec.js expects to find its seeded rows unfiltered).
test.afterAll(async () => {
  const api = await apiAs(personas.configtime);
  try {
    await api.patch('/api/settings/', { fallback_accounting_category: '' });
  } finally {
    await api.dispose();
  }
});

test.describe('Settings: fallback accounting category', () => {
  test.use({ storageState: personas.configtime.storageState });

  test('config persona designates the fallback AC with an explicit Save', async ({ page }) => {
    // A throwaway category (not a seeded one): becoming the fallback hides
    // a category from every normal picker AND from the Accounting
    // Categories manager's own list (same exclusion) — designating a real
    // seeded category here would make it vanish from other specs'
    // listings (e.g. the "Service" row in
    // specs/settings/accounting-categories.spec.js). Same throwaway-row
    // pattern that spec itself uses.
    const api = await apiAs(personas.configtime);
    const name = `${stamp} fallback`;
    const fallbackCat = await api.post('/api/accounting-categories/', {
      code: name.slice(-20).toUpperCase(), name, taxable: false,
    });
    await api.dispose();

    await page.goto('/#/settings');
    const fieldset = page.locator('fieldset').filter({ hasText: 'Uncategorized lines' });
    await expect(fieldset).toBeVisible();

    await fieldset.getByLabel('Fallback accounting category').selectOption({ label: fallbackCat.name });
    await fieldset.getByRole('button', { name: 'Save' }).click();
    await expect(fieldset.getByText('Fallback accounting category saved.')).toBeVisible();

    // Persisted server-side, not just local select state.
    const verifyApi = await apiAs(personas.configtime);
    const settings = await verifyApi.get('/api/settings/');
    await verifyApi.dispose();
    expect(String(settings.fallback_accounting_category)).toBe(String(fallbackCat.id));
  });
});

test.describe('Uncategorized task composed onto an invoice', () => {
  test.use({ storageState: personas.finjobs.storageState });

  test('badge shows, correction clears it, a second flagged line survives the send gate', async ({ page }) => {
    const api = await apiAs(personas.finjobs);

    // The fallback the describe block above configured -- read back via API
    // rather than a shared JS var, so this test stands on its own footing
    // (e.g. under --grep) instead of depending on module-scope state.
    // GET /api/settings/ is CanManageConfig-gated (not plain IsAuthenticated
    // — finjobs lacks that atom), so use the configtime persona for this one
    // read.
    const configReadApi = await apiAs(personas.configtime);
    const settings = await configReadApi.get('/api/settings/');
    await configReadApi.dispose();
    test.skip(!settings.fallback_accounting_category,
      'seed gap: fallback AC not configured (the settings spec above must run first)');

    const catsResp = await api.get('/api/accounting-categories/?include_fallback=true');
    const cats = catsResp.results || catsResp;
    const fallbackCat = cats.find((c) => String(c.id) === String(settings.fallback_accounting_category));
    const correctionCat = cats.find(
      (c) => fallbackCat && c.id !== fallbackCat.id && !c.is_deposit && c.is_active);
    test.skip(!fallbackCat || !correctionCat,
      'seed gap: configured fallback category or a second non-deposit category missing');

    // A "flat" (non-hour) task-applicable rate scheme -- flat per
    // WorkItemForm's own isHourUnit derivation (unit_label !== 'hour');
    // RateScheme.clean() ties elapsed_time schemes to unit_label='hour', so
    // excluding hour here guarantees an entered_qty scheme (task_applicable
    // already excludes percentage).
    const schemesResp = await api.get('/api/rate-schemes/?task_applicable=true');
    const schemes = schemesResp.results || schemesResp;
    const flatScheme = schemes.find((s) => s.unit_label !== 'hour');
    test.skip(!flatScheme, 'seed gap: no non-hour task-applicable rate scheme');

    const contact = (await api.get('/api/contacts/?page_size=1')).results[0];
    const job = await api.post('/api/jobs/', {
      name: `${stamp} fallback-ac job`, contact: contact.contact_id,
    });
    // Job creation/approval isn't the flow under test -- API setup, same
    // precedent as specs/add-line-and-work-authoring/stamped-task-money.spec.js.
    await api.patch(`/api/jobs/${job.job_id}/`, { status: 'submitted' });
    await api.patch(`/api/jobs/${job.job_id}/`, { status: 'approved' });

    const task1Name = `${stamp} flat task 1`;

    await test.step('Manager creates a flat task with no accounting category', async () => {
      await page.goto(`/#/jobs/${job.job_id}/tasks`);
      await page.getByRole('button', { name: 'Add Work' }).click();
      // Scoped to the "Add line" picker dialog -- it also offers its own
      // "Add Work" (freeform kind) button, distinct from "Add Task".
      await page.getByLabel('Add line').getByRole('button', { name: 'Add Task' }).click();

      await page.getByLabel('Rate Scheme *').selectOption({ label: flatScheme.name });
      await page.getByLabel('Name *').fill(task1Name);

      const acSelect = page.getByLabel('Accounting Category');
      await expect(acSelect.getByRole('option', { name: NONE_AC_OPTION })).toHaveCount(1);
      await acSelect.selectOption({ label: NONE_AC_OPTION });

      await page.getByRole('button', { name: 'Save', exact: true }).click();
      await expect(page.getByRole('dialog')).toHaveCount(0);
    });

    const task1 = (await api.get(`/api/jobs/${job.job_id}/`)).tasks.find((t) => t.name === task1Name);
    expect(task1.accounting_category).toBeNull();
    // Settling the entered quantity to make the task billable isn't the flow
    // under test -- API, same as this suite's other setup-only task mutations.
    await api.post(`/api/tasks/${task1.task_id}/complete/`, { add_qty: '2' });

    await test.step('Start the invoice and compose the null-AC task via Reconcile', async () => {
      await page.goto(`/#/jobs/${job.job_id}/invoice`);
      await page.getByRole('button', { name: 'Start Invoice' }).click();
      await expect(page.getByText(`Invoice: Draft — ${job.job_number}`)).toBeVisible();

      await page.getByRole('button', { name: 'Reconcile' }).click();
      await expect(page.getByRole('heading', { name: 'Tasks and Materials' })).toBeVisible();

      const row = atomRow(page, task1Name);
      await row.locator('input[type="checkbox"]').check();
      // Scoped to the "new line item" affordance -- once a line item already
      // exists (task 2 onward), WizardLineItemCard renders its OWN per-line
      // "Add Here" button too, and the bare role/name locator would be
      // ambiguous between the two.
      await page.locator('.new-line-item').getByRole('button', { name: 'Add Here' }).click();
      await expect(row).toContainText('→ line 1');

      await page.getByRole('button', { name: 'Back to lines' }).click();
    });

    await test.step('The composed line wears the fallback badge', async () => {
      const badge = page.locator('.fallback-badge');
      await expect(badge).toHaveCount(1);
      await expect(badge).toContainText(`Uncategorized → ${fallbackCat.name}`);
    });

    await test.step('Correcting the AC on the line clears the badge without a manual reload', async () => {
      const row = page.locator('tr', { hasText: task1Name });
      await row.getByRole('button', { name: 'Edit' }).click();
      const modal = page.getByRole('dialog');
      await expect(modal.getByRole('heading', { name: 'Edit Line Item' })).toBeVisible();

      // The fallback category is excluded from this picker by construction
      // -- there's nothing to "leave it as fallback"; correcting always
      // means picking a different real category.
      const acField = modal.getByLabel('Accounting Category *');
      await expect(
        acField.getByRole('option', { name: `${fallbackCat.code} - ${fallbackCat.name}` })
      ).toHaveCount(0);
      await acField.selectOption({ label: `${correctionCat.code} - ${correctionCat.name}` });
      await modal.getByRole('button', { name: 'Save' }).click();
      await expect(page.getByRole('dialog')).toHaveCount(0);

      await expect(page.locator('.fallback-badge')).toHaveCount(0);
    });

    const task2Name = `${stamp} flat task 2`;
    await test.step('A second null-AC task is composed; the fallback badge shows again', async () => {
      const task2 = await api.post(`/api/jobs/${job.job_id}/tasks/`, {
        name: task2Name, description: '', rate_scheme: flatScheme.rate_scheme_id,
        accounting_category: null,
      });
      expect(task2.accounting_category).toBeNull();
      await api.post(`/api/tasks/${task2.task_id}/complete/`, { add_qty: '3' });

      await page.getByRole('button', { name: 'Reconcile' }).click();
      await expect(page.getByRole('heading', { name: 'Tasks and Materials' })).toBeVisible();
      const row = atomRow(page, task2Name);
      await row.locator('input[type="checkbox"]').check();
      // Scoped to the "new line item" affordance -- once a line item already
      // exists (task 2 onward), WizardLineItemCard renders its OWN per-line
      // "Add Here" button too, and the bare role/name locator would be
      // ambiguous between the two.
      await page.locator('.new-line-item').getByRole('button', { name: 'Add Here' }).click();
      await expect(row).toContainText('→ line');
      await page.getByRole('button', { name: 'Back to lines' }).click();

      await expect(page.locator('.fallback-badge')).toHaveCount(1);
      await expect(page.locator('.fallback-badge')).toContainText(`Uncategorized → ${fallbackCat.name}`);
    });

    await test.step('Send gate: the fallback-stamped line still counts as categorized', async () => {
      await expect(page.locator('.send-blocked')).toHaveCount(0);
      await expect(page.getByText('Assign an accounting category to every line before sending.')).toHaveCount(0);
      await expect(page.getByRole('link', { name: /Send Invoice|Resend Invoice/ })).toBeVisible();
    });

    await test.step('Targeted percentage adjustment + fallback badge: the coexistence warning', async () => {
      // A percentage RateScheme is a document-level adjustment preset, not a
      // task-creation scheme -- CanManageConfig-gated, same as any other
      // RateScheme write (RateSchemeViewSet).
      const configApi = await apiAs(personas.configtime);
      const svc = await configApi.post('/api/rate-schemes/', {
        name: `${stamp} rush adj`, description: '', algorithm: 'percentage',
        rate: '15', unit_label: '%', accounting_category: correctionCat.id,
      });
      await configApi.dispose();

      await expect(page.locator('.fallback-warning-notice')).toHaveCount(0);

      await page.getByRole('button', { name: 'Add Adjustment' }).click();
      const modal = page.getByRole('dialog', { name: 'Add Adjustment' });
      await modal.getByLabel('Percentage rate scheme').selectOption({ label: `${svc.name} (${svc.rate}%)` });
      // Any *other* real category as the target -- the fallback category is
      // never offered here (excluded from this modal's category list), so a
      // targeted adjustment coexists with a fallback-flagged line trivially.
      await modal.getByRole('checkbox', { name: `${correctionCat.code} - ${correctionCat.name}` }).check();
      await modal.getByRole('button', { name: 'Add Adjustment' }).click();
      await expect(page.getByRole('dialog')).toHaveCount(0);

      await expect(page.locator('.fallback-warning-notice')).toContainText(
        'This invoice has a targeted percentage adjustment, but targeted adjustments never include uncategorized lines.'
      );
    });

    await api.dispose();
  });
});

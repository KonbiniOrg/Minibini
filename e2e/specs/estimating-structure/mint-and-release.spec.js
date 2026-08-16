// claims-by-construction estimating structure (.superpowers/sdd/
// 2026-08-15-estimating-structure-plan) — Task 10, the end-to-end structure
// journey. Tasks 1-9 (all committed on this branch) built: work_declined +
// the acceptance checklist, MintService (Generate work… claims a new task to
// an accepted line), the bundle-into-a-line modal (Task 8, keep-total), and
// Task 6's retirement of both the manual approved->in_progress pill gesture
// and the agreement-side "Add selected here" attach button (replaced by the
// bundle-modal path everywhere).
//
// One journey, one job, built fresh via the API (contact + a dedicated rate
// scheme/catalog service item so the mint modal's rate-scheme dropdown has a
// real default to preselect — the seed's own default_rate_scheme isn't
// reliable, same caution as specs/settings/rate-scheme-presets.spec.js):
// a draft estimate with a catalog service line, two plain hand lines, and a
// bundled line built through the BundleModal gesture itself (select two pool
// atoms -> "Bundle into line…" -> edit qty under keep-total -> Create) —
// then send/accept/mint/decline walks the checklist to the job's
// auto-release. A second test covers the two edge assertions that don't fit
// that single walk: an approved-but-unanswered job's pill still offers no
// manual in_progress option, and an all-catalog estimate skips the
// "approved" rest stop entirely.
import { expect, test } from '@playwright/test';
import { apiAs } from '../../fixtures/api.js';
import { personas } from '../../fixtures/personas.js';

test.use({ storageState: personas.finjobs.storageState });

const stamp = `e2e-struct-${Date.now().toString(36)}`;
let scheme;
let category;

// A dedicated preset (entered_qty, non-hour unit) set as the shop's
// default_rate_scheme so the "Generate work…" mint modal's Rate Scheme
// dropdown preselects without any extra picking step — mirrors
// specs/add-line-and-work-authoring/stamped-task-money.spec.js's arrange +
// cleanup idiom exactly.
test.beforeAll(async () => {
  const configApi = await apiAs(personas.configtime);
  const cats = await configApi.get('/api/accounting-categories/');
  category = (cats.results || cats)
    .find((c) => c.is_active !== false && !c.is_deposit && !c.is_fallback);
  const units = await configApi.get('/api/settings/units/');
  const unit = units.find((u) => u !== 'none' && u !== 'hour') || units[0];
  scheme = await configApi.post('/api/rate-schemes/', {
    name: `${stamp}-scheme`, description: '', algorithm: 'entered_qty',
    rate: '20.00', unit_label: unit, accounting_category: category.id, modifiers: [],
  });
  await configApi.patch('/api/settings/', { default_rate_scheme: String(scheme.rate_scheme_id) });
  await configApi.dispose();
});

test.afterAll(async () => {
  const configApi = await apiAs(personas.configtime);
  await configApi.patch('/api/settings/', { default_rate_scheme: '' });
  await configApi.dispose();
});

test('structure journey: bundle a line, send, accept, mint/decline the checklist, auto-release', async ({ page }) => {
  const api = await apiAs(personas.finjobs);
  const contact = (await api.get('/api/contacts/?page_size=1')).results[0];

  const serviceItem = await api.post('/api/service-items/', {
    template_name: `${stamp} catalog service`, description: '',
    rate_scheme: scheme.rate_scheme_id, default_active_modifiers: [], is_active: true,
  });

  const job = await api.post('/api/jobs/', { name: `${stamp} job`, contact: contact.contact_id });

  // Two tasks left OFF the estimate — the pool atoms the bundle gesture
  // itself will claim through the UI.
  const bundleTaskA = await api.post(`/api/jobs/${job.job_id}/tasks/`, {
    name: `${stamp} bundle atom A`, rate_scheme: scheme.rate_scheme_id, est_qty: '2',
  });
  const bundleTaskB = await api.post(`/api/jobs/${job.job_id}/tasks/`, {
    name: `${stamp} bundle atom B`, rate_scheme: scheme.rate_scheme_id, est_qty: '2',
  });

  const estimate = await api.post('/api/estimates/', { job: job.job_id });
  await api.post(`/api/estimates/${estimate.estimate_id}/line-items-from-service/`, {
    service_item: serviceItem.template_id, qty: '1',
  });
  const handLineA = await api.post(`/api/estimates/${estimate.estimate_id}/line-items/`, {
    description: `${stamp} hand line A`, qty: '3', units: scheme.unit_label, price: '50.00',
    accounting_category: category.id,
  });
  const handLineB = await api.post(`/api/estimates/${estimate.estimate_id}/line-items/`, {
    description: `${stamp} hand line B`, qty: '1', units: scheme.unit_label, price: '75.00',
    accounting_category: category.id,
  });

  // mark-open's send-gate requires a non-empty Deliverables list.
  await api.post(`/api/jobs/${job.job_id}/deliverables/`, {
    description: `${stamp} deliverable`, qty_ordered: '1', units: 'ea',
  });

  const bundleDescription = `${stamp} bundled projected line`;

  await page.goto(`/#/jobs/${job.job_id}/estimate/${estimate.estimate_id}`);
  const editTable = page.locator('table.line-items-table');
  // A line's OWN row (not its nested AtomChildRow/caption siblings — those
  // can carry the same text: a mint-generated task's name mirrors the line
  // description, and a crystallized catalog task's name is the template
  // name). Only the real line's description cell carries preserve-breaks.
  const lineRow = (desc) => editTable.locator('tbody tr').filter({
    has: page.locator('td.preserve-breaks', { hasText: desc }),
  });

  await test.step('Draft: the catalog + two hand lines are on the estimate; no "Add selected here" anywhere', async () => {
    await expect(lineRow(serviceItem.template_name)).toBeVisible();
    await expect(lineRow(handLineA.description)).toBeVisible();
    await expect(lineRow(handLineB.description)).toBeVisible();
    await expect(page.getByRole('button', { name: 'Add selected here' })).toHaveCount(0);
  });

  await test.step('Bundle into line…: select two pool atoms, edit qty under keep-total, Create', async () => {
    const pool = page.locator('.uncovered-work-section');
    await pool.locator('tbody tr').filter({ hasText: bundleTaskA.name })
      .locator('input[type="checkbox"]').check();
    await pool.locator('tbody tr').filter({ hasText: bundleTaskB.name })
      .locator('input[type="checkbox"]').check();

    const newlineRow = page.locator('tr.doc-newline');
    await expect(newlineRow).toBeVisible();
    await newlineRow.getByRole('button', { name: 'Bundle into line…' }).click();

    const modal = page.getByRole('dialog');
    await expect(modal).toContainText('Bundle into line');
    await expect(modal.locator('tbody tr').filter({ hasText: bundleTaskA.name })).toBeVisible();
    await expect(modal.locator('tbody tr').filter({ hasText: bundleTaskB.name })).toBeVisible();

    const keepTotal = modal.getByRole('checkbox', { name: /keep total/i });
    await expect(keepTotal).toBeChecked();

    const totalText = await modal.locator('tfoot td').last().innerText();
    const total = Number(totalText.replace(/[^0-9.-]/g, ''));
    expect(total).toBeGreaterThan(0);

    const qtyInput = modal.getByLabel(/Quantity/);
    const priceInput = modal.getByLabel(/^Price/);
    const qtyBefore = Number(await qtyInput.inputValue());
    expect(qtyBefore).toBeGreaterThan(0);

    // Editing qty re-derives price so qty * price still equals the
    // selected atoms' summed total (Task 8's keep-total gesture).
    const newQty = (qtyBefore * 2).toFixed(2);
    await qtyInput.fill(newQty);
    const expectedPrice = (total / Number(newQty)).toFixed(2);
    await expect(priceInput).toHaveValue(expectedPrice);
    await expect(keepTotal).toBeChecked();

    await modal.getByLabel('Description').fill(bundleDescription);
    await modal.getByRole('button', { name: 'Create line' }).click();
    await expect(modal).toBeHidden();

    await expect(lineRow(bundleDescription)).toBeVisible();
    await expect(page.locator('tr.doc-atom-caption').filter({ hasText: 'based on 2 tasks:' })).toBeVisible();
    await expect(editTable.getByText(bundleTaskA.name)).toBeVisible();
    await expect(editTable.getByText(bundleTaskB.name)).toBeVisible();
    // Claimed now — gone from the still-uncovered pool.
    await expect(pool.locator('tbody tr').filter({ hasText: bundleTaskA.name })).toHaveCount(0);
    await expect(pool.locator('tbody tr').filter({ hasText: bundleTaskB.name })).toHaveCount(0);
  });

  await test.step('Send (open): the surface goes inert — no edit or mint affordances anywhere', async () => {
    await api.patch(`/api/estimates/${estimate.estimate_id}/`, { status: 'open' });
    await page.reload(); // same-fragment goto doesn't renavigate a hash router
    await expect(page.getByRole('button', { name: 'Add line' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Add Adjustment' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Generate work…' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'No work needed' })).toHaveCount(0);
    await expect(page.locator('.uncovered-work-section')).toHaveCount(0);
    await expect(page.locator('.doc-warning')).toHaveCount(0);
  });

  await test.step('Accept: the checklist banner counts the two unanswered hand lines', async () => {
    await api.patch(`/api/estimates/${estimate.estimate_id}/`, { status: 'accepted' });
    await page.reload();
    await expect(page.locator('.doc-warning')).toHaveText(
      '2 line(s) need a work decision — the job starts automatically when all are answered.'
    );
    // The catalog and bundled lines are already answered (catalog identity /
    // atom sources) — no gesture offered on them.
    const catalogRow = lineRow(serviceItem.template_name);
    await expect(catalogRow.getByRole('button', { name: 'Generate work…' })).toHaveCount(0);
    const bundledRow = lineRow(bundleDescription);
    await expect(bundledRow.getByRole('button', { name: 'Generate work…' })).toHaveCount(0);
  });

  await test.step('"Generate work…" on hand line A mirror-seeds the manual-task modal; saving claims it and counts the banner down', async () => {
    const rowA = lineRow(handLineA.description);
    await rowA.getByRole('button', { name: 'Generate work…' }).click();

    const dialog = page.getByRole('dialog');
    await expect(dialog.getByRole('heading', { name: 'Add Manual Task' })).toBeVisible();
    await expect(dialog.getByLabel('Name *')).toHaveValue(handLineA.description);
    await expect(dialog.getByLabel('Estimated qty')).toHaveValue(handLineA.qty);
    await dialog.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(dialog).toBeHidden();

    await expect(rowA.getByRole('button', { name: 'Generate work…' })).toHaveCount(0);
    // The catalog line ALSO reads "based on 1 task:" (its own Task
    // crystallized at acceptance) — scope to the row immediately following
    // hand line A's own <tr> (AtomCaptionRow is a sibling, not nested).
    const captionA = rowA.locator('xpath=following-sibling::tr[1]');
    await expect(captionA).toHaveClass(/doc-atom-caption/);
    await expect(captionA).toContainText('based on 1 task:');
    await expect(page.locator('.doc-warning')).toHaveText(
      '1 line(s) need a work decision — the job starts automatically when all are answered.'
    );
  });

  await test.step('"No work needed" on hand line B clears the banner AND auto-releases the job', async () => {
    const rowB = lineRow(handLineB.description);
    await rowB.getByRole('button', { name: 'No work needed' }).click();

    await expect(rowB.getByText('no work needed')).toBeVisible();
    await expect(rowB.getByRole('button', { name: 'Undo' })).toBeVisible();
    await expect(page.locator('.doc-warning')).toHaveCount(0);

    // Last unanswered line resolved -> approved -> in_progress, both via the
    // API and the header pill refreshing in place (no reload).
    await expect.poll(async () => {
      const check = await apiAs(personas.finjobs);
      const detail = await check.get(`/api/jobs/${job.job_id}/`);
      await check.dispose();
      return detail.status;
    }).toBe('in_progress');

    const pill = page.locator('.job-header select');
    await expect(pill).toHaveValue('in_progress');
    await expect(pill.locator('option:checked')).toHaveText('In Progress');
  });

  await api.dispose();
});

test('approved-but-unanswered pill offers no manual in_progress; an all-catalog estimate accepts straight to in_progress', async ({ page }) => {
  const stamp2 = `e2e-struct2-${Date.now().toString(36)}`;
  const api = await apiAs(personas.finjobs);
  const contact = (await api.get('/api/contacts/?page_size=1')).results[0];

  await test.step('Approved job with an unanswered hand line: the pill has no in_progress option', async () => {
    const job = await api.post('/api/jobs/', { name: `${stamp2} unanswered job`, contact: contact.contact_id });
    const estimate = await api.post('/api/estimates/', { job: job.job_id });
    await api.post(`/api/estimates/${estimate.estimate_id}/line-items/`, {
      description: `${stamp2} unanswered hand line`, qty: '1', units: scheme.unit_label, price: '40.00',
      accounting_category: category.id,
    });
    await api.post(`/api/jobs/${job.job_id}/deliverables/`, {
      description: `${stamp2} deliverable`, qty_ordered: '1', units: 'ea',
    });
    await api.patch(`/api/estimates/${estimate.estimate_id}/`, { status: 'open' });
    await api.patch(`/api/estimates/${estimate.estimate_id}/`, { status: 'accepted' });

    const detail = await api.get(`/api/jobs/${job.job_id}/`);
    expect(detail.status).toBe('approved');

    await page.goto(`/#/jobs/${job.job_id}`);
    const pill = page.locator('.job-header select');
    await expect(pill).toHaveValue('approved');
    await expect(pill.locator('option[value="in_progress"]')).toHaveCount(0);
    await expect(pill.locator('option', { hasText: 'In Progress' })).toHaveCount(0);
  });

  await test.step('An all-catalog estimate skips the approved rest stop: acceptance lands the job straight on in_progress', async () => {
    const serviceItem = await api.post('/api/service-items/', {
      template_name: `${stamp2} all-catalog service`, description: '',
      rate_scheme: scheme.rate_scheme_id, default_active_modifiers: [], is_active: true,
    });
    const job = await api.post('/api/jobs/', { name: `${stamp2} all-catalog job`, contact: contact.contact_id });
    const estimate = await api.post('/api/estimates/', { job: job.job_id });
    await api.post(`/api/estimates/${estimate.estimate_id}/line-items-from-service/`, {
      service_item: serviceItem.template_id, qty: '1',
    });
    await api.post(`/api/jobs/${job.job_id}/deliverables/`, {
      description: `${stamp2} all-catalog deliverable`, qty_ordered: '1', units: 'ea',
    });
    await api.patch(`/api/estimates/${estimate.estimate_id}/`, { status: 'open' });
    await api.patch(`/api/estimates/${estimate.estimate_id}/`, { status: 'accepted' });

    const detail = await api.get(`/api/jobs/${job.job_id}/`);
    expect(detail.status).toBe('in_progress');

    await page.goto(`/#/jobs/${job.job_id}`);
    const pill = page.locator('.job-header select');
    await expect(pill).toHaveValue('in_progress');
    await expect(pill.locator('option:checked')).toHaveText('In Progress');
  });

  await api.dispose();
});

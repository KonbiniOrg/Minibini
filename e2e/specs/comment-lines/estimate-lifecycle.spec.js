// Comment lines on the estimate surface (is_comment, merged from main
// 2026-09-21): a purely informational row — no charge, no atom linkage.
// This spec drives the whole lifecycle through the UI where the feature
// lives (the Add line picker's "Comment (no charge)" checkbox and the
// AC-free follow-up form) and asserts the document-only invariants via
// the API, mirroring tests/test_comment_line_items.py +
// tests/test_agreement_composition.py:
//   - the add form asks for a description only (no AC / qty / price),
//   - the stored line is zeroed and category-free,
//   - acceptance crystallizes the sibling catalog line into a Task but
//     never the comment (no Task, no Material, no source row),
//   - compose_agreement excludes it, so a freshly seeded invoice never
//     carries it.
// Built fresh (job + catalog service item + draft estimate) — same
// precedent as estimating-structure/mint-and-release.spec.js.
import { expect, test } from '@playwright/test';
import { apiAs } from '../../fixtures/api.js';
import { personas } from '../../fixtures/personas.js';

test.use({ storageState: personas.finjobs.storageState });

const stamp = `e2e-cmtest-${Date.now().toString(36)}`;

test('estimate comment line: AC-free add form, document-only through acceptance, excluded from agreement + invoice seeding', async ({ page }) => {
  const api = await apiAs(personas.finjobs);

  const contact = (await api.get('/api/contacts/?page_size=1')).results[0];
  const schemes = await api.get('/api/rate-schemes/?page_size=100');
  const scheme = (schemes.results || schemes)
    .find((s) => s.algorithm === 'entered_qty' && s.is_active !== false);
  test.skip(!scheme, 'seed gap: no active entered_qty rate scheme');

  const serviceItem = await api.post('/api/service-items/', {
    template_name: `${stamp} rush handling`, description: '',
    rate_scheme: scheme.rate_scheme_id, default_active_modifiers: [], is_active: true,
  });

  const job = await api.post('/api/jobs/', {
    name: `${stamp} job`, contact: contact.contact_id,
  });
  const estimate = await api.post('/api/estimates/', { job: job.job_id });
  // The real (chargeable) contrast line: a catalog service line that
  // acceptance will crystallize into a Task — the positive anchor for
  // every "the comment did nothing" assertion below.
  const serviceLine = await api.post(
    `/api/estimates/${estimate.estimate_id}/line-items-from-service/`,
    { service_item: serviceItem.template_id, qty: '2' },
  );

  const commentDesc = `${stamp} see attached spec sheet`;

  // A line's OWN row — not a nested atom child row that can carry the same
  // text (same convention as estimating-structure/mint-and-release.spec.js).
  const lineRow = (desc) => page.locator('table.line-items-table tbody tr').filter({
    has: page.locator('td.preserve-breaks', { hasText: desc }),
  });

  await test.step('Add line → "Comment (no charge)": the follow-up form asks for a description only — no AC, no qty, no price', async () => {
    await page.goto(`/#/jobs/${job.job_id}/estimate/${estimate.estimate_id}`);
    // Positive anchor: the doc surface loaded the real line before we
    // touch the add flow.
    await expect(lineRow(serviceItem.template_name)).toBeVisible();

    await page.getByRole('button', { name: 'Add line' }).click();
    const picker = page.getByRole('dialog');
    await picker.getByPlaceholder(/search/i).fill(commentDesc);
    await picker.getByRole('checkbox', { name: 'Comment (no charge)' }).check();
    await picker.getByRole('button', { name: 'Add Line', exact: true }).click();

    const form = page.getByRole('dialog');
    await expect(form.getByRole('heading', { name: 'Add Comment' })).toBeVisible();
    // Anchor: the description field exists and carries the typed text —
    // so the absence assertions below are about a rendered form, not a
    // blank dialog.
    await expect(form.getByLabel('Description')).toHaveValue(commentDesc);
    await expect(form.getByLabel(/Accounting Category/)).toHaveCount(0);
    await expect(form.getByLabel(/Quantity/)).toHaveCount(0);
    await expect(form.getByLabel(/^Price/)).toHaveCount(0);

    await form.getByRole('button', { name: 'Add', exact: true }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await expect(lineRow(commentDesc)).toBeVisible();
  });

  await test.step('The stored line is zeroed and category-free; the estimate total is the service line alone', async () => {
    const detail = await api.get(`/api/estimates/${estimate.estimate_id}/`);
    const commentLine = detail.line_items.find((li) => li.description === commentDesc);
    expect(commentLine).toBeTruthy();
    expect(commentLine.is_comment).toBe(true);
    expect(commentLine.accounting_category).toBeNull();
    expect(Number(commentLine.qty)).toBe(0);
    expect(Number(commentLine.price)).toBe(0);

    const serviceAmount = Number(serviceLine.qty) * Number(serviceLine.price);
    expect(serviceAmount).toBeGreaterThan(0); // anchor: the contrast line has real money
    expect(Number(detail.total)).toBeCloseTo(serviceAmount, 2);
  });

  await test.step('Acceptance crystallizes the service line into a Task; the comment stays document-only', async () => {
    await api.post(`/api/jobs/${job.job_id}/deliverables/`, {
      description: `${stamp} deliverable`, qty_ordered: '1', units: 'ea',
    });
    await api.patch(`/api/estimates/${estimate.estimate_id}/`, { status: 'open' });
    await api.patch(`/api/estimates/${estimate.estimate_id}/`, { status: 'accepted' });

    const jobDetail = await api.get(`/api/jobs/${job.job_id}/`);
    // Positive anchor: acceptance did crystallize — exactly the service
    // line's Task exists on the job...
    expect((jobDetail.tasks || []).length).toBe(1);
    // ...and it is not the comment (nothing on the job carries its text).
    expect((jobDetail.tasks || []).some((t) => (t.name || '').includes('see attached'))).toBe(false);
    expect((jobDetail.materials || []).some((m) => (m.description || '').includes('see attached'))).toBe(false);

    const detail = await api.get(`/api/estimates/${estimate.estimate_id}/`);
    const crystallized = detail.line_items.find((li) => li.description === serviceLine.description);
    expect(crystallized.sources.length).toBe(1); // anchor: claims machinery ran
    const commentLine = detail.line_items.find((li) => li.description === commentDesc);
    expect(commentLine.sources.length).toBe(0); // the comment got no source row
  });

  await test.step('The agreement and a freshly seeded invoice carry the service line, never the comment', async () => {
    const agreement = await api.get(`/api/jobs/${job.job_id}/agreement/`);
    const descriptions = agreement.lines.map((l) => l.description);
    expect(descriptions).toContain(serviceLine.description); // anchor
    expect(descriptions).not.toContain(commentDesc);

    await page.goto(`/#/jobs/${job.job_id}/invoice`);
    await page.getByRole('button', { name: 'Start Invoice' }).click();
    await expect(page.getByRole('heading', { name: 'Line Items' })).toBeVisible();
    // Positive anchor: the agreement-backed real line seeded...
    await expect(lineRow(serviceLine.description)).toBeVisible();
    // ...and the comment did not.
    await expect(page.locator('table.line-items-table').getByText(commentDesc)).toHaveCount(0);
  });

  await api.dispose();
});

// Comment lines on the change-order surface (is_comment merge 2026-09-21 +
// b7880c56 wiring is_comment through COEditView's edit gestures):
//   - a comment ADD is authored through the same Add line picker as the
//     estimate's, renders as a tinted CO row, and moves the amended-
//     agreement total by exactly nothing;
//   - the added comment row's Edit gesture reopens COLineItemModal in
//     comment mode (checkbox pre-checked, qty/price/AC collapsed);
//   - Replace… on a claimed agreement line with the comment checkbox is an
//     ANNOTATED REMOVAL: the original strikes for $0, and at acceptance the
//     target drops from the agreement, its task is descoped/cancelled, and
//     no claims ever move onto the comment line
//     (tests/test_comment_line_items.py ChangeOrderCommentLineAcceptanceTest,
//     tests/test_agreement_composition.py ComposeAgreementCommentLineTests).
// Build idiom + row helpers mirror specs/change-orders/amend-in-place.spec.js.
import { expect, test } from '@playwright/test';
import { apiAs } from '../../fixtures/api.js';
import { personas } from '../../fixtures/personas.js';

test.use({ storageState: personas.finjobs.storageState });

const stamp = `e2e-cmtco-${Date.now().toString(36)}`;

test('CO comment lines: zero-charge add, comment-mode edit gesture, comment replace as annotated removal through acceptance', async ({ page }) => {
  const api = await apiAs(personas.finjobs);

  const contact = (await api.get('/api/contacts/?page_size=1')).results[0];
  const schemes = await api.get('/api/rate-schemes/?page_size=100');
  const scheme = (schemes.results || schemes)
    .find((s) => s.algorithm === 'entered_qty' && s.is_active !== false);
  test.skip(!scheme, 'seed gap: no active entered_qty rate scheme');

  // Accepted-estimate job with ONE claimed task line, then held with a
  // draft CO — the standard amend-in-place backdrop.
  const job = await api.post('/api/jobs/', { name: `${stamp} job`, contact: contact.contact_id });
  const task = await api.post(`/api/jobs/${job.job_id}/tasks/`, {
    name: `${stamp} claimed work`, rate_scheme: scheme.rate_scheme_id, est_qty: '2',
  });
  const estimate = await api.post('/api/estimates/', { job: job.job_id });
  const taskLine = await api.post(`/api/estimates/${estimate.estimate_id}/line-items-from-atoms/`, {
    atoms: [{ type: 'task', id: task.task_id }],
  });
  await api.post(`/api/jobs/${job.job_id}/deliverables/`, {
    description: `${stamp} deliverable`, qty_ordered: '1', units: 'ea',
  });
  await api.patch(`/api/estimates/${estimate.estimate_id}/`, { status: 'open' });
  await api.patch(`/api/estimates/${estimate.estimate_id}/`, { status: 'accepted' });
  expect((await api.get(`/api/jobs/${job.job_id}/`)).status).toBe('in_progress');

  await api.post(`/api/jobs/${job.job_id}/hold/`, { reason: 'e2e: comment-line CO' });
  const co = await api.post('/api/change-orders/', { job: job.job_id });
  expect(co.status).toBe('draft');

  const apiBase = `/api/change-orders/${co.change_order_id}`;
  const amended = () => api.get(`${apiBase}/amended-agreement/`);

  const commentAddDesc = `${stamp} FYI customer prefers morning delivery`;
  const commentReplaceDesc = `${stamp} cancelled - see note`;

  const editTable = page.locator('table.co-edit-table');
  const plainRow = (desc) =>
    editTable.locator('tbody > tr:not(.co-authored):not(.co-struck-original):not(.doc-atom-row)').filter({ hasText: desc });
  const struckRow = (desc) => editTable.locator('tr.co-struck-original').filter({ hasText: desc });
  const authoredRow = (desc) => editTable.locator('tr.co-authored').filter({ hasText: desc });

  let baseline; // amended payload before any comment gesture

  await test.step('Comment ADD via Add line → "Comment (no charge)": tinted CO row, amended total unchanged', async () => {
    baseline = await amended();
    expect(Number(baseline.original_total)).toBeGreaterThan(0); // anchor: a real agreement to amend
    const agreementRow = baseline.rows.find(
      (r) => r.kind === 'agreement' && r.line.estimate_line_id === taskLine.line_item_id);
    expect(agreementRow.sources.length).toBe(1); // anchor: the line really carries the task claim

    await page.goto(`/#/jobs/${job.job_id}/change-order/${co.change_order_id}`);
    await expect(plainRow(taskLine.description)).toBeVisible(); // anchor: table loaded

    await page.getByRole('button', { name: 'Add line' }).click();
    const picker = page.getByRole('dialog');
    await picker.getByPlaceholder(/search/i).fill(commentAddDesc);
    await picker.getByRole('checkbox', { name: 'Comment (no charge)' }).check();
    await picker.getByRole('button', { name: 'Add Line', exact: true }).click();

    const form = page.getByRole('dialog');
    await expect(form.getByRole('heading', { name: 'Add Comment' })).toBeVisible();
    await expect(form.getByLabel('Description')).toHaveValue(commentAddDesc); // anchor
    await expect(form.getByLabel(/Accounting Category/)).toHaveCount(0);
    await expect(form.getByLabel(/Quantity/)).toHaveCount(0);
    await expect(form.getByLabel(/^Price/)).toHaveCount(0);
    await form.getByRole('button', { name: 'Add', exact: true }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);

    const added = authoredRow(commentAddDesc);
    await expect(added).toBeVisible();
    await expect(added.locator('.co-badge')).toBeVisible();

    const after = await amended();
    const addedRow = after.rows.find(
      (r) => r.kind === 'added' && r.line.description === commentAddDesc);
    expect(addedRow).toBeTruthy();
    expect(Number(addedRow.line.amount)).toBe(0);
    // The informational row moved the money by exactly nothing.
    expect(Number(after.revised_total)).toBe(Number(baseline.revised_total));
    expect(Number(after.co_delta)).toBe(0);
  });

  await test.step('Edit on the comment row reopens the modal in comment mode (b7880c56)', async () => {
    await authoredRow(commentAddDesc).getByRole('button', { name: 'Edit' }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toContainText('Edit Line');
    // Anchor: the description field is populated — this is the comment
    // line's own edit, not a blank form.
    await expect(dialog.getByLabel('Description')).toHaveValue(commentAddDesc);
    await expect(dialog.getByRole('checkbox', { name: /Comment line/ })).toBeChecked();
    await expect(dialog.getByLabel(/Quantity/)).toHaveCount(0);
    await expect(dialog.getByLabel(/^Price/)).toHaveCount(0);
    await expect(dialog.getByLabel(/Accounting Category/)).toHaveCount(0);
    await dialog.getByRole('button', { name: 'Cancel' }).click();
    await expect(dialog).toBeHidden();
  });

  await test.step('Replace… on the claimed line, marked as comment: fields collapse, the original strikes for $0', async () => {
    await plainRow(taskLine.description).getByRole('button', { name: /Replace/ }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toContainText('Replace Line');
    // Anchor: the replace modal opens prefilled from the current line —
    // the money fields are really there before the checkbox collapses them.
    expect(Number(await dialog.getByLabel(/Quantity/).inputValue())).toBe(Number(taskLine.qty));
    await dialog.getByRole('checkbox', { name: /Comment line/ }).check();
    await expect(dialog.getByLabel(/Quantity/)).toHaveCount(0);
    await expect(dialog.getByLabel(/^Price/)).toHaveCount(0);
    await dialog.getByLabel('Description').fill(commentReplaceDesc);
    await dialog.getByRole('button', { name: 'Save' }).click();
    await expect(dialog).toBeHidden();

    await expect(authoredRow(commentReplaceDesc)).toBeVisible();
    await expect(struckRow(taskLine.description)).toBeVisible();

    const after = await amended();
    const replacedRow = after.rows.find(
      (r) => r.kind === 'replaced' && r.original.estimate_line_id === taskLine.line_item_id);
    expect(replacedRow).toBeTruthy();
    expect(Number(replacedRow.line.amount)).toBe(0);
    // Only line replaced by a comment + a comment add → nothing left to bill.
    expect(Number(after.revised_total)).toBe(0);
    expect(Number(after.co_delta)).toBe(-Number(after.original_total));
  });

  await test.step('Acceptance: target drops from the agreement, its task is descoped/cancelled, the comment holds zero claims', async () => {
    // Anchor before the absence assertions: the agreement DID contain the
    // line while the CO was still draft (draft COs never apply).
    const agreementBefore = await api.get(`/api/jobs/${job.job_id}/agreement/`);
    expect(agreementBefore.lines.map((l) => l.description)).toContain(taskLine.description);

    await api.patch(apiBase + '/', { status: 'open' });
    await api.patch(apiBase + '/', { status: 'accepted' });

    // Acceptance side effects ran: the hold cleared.
    await expect.poll(async () => (await api.get(`/api/jobs/${job.job_id}/`)).on_hold).toBe(false);

    // Target gone from the agreement — and the comment never entered it.
    const agreementAfter = await api.get(`/api/jobs/${job.job_id}/agreement/`);
    expect(agreementAfter.lines).toHaveLength(0);
    expect(Number(agreementAfter.grand_total)).toBe(0);

    // The claimed task was retired as a descope, not orphaned.
    const freshTask = await api.get(`/api/tasks/${task.task_id}/`);
    expect(freshTask.status).toBe('cancelled');

    // No claims moved onto the comment replace line (backing inheritance
    // is skipped for a comment-marked replace): a fresh invoice seeds
    // EMPTY (nothing left on the agreement to bill), and the retired task
    // surfaces in Unbilled work flagged "cancelled — work done" (the
    // cancelled-task prompt supersedes the descoped-by badge server-side)
    // — NOT as billable actuals riding the comment. (The amended-agreement
    // endpoint's `sources` on a replaced row are display-context — they
    // fall back to the target's own rows — so claim ownership is asserted
    // through the invoice surface instead.)
    const afterAccept = await amended();
    const replacedRow = afterAccept.rows.find(
      (r) => r.kind === 'replaced' && r.original.estimate_line_id === taskLine.line_item_id);
    expect(replacedRow).toBeTruthy(); // anchor: the record view still shows the amendment

    const invoice = await api.post('/api/invoices/', { job: job.job_id });
    expect((invoice.line_items || []).length).toBe(0);

    await page.goto(`/#/jobs/${job.job_id}/invoice/${invoice.invoice_id}`);
    await expect(page.getByRole('heading', { name: 'Unbilled work' })).toBeVisible(); // anchor
    const descopedRow = page.locator('.uncovered-work-section tr').filter({ hasText: task.name });
    await expect(descopedRow.getByText('cancelled — work done')).toBeVisible();
    // And the comment text never reached the invoice surface at all.
    await expect(page.locator('table.line-items-table').getByText(commentReplaceDesc)).toHaveCount(0);
  });

  await api.dispose();
});

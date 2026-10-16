// The Pipeline column groups its cards into ordered sections — Inquiries (no
// estimate), Estimating (draft estimate), Awaiting Approval (sent estimate),
// Awaiting Prep (accepted; job approved) — each under a small header tinted
// like the cards' tab (RM, feature/pipeline 2026-10-11). Each card's section
// is computed server-side and carried on the payload as `section`
// (feature/unpaid 2026-10-14), so the expected layout is read straight off
// the board payload and holds whatever mix the seed (plus earlier specs)
// leaves in the pipeline.
import { expect, test } from '@playwright/test';
import { apiAs } from '../../fixtures/api.js';
import { personas } from '../../fixtures/personas.js';

const SECTIONS = [
  { key: 'needs-scoping',     label: 'Inquiries' },
  { key: 'estimating',        label: 'Estimating' },
  { key: 'awaiting-response', label: 'Awaiting Approval' },
  { key: 'awaiting-prep',     label: 'Awaiting Prep' },
];

test.use({ storageState: personas.worker.storageState });

test('pipeline cards sit under ordered, colored section headers', async ({ page }) => {
  const api = await apiAs(personas.worker);
  const { jobs } = await api.get('/api/jobs/board/pipeline/');
  await api.dispose();
  test.skip(jobs.length === 0, 'seed gap: no pipeline jobs');

  // Every payload row carries a section the column knows.
  for (const j of jobs) expect(SECTIONS.map((s) => s.key)).toContain(j.section);

  const expected = [];
  for (const section of SECTIONS) {
    const members = jobs.filter((j) => j.section === section.key);
    if (members.length === 0) continue;
    expected.push(section.label.toUpperCase());
    for (const j of members) expected.push(j.job_number);
  }

  // The board opens on In Progress; Pipeline is a collapsed tab until clicked.
  await page.goto('/#/jobs/board');
  await page.getByRole('button', { name: 'Pipeline' }).click();
  const body = page.locator('.column-body');
  await expect(body.locator('.section-label').first()).toBeVisible();

  // Headers and card numbers in DOM order, as one flat list. Labels render
  // uppercase via CSS, so compare on innerText (which applies text-transform).
  const flow = await body.locator('.section-label, .border-num').allInnerTexts();
  expect(flow.map((t) => t.trim())).toEqual(expected);

  // Each header carries its cards' tab color as a custom property.
  const colors = await body.locator('.section-divider').evaluateAll((els) =>
    els.map((el) => el.style.getPropertyValue('--section-color').trim()));
  const present = SECTIONS.filter((s) => expected.includes(s.label.toUpperCase()));
  const tabColors = { 'needs-scoping': '#64748b', 'estimating': '#2563eb', 'awaiting-response': '#b45309', 'awaiting-prep': '#ca8a04' };
  expect(colors).toEqual(present.map((s) => tabColors[s.key]));
});

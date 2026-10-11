// The Pipeline column groups its cards by sub-status into ordered sections —
// Inquiries (no estimate), Estimating (draft estimate), Awaiting Approval
// (sent estimate), Awaiting Prep (accepted; job approved) — each under a
// small header tinted like the cards' tab (RM, feature/pipeline 2026-10-11).
// The expected layout is derived from the board payload itself so the spec
// holds whatever mix the seed (plus earlier specs) leaves in the pipeline.
import { expect, test } from '@playwright/test';
import { apiAs } from '../../fixtures/api.js';
import { personas } from '../../fixtures/personas.js';

const SECTIONS = [
  { key: 'needs-scoping',     label: 'Inquiries' },
  { key: 'estimating',        label: 'Estimating' },
  { key: 'awaiting-response', label: 'Awaiting Approval' },
  { key: 'awaiting-prep',     label: 'Awaiting Prep' },
];

// Mirror of PipelineColumn.sectionKey: a held job's sub_status is 'on-hold',
// so it is bucketed by its estimates the way the backend would unheld.
function sectionKey(job) {
  if (job.status === 'approved') return 'awaiting-prep';
  if (SECTIONS.some((s) => s.key === job.sub_status)) return job.sub_status;
  const estimates = job.estimates || [];
  if (estimates.some((e) => e.status === 'open')) return 'awaiting-response';
  if (estimates.some((e) => e.status === 'draft')) return 'estimating';
  return 'needs-scoping';
}

test.use({ storageState: personas.worker.storageState });

test('pipeline cards sit under ordered, colored section headers', async ({ page }) => {
  const api = await apiAs(personas.worker);
  const { jobs } = await api.get('/api/jobs/board/pipeline/');
  await api.dispose();
  test.skip(jobs.length === 0, 'seed gap: no pipeline jobs');

  const expected = [];
  for (const section of SECTIONS) {
    const members = jobs.filter((j) => sectionKey(j) === section.key);
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

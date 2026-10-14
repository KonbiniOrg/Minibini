// The Unpaid column groups its cards into ordered sections — Needs Invoice
// (work done, real bill not started), Invoice Drafted (draft, unsent),
// Awaiting Payment (sent, still owed), Needs Pickup (paid, customer hasn't
// collected) — each under a small header tinted like the cards' tab (RM,
// feature/unpaid 2026-10-13/14). Each card's section is computed server-side
// (BoardService.unpaid_section — it needs deliverable fulfillment and
// deposit-ness the card payload doesn't carry) and arrives as `section`, so
// the expected layout is read straight off the board payload and holds
// whatever mix the seed (plus earlier specs) leaves in the lane.
import { expect, test } from '@playwright/test';
import { apiAs } from '../../fixtures/api.js';
import { personas } from '../../fixtures/personas.js';

const SECTIONS = [
  { key: 'needs-invoice',   label: 'Needs Invoice',    color: '#64748b' },
  { key: 'invoice-prepped', label: 'Invoice Drafted',  color: '#f59e0b' },
  { key: 'invoice-sent',    label: 'Awaiting Payment', color: '#3b82f6' },
  { key: 'needs-pickup',    label: 'Needs Pickup',     color: '#7c3aed' },
];

test.use({ storageState: personas.worker.storageState });

test('unpaid cards sit under ordered, colored section headers', async ({ page }) => {
  const api = await apiAs(personas.worker);
  const { jobs } = await api.get('/api/jobs/board/unpaid/');
  await api.dispose();
  test.skip(jobs.length === 0, 'seed gap: no unpaid jobs');

  // Every payload row carries a section the column knows.
  for (const j of jobs) expect(SECTIONS.map((s) => s.key)).toContain(j.section);

  const expected = [];
  const present = [];
  for (const section of SECTIONS) {
    const members = jobs.filter((j) => j.section === section.key);
    if (members.length === 0) continue;
    present.push(section);
    expected.push(section.label.toUpperCase());
    for (const j of members) expected.push(j.job_number);
  }

  // The board opens on In Progress; Unpaid is a collapsed tab until clicked.
  await page.goto('/#/jobs/board');
  await page.getByRole('button', { name: 'Unpaid' }).click();
  const body = page.locator('.column-body');
  await expect(body.locator('.section-label').first()).toBeVisible();

  // Headers and card numbers in DOM order, as one flat list. Labels render
  // uppercase via CSS, so compare on innerText (which applies text-transform).
  const flow = await body.locator('.section-label, .border-num').allInnerTexts();
  expect(flow.map((t) => t.trim())).toEqual(expected);

  // Each header carries its cards' tab color as a custom property, and every
  // card's tab is painted that same color.
  const colors = await body.locator('.section-divider').evaluateAll((els) =>
    els.map((el) => el.style.getPropertyValue('--section-color').trim()));
  expect(colors).toEqual(present.map((s) => s.color));

  // A card for a job that isn't work_complete (an active job with a progress
  // invoice, a cancelled job with a receivable) wears a status badge; a
  // work_complete card wears none.
  const badged = jobs.filter((j) => j.status !== 'work_complete');
  await expect(body.locator('.status-badge')).toHaveCount(badged.length);

  // Needs Pickup cards footer "Awaiting pickup" rather than an amount due.
  const pickup = jobs.filter((j) => j.section === 'needs-pickup');
  await expect(body.locator('.total.pickup')).toHaveCount(pickup.length);
});

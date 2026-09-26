// bundling-in-task-view (.superpowers/sdd/2026-09-19-bundling-in-task-view-plan)
// Task 6 — shared helpers for the "select atoms on the Tasks page, then open
// BundleModal" gesture that four+ specs drive (per-unit-lines/plan-first,
// per-unit-lines/split-materials, invoice-skeleton/estimate-three-modes,
// estimating-structure/mint-and-release). Composing a new estimate/CO line
// from job atoms now happens exclusively on the Tasks page (Tasks 2-4): each
// unclaimed task/material row on `#/jobs/{id}/tasks` carries a bundle-select
// checkbox (TaskRow/MaterialRow, aria-label "Select {name} for bundling"),
// and the toolbar's "Bundle N selected into a line…" button opens the
// (unchanged) BundleModal. Callers still drive the modal's own fields
// themselves afterward — only navigation + selection + opening it is shared
// here, since the modal's internals differ per journey.
//
// NOTE: as of the Tasks-page CO lens (RM 2026-09-20), this ALSO covers
// bundling into a job's draft change order — same checkboxes/CTA/modal, just
// targeting `/api/change-orders/{id}` instead of `/api/estimates/{id}` once
// a held job has a draft CO (see specs/task-view-bundling/co-lens.spec.js).
// The change-order page's own former "Uncovered work" pool picker was
// retired (c413c4f3) in favor of this single Tasks-page composition surface.
import { expect } from '@playwright/test';

export async function gotoTasksPage(page, jobId) {
  await page.goto(`/#/jobs/${jobId}/tasks`);
}

// The single task-tree table on the Tasks page (bundleMode adds a leading
// checkbox column to it) — scoping here mirrors the old pool-locator
// convention (`.uncovered-work-section`) so a name match can't accidentally
// hit an unrelated row elsewhere on the page.
export function taskTreeRow(page, name) {
  return page.locator('table.task-tree-table tbody tr').filter({ hasText: name });
}

// Check the bundle-selection checkbox for one named task/material row.
export async function checkBundleRow(page, name) {
  await taskTreeRow(page, name).locator('input[type="checkbox"]').check();
}

// Click the toolbar's "Bundle N selected into a line…" CTA (n = the live
// selection count) and return the opened BundleModal, already asserted
// visible with its heading text.
export async function openBundleModal(page, n) {
  await page.getByRole('button', { name: `Bundle ${n} selected into a line…` }).click();
  const modal = page.getByRole('dialog');
  await expect(modal).toContainText('Bundle into line');
  return modal;
}

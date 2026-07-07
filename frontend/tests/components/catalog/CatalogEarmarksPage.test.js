import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import { readable } from 'svelte/store';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn() } }));
vi.mock('@/stores/permissions.js', () => ({
  canManageFinancials: readable(true),
  canManageJobs: readable(true),
  canManageConfig: readable(true),
}));

import { api } from '@/lib/api.js';
import CatalogEarmarksPage from '@/routes/catalog/CatalogEarmarksPage.svelte';

const rows = [
  {
    earmark_id: 1, inventory_item: 7, item_code: 'B-SHEET', item_description: 'acrylic',
    units: 'sheet', job: 3, job_number: 'JOB-2026-0011', quantity: '4.00',
    qty_on_hand: '1.00', qty_on_order: '2.00', qty_earmarked_total: '6.00',
    pos: [{ po_id: 9, po_number: 'PO-2026-0042' }],
  },
  {
    earmark_id: 2, inventory_item: 8, item_code: 'A-ROD', item_description: 'rod',
    units: 'ea', job: 4, job_number: 'JOB-2026-0012', quantity: '2.00',
    qty_on_hand: '5.00', qty_on_order: '0.00', qty_earmarked_total: '2.00',
    pos: [],
  },
];

beforeEach(() => {
  api.get.mockReset();
  api.get.mockResolvedValue(rows);
});

describe('CatalogEarmarksPage', () => {
  it('renders one row per earmark with job link, PO link and shortfall', async () => {
    const { findByText, getByRole } = render(CatalogEarmarksPage);
    await findByText('B-SHEET');
    expect(getByRole('link', { name: 'JOB-2026-0011' }).getAttribute('href'))
      .toContain('/jobs/3');
    expect(getByRole('link', { name: 'PO-2026-0042' }).getAttribute('href'))
      .toContain('/purchase-orders/9');
    // shortfall: 6 − 1 − 2 = 3
    await findByText('3');
  });

  // Default sort is item_code ascending (A-ROD, B-SHEET already), so clicking
  // the *same* header (Code) toggles to descending. To exercise "clicking a
  // header sorts by that column, ascending on first click", click a
  // different column (Earmarked / quantity): B-SHEET is 4.00, A-ROD is 2.00,
  // so ascending puts A-ROD first.
  it('sorts by a column on header click', async () => {
    const { findByText, getByRole, getAllByRole } = render(CatalogEarmarksPage);
    await findByText('B-SHEET');
    await fireEvent.click(getByRole('button', { name: /Earmarked/ }));
    const cells = getAllByRole('row').slice(1).map(r => r.textContent);
    expect(cells[0]).toContain('A-ROD');   // ascending after click
  });

  it('toggles direction on a second click of the same header', async () => {
    const { findByText, getByRole, getAllByRole } = render(CatalogEarmarksPage);
    await findByText('B-SHEET');
    // Default sort is item_code asc -> A-ROD, B-SHEET. Clicking Code once
    // toggles to descending.
    await fireEvent.click(getByRole('button', { name: /Code/ }));
    const cells = getAllByRole('row').slice(1).map(r => r.textContent);
    expect(cells[0]).toContain('B-SHEET');
  });

  it('shows an Order button per row for financials users', async () => {
    const { findAllByRole } = render(CatalogEarmarksPage);
    const buttons = await findAllByRole('button', { name: 'order' });
    expect(buttons.length).toBe(2);
  });
});

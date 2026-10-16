import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from '@testing-library/svelte';
import { readable } from 'svelte/store';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn() }, errorMessage: (e, fallback) => e?.message || fallback }));
vi.mock('@/stores/permissions.js', () => ({
  canManageFinancials: readable(false),
  canManageJobs: readable(false),
  canManageConfig: readable(false),
}));

import { api } from '@/lib/api.js';
import { viewMode } from '@/stores/viewMode.js';
import CatalogEarmarksPage from '@/routes/catalog/CatalogEarmarksPage.svelte';

const rows = [{
  earmark_id: 1, inventory_item: 7, item_code: 'B-SHEET', item_description: 'acrylic',
  units: 'sheet', job: 3, job_number: 'JOB-2026-0011', quantity: '4.00',
  qty_on_hand: '1.00', qty_on_order: '2.00', qty_earmarked_total: '6.00', pos: [],
}];

beforeEach(() => {
  api.get.mockReset();
  api.get.mockResolvedValue(rows);
});

describe('CatalogEarmarksPage — permission gating is applied before density', () => {
  it('a worker in full density gets no Actions column and no order button', async () => {
    viewMode.set('full');
    const { findByText, container, queryByRole } = render(CatalogEarmarksPage);
    await findByText('B-SHEET');
    const headers = Array.from(container.querySelectorAll('thead th')).map((th) => th.textContent.trim());
    expect(headers).toEqual(['Code', 'Description', 'Units', 'Job', 'Earmarked', 'On hand', 'On order', 'Shortfall', 'POs']);
    expect(container.querySelector('td[data-col="actions"]')).toBeNull();
    expect(queryByRole('button', { name: 'order' })).toBeNull();
  });
});

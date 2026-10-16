import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));
vi.mock('svelte-spa-router', () => ({ push: vi.fn() }));
const perms = vi.hoisted(() => ({ financials: true, jobs: false }));
vi.mock('@/stores/permissions.js', () => ({
  canManageFinancials: { subscribe: (fn) => { fn(perms.financials); return () => {}; } },
  canManageJobs: { subscribe: (fn) => { fn(perms.jobs); return () => {}; } },
}));

import { api } from '@/lib/api.js';
import PurchaseOrderListPage from '@/routes/purchaseorders/PurchaseOrderListPage.svelte';

beforeEach(() => {
  perms.financials = true;
  perms.jobs = false;
  api.get.mockReset();
  api.get.mockResolvedValue({ count: 0, results: [], next: null, previous: null });
});

describe('PurchaseOrderListPage — awaiting-reconciliation filter', () => {
  it('wires the checkbox to the ?awaiting_reconciliation=true query param', async () => {
    const { getByLabelText } = render(PurchaseOrderListPage);
    await vi.waitFor(() => expect(api.get).toHaveBeenCalled());
    api.get.mockClear();

    await fireEvent.click(getByLabelText('Awaiting reconciliation only'));

    await vi.waitFor(() => expect(api.get).toHaveBeenCalled());
    const url = api.get.mock.calls[0][0];
    expect(url).toContain('awaiting_reconciliation=true');
  });

  it('omits the param when the checkbox is off', async () => {
    render(PurchaseOrderListPage);
    await vi.waitFor(() => expect(api.get).toHaveBeenCalled());
    const url = api.get.mock.calls[0][0];
    expect(url).not.toContain('awaiting_reconciliation');
  });
});

describe('PurchaseOrderListPage — New Purchase Order gate', () => {
  it('shows the link to a jobs-only user', () => {
    perms.financials = false;
    perms.jobs = true;
    const { getByText } = render(PurchaseOrderListPage);
    expect(getByText('New Purchase Order')).toBeInTheDocument();
  });

  it('hides the link when neither atom is held', () => {
    perms.financials = false;
    perms.jobs = false;
    const { queryByText } = render(PurchaseOrderListPage);
    expect(queryByText('New Purchase Order')).toBeNull();
  });
});

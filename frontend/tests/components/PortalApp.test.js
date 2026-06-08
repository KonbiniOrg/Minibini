import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn() } }));

import { api } from '@/lib/api.js';
import PortalApp from '@/PortalApp.svelte';

// PortalApp reads ?token=... from window.location at construction, so the URL
// must carry a token before render() or it short-circuits to "Missing link token."
function estimate(actions) {
  return {
    estimate_number: 'EST-2026-0001',
    status: 'open',
    actions,
    deliverables: [],
    line_items: [{ description: 'Widget', qty: 1, units: 'ea', price: '10', amount: '10' }],
    grand_total: '10',
  };
}

describe('PortalApp', () => {
  beforeEach(() => {
    api.get.mockReset();
    window.history.replaceState(null, '', '/?token=tok123');
  });

  it('hides the action buttons when the estimate is not actionable (actions empty)', async () => {
    api.get.mockResolvedValue(estimate([]));
    const { findByText, queryByRole } = render(PortalApp);
    await findByText('Estimate EST-2026-0001');
    expect(queryByRole('button', { name: 'Accept estimate' })).toBeNull();
    expect(queryByRole('button', { name: 'Request changes' })).toBeNull();
    expect(queryByRole('button', { name: 'Decline estimate' })).toBeNull();
  });

  it('shows the action buttons when the estimate is actionable', async () => {
    api.get.mockResolvedValue(estimate(['accept', 'request_changes', 'reject']));
    const { findByRole } = render(PortalApp);
    expect(await findByRole('button', { name: 'Accept estimate' })).toBeInTheDocument();
    expect(await findByRole('button', { name: 'Request changes' })).toBeInTheDocument();
    expect(await findByRole('button', { name: 'Decline estimate' })).toBeInTheDocument();
  });

  it('routes a change-order link (doc=change_order) to the change order view', async () => {
    window.history.replaceState(null, '', '/?token=tok123&doc=change_order');
    api.get.mockResolvedValue({
      change_order_number: 'EST-1-CO1',
      status: 'open',
      actions: [],
      deliverables: [],
      line_rows: [],
      prior_total: '0.00', proposed_total: '0.00', diff_total: '0.00',
    });
    const { findByText } = render(PortalApp);
    await findByText('Change order EST-1-CO1');
    // It hit the CO portal endpoint, not the estimate one.
    expect(api.get).toHaveBeenCalledWith(
      expect.stringContaining('/api/portal/change-orders/'));
  });
});

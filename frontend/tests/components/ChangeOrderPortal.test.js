import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn() } }));

import { api } from '@/lib/api.js';
import ChangeOrderPortal from '@/ChangeOrderPortal.svelte';

function payload(actions, overrides = {}) {
  return {
    change_order_number: 'EST-2026-0001-1-CO1',
    status: 'open',
    actions,
    deliverables: [
      { kind: 'added', description: 'New panel', qty: '1', units: 'ea' },
    ],
    line_rows: [
      { kind: 'unchanged', line_number: 1, description: 'Base', qty: '1', units: 'ea', price: '100.00', amount: '100.00' },
      { kind: 'added', line_number: 1, description: 'Extra', qty: '1', units: 'ea', price: '250.00', amount: '250.00' },
    ],
    prior_total: '100.00',
    proposed_total: '350.00',
    diff_total: '250.00',
    ...overrides,
  };
}

describe('ChangeOrderPortal', () => {
  beforeEach(() => {
    api.get.mockReset();
    api.post.mockReset();
    window.history.replaceState(null, '', '/?token=tok123&doc=change_order');
  });

  it('renders the line-item diff rows and totals', async () => {
    api.get.mockResolvedValue(payload([]));
    const { findByText, getByText } = render(ChangeOrderPortal);
    await findByText('Change order EST-2026-0001-1-CO1');
    expect(getByText('Base')).toBeInTheDocument();
    expect(getByText('Extra')).toBeInTheDocument();
    expect(getByText('+$250.00')).toBeInTheDocument();
  });

  it('hides the action buttons when not actionable', async () => {
    api.get.mockResolvedValue(payload([]));
    const { findByText, queryByRole } = render(ChangeOrderPortal);
    await findByText('Change order EST-2026-0001-1-CO1');
    expect(queryByRole('button', { name: 'Approve change' })).toBeNull();
    expect(queryByRole('button', { name: 'Decline change' })).toBeNull();
  });

  it('shows the action buttons when actionable', async () => {
    api.get.mockResolvedValue(payload(['accept', 'request_changes', 'reject']));
    const { findByRole } = render(ChangeOrderPortal);
    expect(await findByRole('button', { name: 'Approve change' })).toBeInTheDocument();
    expect(await findByRole('button', { name: 'Request changes' })).toBeInTheDocument();
    expect(await findByRole('button', { name: 'Decline change' })).toBeInTheDocument();
  });

  it('posts to the accept endpoint on approval', async () => {
    api.get.mockResolvedValue(payload(['accept', 'request_changes', 'reject']));
    api.post.mockResolvedValue(payload([], { status: 'accepted' }));
    const { findByRole, getByRole } = render(ChangeOrderPortal);
    await fireEvent.click(await findByRole('button', { name: 'Approve change' }));
    await fireEvent.click(getByRole('button', { name: 'Yes, approve' }));
    expect(api.post).toHaveBeenCalledWith(
      expect.stringContaining('/api/portal/change-orders/tok123/accept/'), null);
  });

  it('renders the superseded banner with a forward link', async () => {
    api.get.mockResolvedValue(payload([], {
      status: 'superseded', current_token: 'newtok',
    }));
    const { findByText, getByRole } = render(ChangeOrderPortal);
    await findByText(/newer version of this change order/i);
    const link = getByRole('link', { name: /current change order/i });
    expect(link.getAttribute('href')).toContain('token=newtok');
    expect(link.getAttribute('href')).toContain('doc=change_order');
  });
});

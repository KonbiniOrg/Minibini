import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn() } }));

import { api } from '@/lib/api.js';
import EstimatePortal from '@/EstimatePortal.svelte';

// EstimatePortal (like ChangeOrderPortal) renders through the shared
// PortalDocument wrapper — these tests cover the wrapper's load/confirm/
// submit machine through a real consumer.
function payload(actions, overrides = {}) {
  return {
    estimate_number: 'EST-2026-0001',
    status: 'open',
    actions,
    deliverables: [
      { description: 'Cut panels', qty_ordered: '4', units: 'ea' },
    ],
    line_items: [
      { description: 'CNC time', qty: '2', units: 'hr', price: '100.00', amount: '200.00' },
    ],
    grand_total: '200.00',
    ...overrides,
  };
}

describe('EstimatePortal', () => {
  beforeEach(() => {
    api.get.mockReset();
    api.post.mockReset();
    window.history.replaceState(null, '', '/?token=tok123&doc=estimate');
  });

  it('renders the line items and total', async () => {
    api.get.mockResolvedValue(payload([]));
    const { findByText, getByText, getAllByText } = render(EstimatePortal);
    await findByText('Estimate EST-2026-0001');
    expect(getByText('CNC time')).toBeInTheDocument();
    // Once in the line row, once in the grand-total row.
    expect(getAllByText('$200.00')).toHaveLength(2);
  });

  it('shows the not-available message on 404', async () => {
    api.get.mockRejectedValue(Object.assign(new Error('nope'), { status: 404 }));
    const { findByText } = render(EstimatePortal);
    expect(await findByText('This estimate is not available.')).toBeInTheDocument();
  });

  it('hides the action buttons when not actionable', async () => {
    api.get.mockResolvedValue(payload([]));
    const { findByText, queryByRole } = render(EstimatePortal);
    await findByText('Estimate EST-2026-0001');
    expect(queryByRole('button', { name: 'Accept estimate' })).toBeNull();
    expect(queryByRole('button', { name: 'Decline estimate' })).toBeNull();
  });

  it('posts to the accept endpoint on confirmed acceptance', async () => {
    api.get.mockResolvedValue(payload(['accept', 'request_changes', 'reject']));
    api.post.mockResolvedValue(payload([], { status: 'accepted' }));
    const { findByRole, getByRole, findByText } = render(EstimatePortal);
    await fireEvent.click(await findByRole('button', { name: 'Accept estimate' }));
    await fireEvent.click(getByRole('button', { name: 'Yes, accept' }));
    expect(api.post).toHaveBeenCalledWith(
      expect.stringContaining('/api/portal/estimates/tok123/accept/'), null);
    expect(await findByText(/You accepted this estimate/)).toBeInTheDocument();
  });

  it('posts the typed reason on decline', async () => {
    api.get.mockResolvedValue(payload(['accept', 'request_changes', 'reject']));
    api.post.mockResolvedValue(payload([], { status: 'rejected' }));
    const { findByRole, getByRole, getByLabelText } = render(EstimatePortal);
    await fireEvent.click(await findByRole('button', { name: 'Decline estimate' }));
    await fireEvent.input(getByLabelText(/Reason \(optional\)/), {
      target: { value: 'Too expensive' },
    });
    await fireEvent.click(getByRole('button', { name: 'Yes, decline' }));
    expect(api.post).toHaveBeenCalledWith(
      expect.stringContaining('/api/portal/estimates/tok123/reject/'),
      { reason: 'Too expensive' });
  });

  it('posts the typed comment on request changes and thanks the customer', async () => {
    api.get.mockResolvedValue(payload(['accept', 'request_changes', 'reject']));
    api.post.mockResolvedValue(payload([]));
    const { findByRole, getByRole, getByLabelText, findByText } = render(EstimatePortal);
    await fireEvent.click(await findByRole('button', { name: 'Request changes' }));
    await fireEvent.input(getByLabelText(/What would you like changed\?/), {
      target: { value: 'Use walnut instead' },
    });
    await fireEvent.click(getByRole('button', { name: 'Send request' }));
    expect(api.post).toHaveBeenCalledWith(
      expect.stringContaining('/api/portal/estimates/tok123/request-changes/'),
      { reason: 'Use walnut instead' });
    expect(await findByText(/we've received your request/)).toBeInTheDocument();
  });

  it('renders the superseded banner with a forward link', async () => {
    api.get.mockResolvedValue(payload([], {
      status: 'superseded', current_token: 'newtok',
    }));
    const { findByText, getByRole } = render(EstimatePortal);
    await findByText(/newer version of this estimate/i);
    const link = getByRole('link', { name: /current estimate/i });
    expect(link.getAttribute('href')).toContain('token=newtok');
    expect(link.getAttribute('href')).toContain('doc=estimate');
  });
});

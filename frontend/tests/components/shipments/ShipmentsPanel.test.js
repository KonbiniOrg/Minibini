import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

import { api } from '@/lib/api.js';
import ShipmentsPanel from '@/components/shipments/ShipmentsPanel.svelte';

const job = { job_id: 3, job_number: 'JOB-3', name: 'Widget' };

function mockApi({ deliverables = [], shipments = [] } = {}) {
  api.get.mockImplementation((url) => {
    if (url.includes('/deliverables/')) return Promise.resolve(deliverables);
    if (url.includes('/shipments/')) return Promise.resolve(shipments);
    return Promise.resolve(null);
  });
}

beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();
  api.patch.mockReset();
  api.delete.mockReset();
  api.post.mockResolvedValue({});
  api.patch.mockResolvedValue({});
  api.delete.mockResolvedValue({});
});

describe('ShipmentsPanel', () => {
  it('shows loading, then the no-deliverables message', async () => {
    mockApi({ deliverables: [] });
    const { getByText, findByText } = render(ShipmentsPanel, { props: { job } });
    expect(getByText('Loading...')).toBeInTheDocument();
    expect(await findByText('This job has no deliverables yet.')).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith('/api/jobs/3/deliverables/');
    expect(api.get).toHaveBeenCalledWith('/api/shipments/?job=3');
  });

  it('shows the no-shipments message when deliverables exist but no shipments', async () => {
    mockApi({ deliverables: [{ id: 1, description: 'Widget', qty_ordered: '5', qty_remaining: '5', units: 'ea' }] });
    const { findByText } = render(ShipmentsPanel, { props: { job } });
    expect(await findByText('No shipments yet. Click "+ Add shipment" to create one.')).toBeInTheDocument();
  });

  it('renders the matrix with a persisted shipment', async () => {
    mockApi({
      deliverables: [{ id: 1, description: 'Widget', qty_ordered: '5', qty_remaining: '5', units: 'ea' }],
      shipments: [{ id: 10, sequence: 1, status: 'prepared', prepared_date: '2026-07-01T00:00:00Z', items: [] }],
    });
    const { findByText, getByText } = render(ShipmentsPanel, { props: { job } });
    expect(await findByText('Widget')).toBeInTheDocument();
    expect(getByText(/Shipment #1/)).toBeInTheDocument();
  });

  it('adding a shipment creates a local draft column prefilled with remaining qty', async () => {
    mockApi({
      deliverables: [{ id: 1, description: 'Widget', qty_ordered: '5', qty_remaining: '5', units: 'ea' }],
    });
    const { findByText, getByRole, getByDisplayValue } = render(ShipmentsPanel, { props: { job } });
    await findByText('No shipments yet. Click "+ Add shipment" to create one.');
    await fireEvent.click(getByRole('button', { name: '+ Add shipment' }));
    expect(await findByText('New shipment')).toBeInTheDocument();
    expect(getByDisplayValue('5')).toBeInTheDocument();
    expect(getByRole('button', { name: 'Save changes' })).not.toBeDisabled();
  });

  it('saves a new draft by posting the shipment and its non-zero item', async () => {
    mockApi({
      deliverables: [{ id: 1, description: 'Widget', qty_ordered: '5', qty_remaining: '5', units: 'ea' }],
    });
    api.post.mockImplementation((url) => {
      if (url === '/api/jobs/3/shipments/') return Promise.resolve({ id: 99 });
      return Promise.resolve({});
    });
    const onJobChange = vi.fn();
    const { findByText, getByRole } = render(ShipmentsPanel, { props: { job, onJobChange } });
    await findByText('No shipments yet. Click "+ Add shipment" to create one.');
    await fireEvent.click(getByRole('button', { name: '+ Add shipment' }));
    await findByText('New shipment');

    mockApi({
      deliverables: [{ id: 1, description: 'Widget', qty_ordered: '5', qty_remaining: '0', units: 'ea' }],
      shipments: [{ id: 99, sequence: 1, status: 'prepared', prepared_date: '2026-07-01T00:00:00Z', items: [{ id: 1, deliverable: 1, qty: '5' }] }],
    });

    await fireEvent.click(getByRole('button', { name: 'Save changes' }));

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/api/jobs/3/shipments/', {});
      expect(api.post).toHaveBeenCalledWith('/api/shipments/99/items/', { deliverable: 1, qty: '5' });
    });
    expect(onJobChange).toHaveBeenCalled();
  });

  it('discards a draft shipment locally with no API call', async () => {
    mockApi({
      deliverables: [{ id: 1, description: 'Widget', qty_ordered: '5', qty_remaining: '5', units: 'ea' }],
    });
    const { findByText, getByRole, queryByText } = render(ShipmentsPanel, { props: { job } });
    await findByText('No shipments yet. Click "+ Add shipment" to create one.');
    await fireEvent.click(getByRole('button', { name: '+ Add shipment' }));
    await findByText('New shipment');
    await fireEvent.click(getByRole('button', { name: 'Discard' }));
    expect(queryByText('New shipment')).toBeNull();
    expect(api.delete).not.toHaveBeenCalled();
  });

  it('discarding a persisted shipment confirms, deletes its items and itself, and refreshes', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    mockApi({
      deliverables: [{ id: 1, description: 'Widget', qty_ordered: '5', qty_remaining: '0', units: 'ea' }],
      shipments: [{ id: 10, sequence: 1, status: 'prepared', prepared_date: '2026-07-01T00:00:00Z', items: [{ id: 5, deliverable: 1, qty: '5' }] }],
    });
    const onJobChange = vi.fn();
    const { findByText, getByRole } = render(ShipmentsPanel, { props: { job, onJobChange } });
    await findByText('Widget');

    mockApi({ deliverables: [{ id: 1, description: 'Widget', qty_ordered: '5', qty_remaining: '5', units: 'ea' }] });
    await fireEvent.click(getByRole('button', { name: 'Discard' }));

    await waitFor(() => {
      expect(api.delete).toHaveBeenCalledWith('/api/shipments/10/items/5/');
      expect(api.delete).toHaveBeenCalledWith('/api/shipments/10/');
    });
    expect(onJobChange).toHaveBeenCalled();
    window.confirm.mockRestore();
  });

  it('marks a shipment picked up after confirming, then refreshes', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    mockApi({
      deliverables: [{ id: 1, description: 'Widget', qty_ordered: '5', qty_remaining: '0', units: 'ea' }],
      shipments: [{ id: 10, sequence: 1, status: 'prepared', prepared_date: '2026-07-01T00:00:00Z', items: [{ id: 5, deliverable: 1, qty: '5' }] }],
    });
    const onJobChange = vi.fn();
    const { findByText, getByRole } = render(ShipmentsPanel, { props: { job, onJobChange } });
    await findByText('Widget');
    await fireEvent.click(getByRole('button', { name: 'Mark picked up' }));
    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/api/shipments/10/pick-up/', {});
    });
    expect(onJobChange).toHaveBeenCalled();
    window.confirm.mockRestore();
  });

  it('discard changes clears pending edits without any API call', async () => {
    mockApi({
      deliverables: [{ id: 1, description: 'Widget', qty_ordered: '5', qty_remaining: '5', units: 'ea' }],
      shipments: [{ id: 10, sequence: 1, status: 'prepared', prepared_date: '2026-07-01T00:00:00Z', items: [] }],
    });
    const { findByText, getByRole } = render(ShipmentsPanel, { props: { job } });
    await findByText('Widget');
    const input = document.querySelector('.qty-input');
    await fireEvent.input(input, { target: { value: '3' } });
    expect(getByRole('button', { name: 'Discard changes' })).not.toBeDisabled();
    await fireEvent.click(getByRole('button', { name: 'Discard changes' }));
    expect(getByRole('button', { name: 'Save changes' })).toBeDisabled();
    expect(api.post).not.toHaveBeenCalled();
    expect(api.patch).not.toHaveBeenCalled();
  });
});

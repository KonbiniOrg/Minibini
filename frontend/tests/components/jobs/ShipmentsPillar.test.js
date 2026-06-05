import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));

import { api } from '@/lib/api.js';
import ShipmentsPillar from '@/components/jobs/ShipmentsPillar.svelte';

function mockApi({ deliverables = [], shipments = [] } = {}) {
  api.get.mockImplementation((url) => {
    if (url.includes('/deliverables/')) return Promise.resolve(deliverables);
    return Promise.resolve(shipments);
  });
}

beforeEach(() => {
  api.get.mockReset();
});

describe('ShipmentsPillar', () => {
  it('says there is nothing to ship without deliverables', async () => {
    mockApi({ deliverables: [] });
    const { findByText } = render(ShipmentsPillar, { props: { jobId: 5 } });
    expect(await findByText('No deliverables yet; cannot ship.')).toBeInTheDocument();
  });

  it('shows no-shipments when deliverables exist but no shipments', async () => {
    mockApi({ deliverables: [{ deliverable_id: 1, description: 'Widget', qty_ordered: '5', units: 'ea' }], shipments: [] });
    const { findByText } = render(ShipmentsPillar, { props: { jobId: 5 } });
    expect(await findByText('No shipments yet.')).toBeInTheDocument();
  });

  it('renders the matrix when there are shipments', async () => {
    mockApi({
      deliverables: [{ deliverable_id: 1, description: 'Widget', qty_ordered: '5', units: 'ea' }],
      shipments: [{ sequence: 1, status: 'prepared', items: [] }],
    });
    const { findByText } = render(ShipmentsPillar, { props: { jobId: 5 } });
    expect(await findByText('Widget')).toBeInTheDocument();
  });
});

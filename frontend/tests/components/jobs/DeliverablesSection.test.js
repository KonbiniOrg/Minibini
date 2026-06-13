import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));

import { api } from '@/lib/api.js';
import DeliverablesSection from '@/components/jobs/DeliverablesSection.svelte';

function mockApi({ items = [], editable = false } = {}) {
  api.get.mockImplementation((url) => {
    if (url.endsWith('/editability/')) return Promise.resolve({ editable, reason: null });
    return Promise.resolve(items);
  });
}

beforeEach(() => {
  api.get.mockReset();
});

describe('DeliverablesSection', () => {
  it('loads and lists deliverables', async () => {
    mockApi({ items: [{ qty_ordered: '10.00', units: 'ea', description: 'Widget' }] });
    const { findByText } = render(DeliverablesSection, { props: { jobId: 5 } });
    expect(await findByText('Widget')).toBeInTheDocument();
    expect(await findByText('10')).toBeInTheDocument(); // trailing zeros trimmed
  });

  it('shows the empty state', async () => {
    mockApi({ items: [] });
    const { findByText } = render(DeliverablesSection, { props: { jobId: 5 } });
    expect(await findByText(/No deliverables yet/)).toBeInTheDocument();
  });

  it('offers Edit when the user can manage and the list is editable', async () => {
    mockApi({ items: [{ qty_ordered: '1', units: 'ea', description: 'X' }], editable: true });
    const { findByRole } = render(DeliverablesSection, { props: { jobId: 5, canManage: true } });
    expect(await findByRole('button', { name: 'Edit' })).toBeInTheDocument();
  });

  it('hides Edit when the user cannot manage, even if editable', async () => {
    mockApi({ items: [{ qty_ordered: '1', units: 'ea', description: 'X' }], editable: true });
    const { findByText, queryByRole } = render(DeliverablesSection, { props: { jobId: 5, canManage: false } });
    await findByText('X'); // wait for load to settle
    expect(queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument();
  });

  it('hides Edit when not editable, even if the user can manage', async () => {
    mockApi({ items: [{ qty_ordered: '1', units: 'ea', description: 'X' }], editable: false });
    const { findByText, queryByRole } = render(DeliverablesSection, { props: { jobId: 5, canManage: true } });
    await findByText('X'); // wait for load to settle
    expect(queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument();
  });
});

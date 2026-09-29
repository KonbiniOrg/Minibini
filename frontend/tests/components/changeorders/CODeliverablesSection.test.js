import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';
import { get } from 'svelte/store';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  errorMessage: (e, fallback) => e?.message || fallback || 'Request failed.',
}));

import { api } from '@/lib/api.js';
import { deliverablesVersion } from '@/stores/deliverables.js';
import CODeliverablesSection from '@/components/changeorders/CODeliverablesSection.svelte';

const ROW = {
  kind: 'unchanged', anchored: false,
  live: { id: 1, description: 'Panel A', qty_ordered: '2.00', units: 'ea' },
  description: 'Panel A', qty: '2.00', units: 'ea',
};

beforeEach(() => {
  api.get.mockReset(); api.post.mockReset(); api.patch.mockReset(); api.delete.mockReset();
  api.get.mockResolvedValue([]); // UnitsSelect
  api.delete.mockResolvedValue({ message: 'Deliverable deleted.' });
  api.post.mockResolvedValue({ id: 2 });
});

describe('CODeliverablesSection', () => {
  it('bumps the deliverables store after a delete, then reloads the CO', async () => {
    const onReload = vi.fn();
    const before = get(deliverablesVersion);
    const { getByRole } = render(CODeliverablesSection, {
      props: { jobId: 9, rows: [ROW], canEdit: true, onReload },
    });
    await fireEvent.click(getByRole('button', { name: 'Delete' }));
    await waitFor(() => expect(get(deliverablesVersion)).toBe(before + 1));
    expect(api.delete).toHaveBeenCalledWith('/api/jobs/9/deliverables/1/');
    expect(onReload).toHaveBeenCalled();
  });

  it('bumps the deliverables store after adding a new deliverable', async () => {
    const before = get(deliverablesVersion);
    const { getByRole, findByRole, getByPlaceholderText } = render(CODeliverablesSection, {
      props: { jobId: 9, rows: [], canEdit: true, onReload: vi.fn() },
    });
    await fireEvent.click(getByRole('button', { name: '+ New deliverable' }));
    const desc = await findByRole('textbox', { name: /description/i }).catch(() => null);
    const input = desc || getByPlaceholderText(/description/i);
    await fireEvent.input(input, { target: { value: 'Panel B' } });
    await fireEvent.click(getByRole('button', { name: 'Add' }));
    await waitFor(() => expect(get(deliverablesVersion)).toBe(before + 1));
  });

  it('does not bump the store when the delete fails', async () => {
    api.delete.mockRejectedValue({ status: 400, message: 'Nope', data: { detail: 'Nope' } });
    const before = get(deliverablesVersion);
    const { getByRole } = render(CODeliverablesSection, {
      props: { jobId: 9, rows: [ROW], canEdit: true, onReload: vi.fn() },
    });
    await fireEvent.click(getByRole('button', { name: 'Delete' }));
    await waitFor(() => expect(api.delete).toHaveBeenCalled());
    expect(get(deliverablesVersion)).toBe(before);
  });
});

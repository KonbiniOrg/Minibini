import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor, within } from '@testing-library/svelte';
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

  it('bumps the deliverables store after adding a new deliverable (via the New deliverable modal)', async () => {
    const before = get(deliverablesVersion);
    const { getByRole, findByRole } = render(CODeliverablesSection, {
      props: { jobId: 9, rows: [], canEdit: true, onReload: vi.fn() },
    });
    await fireEvent.click(getByRole('button', { name: '+ New deliverable' }));
    const dialog = await findByRole('dialog', { name: 'New deliverable' });
    await fireEvent.input(within(dialog).getByLabelText('Description'), { target: { value: 'Panel B' } });
    await fireEvent.click(within(dialog).getByRole('button', { name: 'Add' }));
    await waitFor(() => expect(get(deliverablesVersion)).toBe(before + 1));
    expect(api.post).toHaveBeenCalledWith('/api/jobs/9/deliverables/', expect.objectContaining({ description: 'Panel B' }));
  });

  it('Change opens the edit modal prefilled and patches on Save', async () => {
    api.patch.mockResolvedValue({});
    const onReload = vi.fn();
    const { getByRole, findByRole } = render(CODeliverablesSection, {
      props: { jobId: 9, rows: [ROW], canEdit: true, onReload },
    });
    await fireEvent.click(getByRole('button', { name: 'Change' }));
    const dialog = await findByRole('dialog', { name: 'Edit deliverable' });
    expect(within(dialog).getByLabelText('Qty').value).toBe('2');
    expect(within(dialog).getByLabelText('Description').value).toBe('Panel A');
    await fireEvent.input(within(dialog).getByLabelText('Qty'), { target: { value: '3' } });
    await fireEvent.click(within(dialog).getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith('/api/jobs/9/deliverables/1/', expect.objectContaining({ qty_ordered: '3' })));
    expect(onReload).toHaveBeenCalled();
  });

  it('Escape closes the drafting modal without saving', async () => {
    const { getByRole, findByRole, queryByRole } = render(CODeliverablesSection, {
      props: { jobId: 9, rows: [], canEdit: true, onReload: vi.fn() },
    });
    await fireEvent.click(getByRole('button', { name: '+ New deliverable' }));
    await findByRole('dialog', { name: 'New deliverable' });
    await fireEvent.keyDown(window, { key: 'Escape' });
    expect(queryByRole('dialog')).toBeNull();
    expect(api.post).not.toHaveBeenCalled();
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

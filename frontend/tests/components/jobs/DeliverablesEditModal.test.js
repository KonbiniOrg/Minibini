import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() } }));

import { get } from 'svelte/store';
import { api } from '@/lib/api.js';
import { deliverablesVersion } from '@/stores/deliverables.js';
import DeliverablesEditModal from '@/components/jobs/DeliverablesEditModal.svelte';

beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();
  api.patch.mockReset();
  api.delete.mockReset();
  api.get.mockImplementation((url) => {
    if (url.endsWith('/deliverables/')) return Promise.resolve([{ id: 1, description: 'Widget', qty_ordered: '5', units: 'ea' }]);
    return Promise.resolve([]); // UnitsSelect
  });
  api.post.mockResolvedValue({ id: 2 });
  api.patch.mockResolvedValue({});
  api.delete.mockResolvedValue({});
});

describe('DeliverablesEditModal', () => {
  it('shows a notice under the heading when one is passed', async () => {
    const { findByDisplayValue, getByText } = render(DeliverablesEditModal, {
      props: { jobId: 5, onClose: vi.fn(), notice: 'Deliverables are required before this estimate can be sent.' },
    });
    await findByDisplayValue('Widget');
    expect(getByText('Deliverables are required before this estimate can be sent.')).toBeInTheDocument();
  });

  it('shows no notice by default', async () => {
    const { findByDisplayValue, queryByText } = render(DeliverablesEditModal, {
      props: { jobId: 5, onClose: vi.fn() },
    });
    await findByDisplayValue('Widget');
    expect(queryByText(/required/)).toBeNull();
  });

  it('loads existing rows', async () => {
    const { findByDisplayValue } = render(DeliverablesEditModal, { props: { jobId: 5, onClose: vi.fn() } });
    expect(await findByDisplayValue('Widget')).toBeInTheDocument();
  });

  it('adds a row and posts it on save', async () => {
    const onClose = vi.fn();
    const { findByDisplayValue, getByRole } = render(DeliverablesEditModal, { props: { jobId: 5, onClose } });
    await findByDisplayValue('Widget');
    await fireEvent.click(getByRole('button', { name: '+ Add row' }));
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    expect(api.post).toHaveBeenCalledWith('/api/jobs/5/deliverables/', { description: '', qty_ordered: '1', units: 'ea' });
  });

  it('bumps the deliverables store on a successful save', async () => {
    const before = get(deliverablesVersion);
    const { findByDisplayValue, getByRole } = render(DeliverablesEditModal, { props: { jobId: 5, onClose: vi.fn() } });
    await findByDisplayValue('Widget');
    await fireEvent.click(getByRole('button', { name: '+ Add row' }));
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(get(deliverablesVersion)).toBe(before + 1));
  });

  it('does not bump the deliverables store on cancel', async () => {
    const before = get(deliverablesVersion);
    const { findByDisplayValue, getByRole } = render(DeliverablesEditModal, { props: { jobId: 5, onClose: vi.fn() } });
    await findByDisplayValue('Widget');
    await fireEvent.click(getByRole('button', { name: 'Cancel' }));
    expect(get(deliverablesVersion)).toBe(before);
  });

  it('cancels via onClose(false)', async () => {
    const onClose = vi.fn();
    const { findByDisplayValue, getByRole } = render(DeliverablesEditModal, { props: { jobId: 5, onClose } });
    await findByDisplayValue('Widget');
    await fireEvent.click(getByRole('button', { name: 'Cancel' }));
    expect(onClose).toHaveBeenCalledWith(false);
  });
});

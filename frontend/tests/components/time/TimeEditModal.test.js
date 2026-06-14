import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() } }));
vi.mock('@/stores/blepActivity.js', () => ({ notifyBlepChanged: vi.fn() }));
vi.mock('@/stores/shift.js', () => ({ notifyShiftChanged: vi.fn() }));

import { api } from '@/lib/api.js';
import TimeEditModal from '@/components/time/TimeEditModal.svelte';

const blep = { blep_id: 7, task: 3, start_time: '2026-03-01T14:00:00Z', end_time: '2026-03-01T15:00:00Z', user: 2 };

beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();
  api.patch.mockReset();
  api.delete.mockReset();
  api.get.mockResolvedValue([]);
  api.post.mockResolvedValue({});
  api.patch.mockResolvedValue({});
  api.delete.mockResolvedValue({});
});

describe('TimeEditModal', () => {
  it('patches an edited blep', async () => {
    const { getByRole } = render(TimeEditModal, {
      props: { open: true, recordType: 'blep', action: 'edit', record: blep, currentUser: { id: 2 } },
    });
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    expect(api.patch).toHaveBeenCalledWith('/api/bleps/7/', expect.objectContaining({
      start_time: expect.any(String), end_time: expect.any(String),
    }));
  });

  it('deletes a blep after confirmation', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    const { getByRole } = render(TimeEditModal, {
      props: { open: true, recordType: 'blep', action: 'edit', record: blep, currentUser: { id: 2 } },
    });
    await fireEvent.click(getByRole('button', { name: 'Delete' }));
    expect(api.delete).toHaveBeenCalledWith('/api/bleps/7/');
    confirmSpy.mockRestore();
  });

  it('submits a change request', async () => {
    const { getByRole } = render(TimeEditModal, {
      props: { open: true, recordType: 'blep', action: 'request', record: blep, currentUser: { id: 2 } },
    });
    await fireEvent.input(getByRole('textbox'), { target: { value: 'fix start' } });
    await fireEvent.click(getByRole('button', { name: 'Submit request' }));
    expect(api.post).toHaveBeenCalledWith('/api/blep-change-requests/', expect.objectContaining({
      reason: 'fix start', task: 3, blep: 7,
    }));
  });

  it('does not block a blep edit when an ongoing (open) shift covers it', async () => {
    // Open shift starting before the blep, still running (end_time null).
    api.get.mockResolvedValue([
      { shift_id: 1, start_time: '2026-03-01T13:00:00Z', end_time: null },
    ]);
    const { getByLabelText, getByRole, queryByText } = render(TimeEditModal, {
      props: { open: true, recordType: 'blep', action: 'edit', record: blep, currentUser: { id: 2 } },
    });
    await fireEvent.blur(getByLabelText('Start'));
    await vi.waitFor(() => expect(api.get).toHaveBeenCalled());
    await api.get.mock.results[0].value;            // the shifts promise the component awaits
    await new Promise((r) => setTimeout(r, 0));     // flush .then continuation + Svelte update
    expect(queryByText(/No shift covers this time/i)).not.toBeInTheDocument();
    expect(getByRole('button', { name: 'Save' })).not.toBeDisabled();
  });

  it('blocks a blep edit when no shift covers it (control: the check runs)', async () => {
    api.get.mockResolvedValue([]); // no shifts at all
    const { getByLabelText, getByRole, findByText } = render(TimeEditModal, {
      props: { open: true, recordType: 'blep', action: 'edit', record: blep, currentUser: { id: 2 } },
    });
    await fireEvent.blur(getByLabelText('Start'));
    expect(await findByText(/No shift covers this time/i)).toBeInTheDocument();
    expect(getByRole('button', { name: 'Save' })).toBeDisabled();
  });
});

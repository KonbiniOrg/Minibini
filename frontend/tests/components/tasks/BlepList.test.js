import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import BlepList from '@/components/tasks/BlepList.svelte';
import { user } from '@/stores/auth.js';

const recent = new Date(Date.now() - 1000).toISOString();
const old = new Date(Date.now() - 48 * 60 * 60 * 1000).toISOString();

beforeEach(() => {
  user.set({ id: 5, permissions: [] }); // worker by default
});

describe('BlepList', () => {
  it('shows the empty state and an Add Entry action', async () => {
    const onAdd = vi.fn();
    const { getByText, getByRole } = render(BlepList, { props: { bleps: [], onAdd } });
    expect(getByText('No work sessions recorded.')).toBeInTheDocument();
    await fireEvent.click(getByRole('button', { name: 'Add Entry' }));
    expect(onAdd).toHaveBeenCalled();
  });

  it('lets a time manager edit anyone\'s old blep', async () => {
    user.set({ id: 5, permissions: ['can_manage_time'] });
    const onEdit = vi.fn();
    const { getByRole } = render(BlepList, {
      props: {
        bleps: [{ blep_id: 1, user: 99, user_name: 'Bob', start_time: old }],
        currentUser: { id: 5 },
        onEdit,
      },
    });
    await fireEvent.click(getByRole('button', { name: 'Edit' }));
    expect(onEdit).toHaveBeenCalledWith(expect.objectContaining({ blep_id: 1 }));
  });

  it('lets a worker edit their own recent blep', () => {
    const { getByRole } = render(BlepList, {
      props: {
        bleps: [{ blep_id: 2, user: 5, user_name: 'Me', start_time: recent }],
        currentUser: { id: 5 },
      },
    });
    expect(getByRole('button', { name: 'Edit' })).toBeInTheDocument();
  });

  // Quantity structure (spec §9 rule 1, task-owned-money Phase 4): a
  // historical time entry is a blep, and the backend rejects creating one
  // on a parent task the same as start-work — hide the affordance rather
  // than let it round-trip a guaranteed error.
  it('hides Add Entry when canAdd is false', () => {
    const { queryByRole } = render(BlepList, { props: { bleps: [], canAdd: false } });
    expect(queryByRole('button', { name: 'Add Entry' })).toBeNull();
  });

  it('shows Add Entry by default (canAdd defaults true)', () => {
    const { getByRole } = render(BlepList, { props: { bleps: [] } });
    expect(getByRole('button', { name: 'Add Entry' })).toBeInTheDocument();
  });

  it("does not let a worker edit someone else's blep", () => {
    const { queryByRole } = render(BlepList, {
      props: {
        bleps: [{ blep_id: 3, user: 9, user_name: 'Other', start_time: recent }],
        currentUser: { id: 5 },
      },
    });
    expect(queryByRole('button', { name: 'Edit' })).toBeNull();
    expect(queryByRole('button', { name: 'Delete' })).toBeNull();
  });
});

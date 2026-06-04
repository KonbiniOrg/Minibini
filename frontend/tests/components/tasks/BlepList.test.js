import { describe, it, expect, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import BlepList from '@/components/tasks/BlepList.svelte';

const recent = new Date(Date.now() - 1000).toISOString();
const old = new Date(Date.now() - 48 * 60 * 60 * 1000).toISOString();

describe('BlepList', () => {
  it('shows the empty state and an Add Entry action', async () => {
    const onAdd = vi.fn();
    const { getByText, getByRole } = render(BlepList, { props: { bleps: [], onAdd } });
    expect(getByText('No work sessions recorded.')).toBeInTheDocument();
    await fireEvent.click(getByRole('button', { name: 'Add Entry' }));
    expect(onAdd).toHaveBeenCalled();
  });

  it('lets a time manager edit anyone\'s old blep', async () => {
    const onEdit = vi.fn();
    const { getByRole } = render(BlepList, {
      props: {
        bleps: [{ blep_id: 1, user: 99, user_name: 'Bob', start_time: old }],
        currentUser: { id: 5 },
        userPermissions: ['can_manage_time'],
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
        userPermissions: [],
      },
    });
    expect(getByRole('button', { name: 'Edit' })).toBeInTheDocument();
  });

  it("does not let a worker edit someone else's blep", () => {
    const { queryByRole } = render(BlepList, {
      props: {
        bleps: [{ blep_id: 3, user: 9, user_name: 'Other', start_time: recent }],
        currentUser: { id: 5 },
        userPermissions: [],
      },
    });
    expect(queryByRole('button', { name: 'Edit' })).toBeNull();
    expect(queryByRole('button', { name: 'Delete' })).toBeNull();
  });
});

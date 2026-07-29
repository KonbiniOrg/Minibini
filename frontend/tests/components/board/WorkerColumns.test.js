import { describe, it, expect, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import WorkerColumns from '@/components/board/WorkerColumns.svelte';

function workers() {
  return [{
    user: { id: 1, name: 'Sam', initials: 'S' },
    tasks: [{ task_id: 10, name: 'A', status: 'pending', job_id: 3, job_name: 'J' }],
  }];
}

describe('WorkerColumns', () => {
  it('renders a worker column with its tasks', () => {
    const { getByText } = render(WorkerColumns, { props: { workers: workers() } });
    expect(getByText('Sam')).toBeInTheDocument();
    expect(getByText('A')).toBeInTheDocument();
  });

  it('links the worker name header to that user\'s PM-filtered job list', () => {
    const { getByRole } = render(WorkerColumns, { props: { workers: workers() } });
    const link = getByRole('link', { name: 'Sam' });
    expect(link).toHaveAttribute('href', '#/jobs?pm=1');
  });

  it('assigns a dropped task to the worker at the end index', async () => {
    const onAssign = vi.fn();
    const { container } = render(WorkerColumns, { props: { workers: workers(), canManage: true, onAssign } });
    const col = container.querySelector('.worker-tasks');
    await fireEvent.dragOver(col, { dataTransfer: {}, clientY: 100 });
    await fireEvent.drop(col, { dataTransfer: { getData: () => '10' } });
    // dropped after the single existing task → index 1, worker id 1
    expect(onAssign).toHaveBeenCalledWith(10, 1, 1);
  });

  it('adds a worker column from the dropdown', async () => {
    const onAddWorker = vi.fn();
    const { getByTitle, getByText } = render(WorkerColumns, {
      props: { workers: workers(), canManage: true, availableWorkers: [{ id: 2, name: 'Dana', initials: 'D' }], onAddWorker },
    });
    await fireEvent.click(getByTitle('Add worker column'));
    await fireEvent.click(getByText('Dana'));
    expect(onAddWorker).toHaveBeenCalledWith(expect.objectContaining({ id: 2 }));
  });
});

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn() },
  errorMessage: (e, fallback) => (e && e.message) || fallback || 'Request failed.',
}));

import { api } from '@/lib/api.js';
import AssignModal from '@/components/AssignModal.svelte';

const USERS = [{ id: 1, name: 'Ann Worker', username: 'ann' }];

beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();
  api.get.mockResolvedValue(USERS);
  api.post.mockResolvedValue({});
});

describe('AssignModal', () => {
  it('assigns a user, sending the parsed est_worker_time', async () => {
    const onSaved = vi.fn();
    const task = { task_id: 5, name: 'Cut parts', assignee: null, est_worker_time: null };
    const { findByRole, getByLabelText, getByRole } = render(AssignModal, {
      props: { open: true, task, onSaved },
    });
    const select = await findByRole('combobox');
    await fireEvent.change(select, { target: { value: '1' } });
    await fireEvent.input(getByLabelText(/Estimated worker time/), { target: { value: '1:30' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));

    expect(api.post).toHaveBeenCalledWith('/api/tasks/5/assign/', {
      assignee: 1, worker_queue: null, est_worker_time: 'PT1H30M',
    });
    expect(onSaved).toHaveBeenCalled();
  });

  it('shows an unparseable duration as a field error under the input', async () => {
    const task = { task_id: 5, name: 'Cut parts', assignee: null, est_worker_time: null };
    const { findByRole, getByLabelText, getByRole, findByText } = render(AssignModal, {
      props: { open: true, task },
    });
    const select = await findByRole('combobox');
    await fireEvent.change(select, { target: { value: '1' } });
    await fireEvent.input(getByLabelText(/Estimated worker time/), { target: { value: 'banana' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));

    const msg = await findByText(/Could not read "banana" as a duration/);
    expect(msg).toHaveClass('field-error');
    expect(api.post).not.toHaveBeenCalled();
  });

  it('renders API field errors under the matching inputs', async () => {
    api.post.mockRejectedValue({
      status: 400,
      message: 'Bad request',
      data: { assignee: ['Invalid user.'] },
    });
    const task = { task_id: 5, name: 'Cut parts', assignee: null, est_worker_time: 'PT2H0M' };
    const { findByRole, getByRole, findByText } = render(AssignModal, {
      props: { open: true, task },
    });
    const select = await findByRole('combobox');
    await fireEvent.change(select, { target: { value: '1' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));

    const msg = await findByText('Invalid user.');
    expect(msg).toHaveClass('field-error');
  });

  it('renders an operation error in the form footer', async () => {
    api.post.mockRejectedValue({
      status: 400,
      message: 'Task is complete; it cannot be assigned.',
      data: { detail: 'Task is complete; it cannot be assigned.' },
    });
    const task = { task_id: 5, name: 'Cut parts', assignee: null, est_worker_time: 'PT2H0M' };
    const { findByRole, getByRole, findByText } = render(AssignModal, {
      props: { open: true, task },
    });
    const select = await findByRole('combobox');
    await fireEvent.change(select, { target: { value: '1' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));

    const alert = await findByRole('alert');
    expect(alert).toHaveTextContent('Task is complete; it cannot be assigned.');
    expect(await findByText('Task is complete; it cannot be assigned.')).toBeInTheDocument();
  });

  it('calls onClose when Cancel is clicked', async () => {
    const onClose = vi.fn();
    const task = { task_id: 5, name: 'Cut parts', assignee: null, est_worker_time: 'PT2H0M' };
    const { getByRole } = render(AssignModal, {
      props: { open: true, task, onClose },
    });
    await fireEvent.click(getByRole('button', { name: 'Cancel' }));
    expect(onClose).toHaveBeenCalled();
  });
});

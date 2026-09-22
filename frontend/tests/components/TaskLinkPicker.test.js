import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, findByRole } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));
import { api } from '@/lib/api.js';
import TaskLinkPicker from '@/components/TaskLinkPicker.svelte';

beforeEach(() => { api.get.mockReset(); });

describe('TaskLinkPicker', () => {
  it('filters the picked job\'s tasks as you type (fix 3: was an unfiltered <select>) and picks one', async () => {
    api.get.mockImplementation((url) => {
      if (url.startsWith('/api/jobs/?')) {
        return Promise.resolve({ results: [{ job_id: 5, job_number: 'JOB-5', name: 'widget' }] });
      }
      if (url === '/api/jobs/5/tasks/') {
        return Promise.resolve([
          { task_id: 10, name: 'Top task' },
          { task_id: 11, name: 'Other task' },
        ]);
      }
      return Promise.resolve([]);
    });
    const { getByPlaceholderText, container, queryByText } = render(TaskLinkPicker, { props: {} });

    await fireEvent.input(getByPlaceholderText('Search jobs…'), { target: { value: 'wid' } });
    await new Promise((r) => setTimeout(r, 300));
    await fireEvent.mouseDown(await findByRole(container, 'button', { name: /JOB-5/ }));
    await new Promise((r) => setTimeout(r)); // let loadTasks(5) settle

    // No native <select> anymore — a type-ahead search box.
    expect(container.querySelector('select')).toBeNull();
    const taskInput = getByPlaceholderText('Search tasks…');
    expect(taskInput).not.toBeDisabled();

    await fireEvent.input(taskInput, { target: { value: 'top' } });
    await new Promise((r) => setTimeout(r, 300));
    expect(await findByRole(container, 'button', { name: 'Top task' })).toBeInTheDocument();
    expect(queryByText('Other task')).toBeNull(); // filtered out by the query

    await fireEvent.mouseDown(await findByRole(container, 'button', { name: 'Top task' }));
    // Picking collapses the SearchPicker into its "selected" state — a
    // label + Clear button, same contract as JobPicker just above it (two
    // Clear buttons now show: one for the job, one for the task).
    await new Promise((r) => setTimeout(r));
    expect(container.textContent).toContain('Top task');
    expect(container.querySelectorAll('.sp-selected')).toHaveLength(2);
  });

  it('disables the task search until a job is picked', () => {
    const { getByPlaceholderText } = render(TaskLinkPicker, { props: {} });
    expect(getByPlaceholderText('Search tasks…')).toBeDisabled();
  });

  it('resolves the job and task labels of a preselected task id (edit mode)', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/api/tasks/10/') {
        return Promise.resolve({ task_id: 10, name: 'Top task', job: { id: 5, job_number: 'JOB-5', name: 'widget' } });
      }
      if (url === '/api/jobs/5/tasks/') {
        return Promise.resolve([{ task_id: 10, name: 'Top task' }]);
      }
      return Promise.resolve([]);
    });
    const { findByText } = render(TaskLinkPicker, { props: { value: 10 } });
    expect(await findByText(/JOB-5/)).toBeInTheDocument();
    expect(await findByText('Top task')).toBeInTheDocument();
  });

  it('clears the picked task when the job is changed by the user', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/api/tasks/10/') {
        return Promise.resolve({ task_id: 10, name: 'Old task', job: { id: 5, job_number: 'JOB-5', name: 'widget' } });
      }
      if (url === '/api/jobs/5/tasks/') {
        return Promise.resolve([{ task_id: 10, name: 'Old task' }]);
      }
      if (url.startsWith('/api/jobs/?')) {
        return Promise.resolve({ results: [{ job_id: 6, job_number: 'JOB-6', name: 'other' }] });
      }
      if (url === '/api/jobs/6/tasks/') {
        return Promise.resolve([{ task_id: 20, name: 'Another task' }]);
      }
      return Promise.resolve([]);
    });
    const { getByPlaceholderText, container, findByText, queryByText } = render(TaskLinkPicker, { props: { value: 10 } });
    // Wait for the edit-mode resolve to seed job 5 and its task list.
    await findByText(/JOB-5/);
    await findByText('Old task');

    // Picking a different job clears the previously-linked task.
    const clearButtons = container.querySelectorAll('button');
    await fireEvent.click(clearButtons[0]); // "Clear" on the resolved JobPicker
    expect(queryByText('Old task')).toBeNull();

    await fireEvent.input(getByPlaceholderText('Search jobs…'), { target: { value: 'oth' } });
    await new Promise((r) => setTimeout(r, 300));
    await fireEvent.mouseDown(await findByRole(container, 'button', { name: /JOB-6/ }));
    await new Promise((r) => setTimeout(r));

    expect(queryByText('Old task')).toBeNull();
    expect(getByPlaceholderText('Search tasks…')).toBeInTheDocument();
  });
});

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, findByRole } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));
import { api } from '@/lib/api.js';
import TaskLinkPicker from '@/components/TaskLinkPicker.svelte';

beforeEach(() => { api.get.mockReset(); });

describe('TaskLinkPicker', () => {
  it('lists only top-level (parent_task null) tasks of the picked job', async () => {
    api.get.mockImplementation((url) => {
      if (url.startsWith('/api/jobs/?')) {
        return Promise.resolve({ results: [{ job_id: 5, job_number: 'JOB-5', name: 'widget' }] });
      }
      if (url === '/api/jobs/5/tasks/') {
        return Promise.resolve([
          { task_id: 10, name: 'Top task', parent_task: null },
          { task_id: 11, name: 'Sub task', parent_task: 10 },
        ]);
      }
      return Promise.resolve([]);
    });
    const { getByPlaceholderText, findByRole: findByRoleInComponent, container } = render(TaskLinkPicker, { props: {} });

    await fireEvent.input(getByPlaceholderText('Search jobs…'), { target: { value: 'wid' } });
    await new Promise((r) => setTimeout(r, 300));
    await fireEvent.mouseDown(await findByRole(container, 'button', { name: /JOB-5/ }));

    await new Promise((r) => setTimeout(r));
    const select = container.querySelector('select[aria-label="Task"]');
    const optionTexts = Array.from(select.options).map((o) => o.textContent);
    expect(optionTexts).toContain('Top task');
    expect(optionTexts).not.toContain('Sub task');
  });

  it('resolves the job of a preselected task id (edit mode)', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/api/tasks/10/') {
        return Promise.resolve({ task_id: 10, name: 'Top task', job: { id: 5, job_number: 'JOB-5', name: 'widget' } });
      }
      if (url === '/api/jobs/5/tasks/') {
        return Promise.resolve([{ task_id: 10, name: 'Top task', parent_task: null }]);
      }
      return Promise.resolve([]);
    });
    const { findByText } = render(TaskLinkPicker, { props: { value: 10 } });
    expect(await findByText(/JOB-5/)).toBeInTheDocument();
  });

  it('clears the picked task when the job is changed by the user', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/api/tasks/10/') {
        return Promise.resolve({ task_id: 10, name: 'Old task', job: { id: 5, job_number: 'JOB-5', name: 'widget' } });
      }
      if (url === '/api/jobs/5/tasks/') {
        return Promise.resolve([{ task_id: 10, name: 'Old task', parent_task: null }]);
      }
      if (url.startsWith('/api/jobs/?')) {
        return Promise.resolve({ results: [{ job_id: 6, job_number: 'JOB-6', name: 'other' }] });
      }
      if (url === '/api/jobs/6/tasks/') {
        return Promise.resolve([{ task_id: 20, name: 'Another top task', parent_task: null }]);
      }
      return Promise.resolve([]);
    });
    const { getByPlaceholderText, container, findByText } = render(TaskLinkPicker, { props: { value: 10 } });
    // Wait for the edit-mode resolve to seed job 5 and its task list.
    await findByText(/JOB-5/);
    await new Promise((r) => setTimeout(r));
    const select = container.querySelector('select[aria-label="Task"]');
    expect(select.value).toBe('10');

    // Picking a different job clears the previously-linked task.
    await fireEvent.click(container.querySelector('button')); // "Clear" on the resolved JobPicker
    await fireEvent.input(getByPlaceholderText('Search jobs…'), { target: { value: 'oth' } });
    await new Promise((r) => setTimeout(r, 300));
    await fireEvent.mouseDown(await findByRole(container, 'button', { name: /JOB-6/ }));
    await new Promise((r) => setTimeout(r));

    expect(select.value).not.toBe('10');
  });
});

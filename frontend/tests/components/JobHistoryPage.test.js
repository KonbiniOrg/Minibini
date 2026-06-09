import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn() } }));

import { api } from '@/lib/api.js';
import JobHistoryPage from '@/routes/jobs/JobHistoryPage.svelte';

const JOB = { job_id: 5, job_number: 'JOB-2025-0005', name: 'Test' };

describe('JobHistoryPage', () => {
  beforeEach(() => { api.get.mockReset(); api.post.mockReset(); });

  it('renders collated entries with source labels', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/api/jobs/5/') return Promise.resolve(JOB);
      if (url === '/api/jobs/5/history/') return Promise.resolve({ results: [
        { id: 1, entry_type: 'action', object_type: 'estimate', object_id: 9,
          username: 'admin', timestamp: '2026-01-02T10:00:00Z',
          changes: { _action: 'Sent to customer' },
          source_label: 'Estimate EST-2025-0001', source_link: null },
        { id: 2, entry_type: 'note', object_type: 'job', object_id: 5,
          username: 'admin', timestamp: '2026-01-03T10:00:00Z', text: 'Customer called',
          changes: null, source_label: 'Job JOB-2025-0005', source_link: '#/jobs/5' },
      ] });
      return Promise.resolve({ results: [] });
    });
    const { findByRole, getByText } = render(JobHistoryPage, { props: { params: { id: '5' } } });
    await findByRole('heading', { name: 'History' });
    // JobHeader is mounted, showing the job title band
    expect(getByText(/JOB #2025-0005/)).toBeInTheDocument();
    // Back-to-overview link like the sibling job pages
    expect(getByText('← Back to overview')).toBeInTheDocument();
    expect(getByText('Estimate EST-2025-0001')).toBeInTheDocument();
    expect(getByText('Sent to customer')).toBeInTheDocument();
    expect(getByText('Customer called')).toBeInTheDocument();
  });

  it('color-codes by object type, sharing one class for estimates and change orders', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/api/jobs/5/') return Promise.resolve(JOB);
      if (url === '/api/jobs/5/history/') return Promise.resolve({ results: [
        { id: 1, entry_type: 'audit', object_type: 'estimate', object_id: 9,
          username: 'a', timestamp: '2026-01-02T10:00:00Z', changes: { _created: true },
          source_label: 'Estimate E1', source_link: null },
        { id: 2, entry_type: 'audit', object_type: 'changeorder', object_id: 3,
          username: 'a', timestamp: '2026-01-03T10:00:00Z', changes: { _created: true },
          source_label: 'Change Order CO1', source_link: null },
        { id: 3, entry_type: 'audit', object_type: 'task', object_id: 7,
          username: 'a', timestamp: '2026-01-04T10:00:00Z', changes: { _created: true },
          source_label: 'Task: X', source_link: null },
      ] });
      return Promise.resolve({ results: [] });
    });
    const { container, findByRole } = render(JobHistoryPage, { props: { params: { id: '5' } } });
    await findByRole('heading', { name: 'History' });
    // estimate + changeorder both carry ot-estimate
    expect(container.querySelectorAll('li.ot-estimate').length).toBe(2);
    // task is its own group
    expect(container.querySelector('li.ot-task')).toBeTruthy();
    expect(container.querySelector('li.ot-changeorder')).toBeNull();
  });

  it('suppresses a long field diff behind a Show full popover', async () => {
    const longOld = 'A'.repeat(150);
    const longNew = 'B'.repeat(150);
    api.get.mockImplementation((url) => {
      if (url === '/api/jobs/5/') return Promise.resolve(JOB);
      if (url === '/api/jobs/5/history/') return Promise.resolve({ results: [
        { id: 1, entry_type: 'audit', object_type: 'job', object_id: 5,
          username: 'a', timestamp: '2026-01-02T10:00:00Z',
          changes: { description: { old: longOld, new: longNew } },
          source_label: 'Job J', source_link: null },
      ] });
      return Promise.resolve({ results: [] });
    });
    const { findByRole, getByRole, queryByText } = render(JobHistoryPage, { props: { params: { id: '5' } } });
    await findByRole('heading', { name: 'History' });
    // full content suppressed until expanded
    expect(queryByText(longOld)).toBeNull();
    await fireEvent.click(getByRole('button', { name: 'Show full' }));
    expect(queryByText(longOld)).not.toBeNull();
    expect(queryByText(longNew)).not.toBeNull();
  });

  it('renders a short field diff inline without a popover', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/api/jobs/5/') return Promise.resolve(JOB);
      if (url === '/api/jobs/5/history/') return Promise.resolve({ results: [
        { id: 2, entry_type: 'audit', object_type: 'task', object_id: 7,
          username: 'a', timestamp: '2026-01-03T10:00:00Z',
          changes: { status: { old: 'pending', new: 'complete' } },
          source_label: 'Task: X', source_link: null },
      ] });
      return Promise.resolve({ results: [] });
    });
    const { findByRole, getByText, queryByRole } = render(JobHistoryPage, { props: { params: { id: '5' } } });
    await findByRole('heading', { name: 'History' });
    expect(getByText('pending')).toBeInTheDocument();
    expect(getByText('complete')).toBeInTheDocument();
    expect(queryByRole('button', { name: 'Show full' })).toBeNull();
  });

  it('bundles same-object changes within a minute into one section', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/api/jobs/5/') return Promise.resolve(JOB);
      if (url === '/api/jobs/5/history/') return Promise.resolve({ results: [
        { id: 3, entry_type: 'action', object_type: 'job', object_id: 5, username: 'a',
          timestamp: '2026-01-02T10:00:40Z',
          changes: { status: { old: 'approved', new: 'in_progress' }, _action: 'Work started' },
          source_label: 'Job J', source_link: null },
        { id: 2, entry_type: 'audit', object_type: 'job', object_id: 5, username: 'a',
          timestamp: '2026-01-02T10:00:20Z',
          changes: { name: { old: 'Old', new: 'New' } }, source_label: 'Job J', source_link: null },
        { id: 1, entry_type: 'audit', object_type: 'job', object_id: 5, username: 'a',
          timestamp: '2026-01-02T10:00:00Z',
          changes: { description: { old: 'd1', new: 'd2' } }, source_label: 'Job J', source_link: null },
      ] });
      return Promise.resolve({ results: [] });
    });
    const { container, findByRole, getByText } = render(JobHistoryPage, { props: { params: { id: '5' } } });
    await findByRole('heading', { name: 'History' });
    expect(container.querySelectorAll('li.entry').length).toBe(1);
    expect(getByText('Work started')).toBeInTheDocument();
    expect(getByText('name')).toBeInTheDocument();
    expect(getByText('description')).toBeInTheDocument();
  });

  it('does not bundle different objects or far-apart changes', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/api/jobs/5/') return Promise.resolve(JOB);
      if (url === '/api/jobs/5/history/') return Promise.resolve({ results: [
        { id: 2, entry_type: 'audit', object_type: 'job', object_id: 5, username: 'a',
          timestamp: '2026-01-02T10:05:00Z',
          changes: { name: { old: 'a', new: 'b' } }, source_label: 'Job J', source_link: null },
        { id: 1, entry_type: 'audit', object_type: 'job', object_id: 5, username: 'a',
          timestamp: '2026-01-02T10:00:00Z',
          changes: { name: { old: 'c', new: 'd' } }, source_label: 'Job J', source_link: null },
      ] });
      return Promise.resolve({ results: [] });
    });
    const { container, findByRole } = render(JobHistoryPage, { props: { params: { id: '5' } } });
    await findByRole('heading', { name: 'History' });
    expect(container.querySelectorAll('li.entry').length).toBe(2);
  });

  it('does not bundle same-object changes by different users', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/api/jobs/5/') return Promise.resolve(JOB);
      if (url === '/api/jobs/5/history/') return Promise.resolve({ results: [
        { id: 2, entry_type: 'audit', object_type: 'job', object_id: 5, username: 'alice',
          timestamp: '2026-01-02T10:00:30Z',
          changes: { name: { old: 'a', new: 'b' } }, source_label: 'Job J', source_link: null },
        { id: 1, entry_type: 'audit', object_type: 'job', object_id: 5, username: 'bob',
          timestamp: '2026-01-02T10:00:00Z',
          changes: { name: { old: 'c', new: 'd' } }, source_label: 'Job J', source_link: null },
      ] });
      return Promise.resolve({ results: [] });
    });
    const { container, findByRole } = render(JobHistoryPage, { props: { params: { id: '5' } } });
    await findByRole('heading', { name: 'History' });
    expect(container.querySelectorAll('li.entry').length).toBe(2);
  });

  it('posts a note then reloads', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/api/jobs/5/') return Promise.resolve(JOB);
      return Promise.resolve({ results: [] });
    });
    api.post.mockResolvedValue({});
    const { findByRole, getByPlaceholderText, getByRole } =
      render(JobHistoryPage, { props: { params: { id: '5' } } });
    await findByRole('heading', { name: 'History' });
    await fireEvent.input(getByPlaceholderText('Add a note…'), { target: { value: 'Hello' } });
    await fireEvent.click(getByRole('button', { name: 'Add Note' }));
    expect(api.post).toHaveBeenCalledWith('/api/jobs/5/notes/', { text: 'Hello' });
  });
});

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn() },
  errorMessage: (e, fallback) =>
    e?.data?.detail || e?.message || fallback || 'Something went wrong.',
}));

import { api } from '@/lib/api.js';
import JobHistorySection from '@/components/jobs/JobHistorySection.svelte';

const JOB = { job_id: 5, job_number: 'JOB-2025-0005', name: 'Test' };

describe('JobHistorySection', () => {
  beforeEach(() => { api.get.mockReset(); api.post.mockReset(); });

  it('renders collated entries with source labels', async () => {
    api.get.mockImplementation((url) => {
      if (url.startsWith('/api/jobs/5/history/')) return Promise.resolve({ results: [
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
    const { findByRole, getByRole, getByText } = render(JobHistorySection, { props: { job: JOB } });
    await findByRole('heading', { name: 'History' });
    await fireEvent.click(getByRole('button', { name: 'Timeline' }));
    // Up-navigation now lives in the shared JobNavRail, not a per-panel back link.
    expect(getByText('Estimate EST-2025-0001')).toBeInTheDocument();
    expect(getByText('Sent to customer')).toBeInTheDocument();
    expect(getByText('Customer called')).toBeInTheDocument();
  });

  it('color-codes by object type, sharing one class for estimates and change orders', async () => {
    api.get.mockImplementation((url) => {
      if (url.startsWith('/api/jobs/5/history/')) return Promise.resolve({ results: [
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
    const { container, findByRole, getByRole } = render(JobHistorySection, { props: { job: JOB } });
    await findByRole('heading', { name: 'History' });
    await fireEvent.click(getByRole('button', { name: 'Timeline' }));
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
      if (url.startsWith('/api/jobs/5/history/')) return Promise.resolve({ results: [
        { id: 1, entry_type: 'audit', object_type: 'job', object_id: 5,
          username: 'a', timestamp: '2026-01-02T10:00:00Z',
          changes: { description: { old: longOld, new: longNew } },
          source_label: 'Job J', source_link: null },
      ] });
      return Promise.resolve({ results: [] });
    });
    const { findByRole, getByRole, queryByText } = render(JobHistorySection, { props: { job: JOB } });
    await findByRole('heading', { name: 'History' });
    await fireEvent.click(getByRole('button', { name: 'Timeline' }));
    // full content suppressed until expanded
    expect(queryByText(longOld)).toBeNull();
    await fireEvent.click(getByRole('button', { name: 'Show full' }));
    expect(queryByText(longOld)).not.toBeNull();
    expect(queryByText(longNew)).not.toBeNull();
  });

  it('renders a short field diff inline without a popover', async () => {
    api.get.mockImplementation((url) => {
      if (url.startsWith('/api/jobs/5/history/')) return Promise.resolve({ results: [
        { id: 2, entry_type: 'audit', object_type: 'task', object_id: 7,
          username: 'a', timestamp: '2026-01-03T10:00:00Z',
          changes: { status: { old: 'pending', new: 'complete' } },
          source_label: 'Task: X', source_link: null },
      ] });
      return Promise.resolve({ results: [] });
    });
    const { findByRole, getByRole, getByText, queryByRole } = render(JobHistorySection, { props: { job: JOB } });
    await findByRole('heading', { name: 'History' });
    await fireEvent.click(getByRole('button', { name: 'Timeline' }));
    expect(getByText('pending')).toBeInTheDocument();
    expect(getByText('complete')).toBeInTheDocument();
    expect(queryByRole('button', { name: 'Show full' })).toBeNull();
  });

  it('bundles same-object changes within a minute into one section', async () => {
    api.get.mockImplementation((url) => {
      if (url.startsWith('/api/jobs/5/history/')) return Promise.resolve({ results: [
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
    const { container, findByRole, getByRole, getByText } = render(JobHistorySection, { props: { job: JOB } });
    await findByRole('heading', { name: 'History' });
    await fireEvent.click(getByRole('button', { name: 'Timeline' }));
    expect(container.querySelectorAll('li.entry').length).toBe(1);
    expect(getByText('Work started')).toBeInTheDocument();
    expect(getByText('name')).toBeInTheDocument();
    expect(getByText('description')).toBeInTheDocument();
  });

  it('does not bundle different objects or far-apart changes', async () => {
    api.get.mockImplementation((url) => {
      if (url.startsWith('/api/jobs/5/history/')) return Promise.resolve({ results: [
        { id: 2, entry_type: 'audit', object_type: 'job', object_id: 5, username: 'a',
          timestamp: '2026-01-02T10:05:00Z',
          changes: { name: { old: 'a', new: 'b' } }, source_label: 'Job J', source_link: null },
        { id: 1, entry_type: 'audit', object_type: 'job', object_id: 5, username: 'a',
          timestamp: '2026-01-02T10:00:00Z',
          changes: { name: { old: 'c', new: 'd' } }, source_label: 'Job J', source_link: null },
      ] });
      return Promise.resolve({ results: [] });
    });
    const { container, findByRole, getByRole } = render(JobHistorySection, { props: { job: JOB } });
    await findByRole('heading', { name: 'History' });
    await fireEvent.click(getByRole('button', { name: 'Timeline' }));
    expect(container.querySelectorAll('li.entry').length).toBe(2);
  });

  it('does not bundle same-object changes by different users', async () => {
    api.get.mockImplementation((url) => {
      if (url.startsWith('/api/jobs/5/history/')) return Promise.resolve({ results: [
        { id: 2, entry_type: 'audit', object_type: 'job', object_id: 5, username: 'alice',
          timestamp: '2026-01-02T10:00:30Z',
          changes: { name: { old: 'a', new: 'b' } }, source_label: 'Job J', source_link: null },
        { id: 1, entry_type: 'audit', object_type: 'job', object_id: 5, username: 'bob',
          timestamp: '2026-01-02T10:00:00Z',
          changes: { name: { old: 'c', new: 'd' } }, source_label: 'Job J', source_link: null },
      ] });
      return Promise.resolve({ results: [] });
    });
    const { container, findByRole, getByRole } = render(JobHistorySection, { props: { job: JOB } });
    await findByRole('heading', { name: 'History' });
    await fireEvent.click(getByRole('button', { name: 'Timeline' }));
    expect(container.querySelectorAll('li.entry').length).toBe(2);
  });

  it('fetches all pages when history is paginated', async () => {
    api.get.mockImplementation((url) => {
      if (url.includes('page=2')) return Promise.resolve({ count: 130, results: [] });
      if (url.startsWith('/api/jobs/5/history/')) return Promise.resolve({ count: 130, results: [] });
      return Promise.resolve({ results: [] });
    });
    const { findByRole } = render(JobHistorySection, { props: { job: JOB } });
    await findByRole('heading', { name: 'History' });
    expect(api.get).toHaveBeenCalledWith('/api/jobs/5/history/?page=2&page_size=100');
  });

  it('defaults to the Summary tab, listed first with house tab styling', async () => {
    api.get.mockImplementation((url) => {
      if (url.startsWith('/api/jobs/5/history/')) return Promise.resolve({ results: [
        { id: 1, entry_type: 'audit', object_type: 'task', object_id: 7,
          username: 'rae', timestamp: '2026-01-05T09:00:00',
          changes: { status: { old: 'pending', new: 'complete' } },
          source_label: 'Task: Cutting', source_link: null },
      ] });
      return Promise.resolve({ results: [] });
    });
    const { container, findByRole, queryByPlaceholderText } =
      render(JobHistorySection, { props: { job: JOB } });
    await findByRole('heading', { name: 'History' });
    // milestone log renders with no tab click; Timeline content (note box) does not
    expect(container.querySelectorAll('tr.log-row').length).toBe(1);
    expect(queryByPlaceholderText('Add a note…')).toBeNull();
    // Summary is the leftmost tab in the shared .page-tabs strip
    const tabs = container.querySelectorAll('.page-tabs button');
    expect(tabs[0]).toHaveTextContent('Summary');
    expect(tabs[1]).toHaveTextContent('Timeline');
    // the log uses the house data-table style
    expect(container.querySelector('table.data-table')).toBeTruthy();
  });

  it('renders the Summary tab as a day-grouped milestone log', async () => {
    api.get.mockImplementation((url) => {
      if (url.startsWith('/api/jobs/5/history/')) return Promise.resolve({ results: [
        { id: 4, entry_type: 'action', object_type: 'job', object_id: 5,
          username: null, timestamp: '2026-01-06T09:30:00',
          changes: { status: { old: 'submitted', new: 'approved' }, _action: 'Approved via customer link' },
          source_label: 'Job JOB-2025-0005', source_link: '#/jobs/5' },
        { id: 3, entry_type: 'audit', object_type: 'estimate', object_id: 9,
          username: 'rae', timestamp: '2026-01-05T14:00:00',
          changes: { status: { old: 'draft', new: 'open' } },
          source_label: 'Estimate EST-2025-0001', source_link: null },
        { id: 2, entry_type: 'audit', object_type: 'job', object_id: 5,
          username: 'rae', timestamp: '2026-01-05T10:00:00',
          changes: { name: { old: 'a', new: 'b' } },
          source_label: 'Job JOB-2025-0005', source_link: '#/jobs/5' },
        { id: 1, entry_type: 'audit', object_type: 'estimate', object_id: 9,
          username: 'rae', timestamp: '2026-01-05T09:00:00',
          changes: { _created: true },
          source_label: 'Estimate EST-2025-0001', source_link: null },
      ] });
      return Promise.resolve({ results: [] });
    });
    const { container, findByRole, getByRole, getByText, queryByText } =
      render(JobHistorySection, { props: { job: JOB } });
    await findByRole('heading', { name: 'History' });
    // three milestone rows; the name edit contributes none
    expect(container.querySelectorAll('tr.log-row').length).toBe(3);
    expect(queryByText('name')).toBeNull();
    // day-break rows (regex so a future non-current-year suffix still matches)
    expect(getByText(/Tuesday, January 6/)).toBeInTheDocument();
    expect(getByText(/Monday, January 5/)).toBeInTheDocument();
    // verb table ("sent"), _action preference, and a creation row
    expect(getByText('sent')).toBeInTheDocument();
    expect(getByText('Approved via customer link')).toBeInTheDocument();
    expect(getByText('created')).toBeInTheDocument();
    // system entry renders an em-dash actor
    expect(getByText('—')).toBeInTheDocument();
  });

  it('shows an empty state on the Summary tab when no milestones exist', async () => {
    api.get.mockResolvedValue({ results: [
      { id: 1, entry_type: 'note', object_type: 'job', object_id: 5,
        username: 'rae', timestamp: '2026-01-05T09:00:00', text: 'Customer called',
        changes: null, source_label: 'Job JOB-2025-0005', source_link: null },
    ] });
    const { findByRole, getByText } =
      render(JobHistorySection, { props: { job: JOB } });
    await findByRole('heading', { name: 'History' });
    expect(getByText('No milestones yet.')).toBeInTheDocument();
  });

  it('posts a note then reloads', async () => {
    api.get.mockResolvedValue({ results: [] });
    api.post.mockResolvedValue({});
    const { findByRole, getByPlaceholderText, getByRole } =
      render(JobHistorySection, { props: { job: JOB } });
    await findByRole('heading', { name: 'History' });
    await fireEvent.click(getByRole('button', { name: 'Timeline' }));
    await fireEvent.input(getByPlaceholderText('Add a note…'), { target: { value: 'Hello' } });
    await fireEvent.click(getByRole('button', { name: 'Add Note' }));
    expect(api.post).toHaveBeenCalledWith('/api/jobs/5/notes/', { text: 'Hello' });
  });

  it('notifies the parent to refresh the job after a note is added', async () => {
    api.get.mockResolvedValue({ results: [] });
    api.post.mockResolvedValue({});
    const onJobChange = vi.fn();
    const { findByRole, getByPlaceholderText, getByRole } =
      render(JobHistorySection, { props: { job: JOB, onJobChange } });
    await findByRole('heading', { name: 'History' });
    await fireEvent.click(getByRole('button', { name: 'Timeline' }));
    await fireEvent.input(getByPlaceholderText('Add a note…'), { target: { value: 'Hello' } });
    await fireEvent.click(getByRole('button', { name: 'Add Note' }));
    await waitFor(() => { expect(onJobChange).toHaveBeenCalled(); });
  });

  it('shows an operation error under the note form when the post fails', async () => {
    api.get.mockResolvedValue({ results: [] });
    api.post.mockRejectedValue(Object.assign(new Error('Request failed'), {
      status: 400, data: { detail: 'Notes are locked.' },
    }));
    const { findByRole, getByPlaceholderText, getByRole } =
      render(JobHistorySection, { props: { job: JOB } });
    await findByRole('heading', { name: 'History' });
    await fireEvent.click(getByRole('button', { name: 'Timeline' }));
    await fireEvent.input(getByPlaceholderText('Add a note…'), { target: { value: 'Hello' } });
    await fireEvent.click(getByRole('button', { name: 'Add Note' }));
    expect(await findByRole('alert')).toHaveTextContent('Notes are locked.');
  });

  it('shows a field error under the note form on field validation failure', async () => {
    api.get.mockResolvedValue({ results: [] });
    api.post.mockRejectedValue(Object.assign(new Error('Request failed'), {
      status: 400, data: { text: ['This field is too long.'] },
    }));
    const { findByRole, findByText, getByPlaceholderText, getByRole } =
      render(JobHistorySection, { props: { job: JOB } });
    await findByRole('heading', { name: 'History' });
    await fireEvent.click(getByRole('button', { name: 'Timeline' }));
    await fireEvent.input(getByPlaceholderText('Add a note…'), { target: { value: 'Hello' } });
    await fireEvent.click(getByRole('button', { name: 'Add Note' }));
    expect(await findByText('This field is too long.')).toBeInTheDocument();
  });
});

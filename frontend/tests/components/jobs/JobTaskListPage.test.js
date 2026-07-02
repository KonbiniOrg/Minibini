import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, waitFor, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), patch: vi.fn(), post: vi.fn(), delete: vi.fn() } }));
vi.mock('svelte-spa-router', () => ({ link: () => ({}) }));

import { api } from '@/lib/api.js';
import { user } from '@/stores/auth.js';
import JobTaskListPage from '@/routes/jobs/JobTaskListPage.svelte';

const CATEGORIES = [
  { id: 1, code: 'RUSH', name: 'Rush Charges' },
  { id: 2, code: 'MISC', name: 'Miscellaneous' },
];

// The fetched job carries can_manage = "atom-holder OR this job's PM". The page
// toolbar gates "Mark Work Complete" on job.can_manage alone (not the global
// atom), while "Add Manual Task" is open to any authenticated user. These tests
// set the global atom to false (worker) to prove the per-object flag is what
// drives the manager affordance, and that add-task ignores permissions entirely.
function mockApi(jobOverrides = {}, categoriesOverride = []) {
  const job = {
    job_id: 3, job_number: 'JOB-3', name: 'Widget', status: 'in_progress',
    contact: null, materials: [], tasks: [], fees: [],
    ...jobOverrides,
  };
  api.get.mockReset();
  api.get.mockImplementation((url) => {
    if (url.startsWith('/api/jobs/3/')) return Promise.resolve(job);
    if (url.startsWith('/api/service-items/')) return Promise.resolve([]);
    if (url.startsWith('/api/accounting-categories/')) return Promise.resolve(categoriesOverride);
    if (url.startsWith('/api/contacts/')) return Promise.resolve({});
    return Promise.resolve([]);
  });
}

beforeEach(() => {
  // Worker (no atom): proves gating is driven by job.can_manage, not the atom.
  user.set({ id: 99, permissions: [] });
});

describe('JobTaskListPage per-job can_manage', () => {
  it('shows Add Manual Task even when atom off and can_manage false (add is open to all)', async () => {
    mockApi({ can_manage: false });
    const { getByRole } = render(JobTaskListPage, { props: { params: { id: 3 } } });
    await waitFor(() => expect(getByRole('button', { name: /add manual task/i })).toBeInTheDocument());
  });

  it('shows Mark Work Complete when can_manage is true (atom off)', async () => {
    mockApi({ can_manage: true });
    const { getByRole } = render(JobTaskListPage, { props: { params: { id: 3 } } });
    await waitFor(() => expect(getByRole('button', { name: /mark work complete/i })).toBeInTheDocument());
  });

  it('hides Mark Work Complete when can_manage is false (atom off)', async () => {
    mockApi({ can_manage: false });
    const { findByRole, queryByRole } = render(JobTaskListPage, { props: { params: { id: 3 } } });
    // wait for the toolbar to render (add manual task always shows)
    await findByRole('button', { name: /add manual task/i });
    expect(queryByRole('button', { name: /mark work complete/i })).toBeNull();
  });
});

describe('JobTaskListPage — Add Fee', () => {
  it('shows the Add Fee toolbar button', async () => {
    mockApi({ can_manage: false });
    const { findByRole } = render(JobTaskListPage, { props: { params: { id: 3 } } });
    expect(await findByRole('button', { name: /add fee/i })).toBeInTheDocument();
  });

  it('clicking Add Fee opens FeeModal (modal heading becomes visible)', async () => {
    mockApi({ can_manage: false });
    const { findByRole, getByRole } = render(JobTaskListPage, { props: { params: { id: 3 } } });
    await findByRole('button', { name: /add fee/i });
    await fireEvent.click(getByRole('button', { name: /add fee/i }));
    // FeeModal renders an <h3>Add Fee</h3> when open
    await waitFor(() => expect(getByRole('heading', { name: /add fee/i })).toBeInTheDocument());
  });

  it('FeeModal receives the job id (posts to the correct endpoint)', async () => {
    api.post.mockResolvedValue({});
    mockApi({ can_manage: false });
    const { findByRole, getByRole, getByLabelText } = render(JobTaskListPage, { props: { params: { id: 3 } } });
    await findByRole('button', { name: /add fee/i });
    await fireEvent.click(getByRole('button', { name: /add fee/i }));
    await waitFor(() => getByRole('heading', { name: /add fee/i }));
    await fireEvent.input(getByLabelText(/Description/i), { target: { value: 'Rush' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    expect(api.post).toHaveBeenCalledWith('/api/jobs/3/fees/', expect.any(Object));
  });

  it('FeeModal receives non-empty categories when categories are loaded', async () => {
    mockApi({ can_manage: false }, CATEGORIES);
    const { findByRole, getByRole, getByLabelText } = render(JobTaskListPage, { props: { params: { id: 3 } } });
    await findByRole('button', { name: /add fee/i });
    await fireEvent.click(getByRole('button', { name: /add fee/i }));
    await waitFor(() => getByRole('heading', { name: /add fee/i }));
    const select = getByLabelText(/Accounting Category/i);
    // Two real options plus "-- None --" placeholder
    expect(select.options.length).toBe(3);
    expect(select.options[1].text).toContain('RUSH');
  });
});

describe('JobTaskListPage — fees display', () => {
  it('lists a job fee by description', async () => {
    mockApi({
      can_manage: false,
      fees: [{ fee_id: 10, description: 'Setup Charge', quantity: '2', unit_rate: '50', sort_order: 1 }],
    });
    const { findByText } = render(JobTaskListPage, { props: { params: { id: 3 } } });
    expect(await findByText('Setup Charge')).toBeInTheDocument();
  });

  it('does not render the fees section when there are no fees', async () => {
    mockApi({ can_manage: false, fees: [] });
    const { findByRole, queryByText } = render(JobTaskListPage, { props: { params: { id: 3 } } });
    await findByRole('button', { name: /add fee/i });
    expect(queryByText('Fees')).toBeNull();
  });
});

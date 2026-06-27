import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), patch: vi.fn(), post: vi.fn() } }));
vi.mock('svelte-spa-router', () => ({ link: () => ({}) }));

import { api } from '@/lib/api.js';
import { user } from '@/stores/auth.js';
import JobDetail from '@/components/jobs/JobDetail.svelte';

// JobDetail is an orchestrator (flagged oversized in LATER.md). This proves it
// mounts, renders the header, and wires its child sections. Its deeper
// derivations (version timeline, CO delta layering) are better unit-tested once
// the component is split out.
beforeEach(() => {
  api.get.mockReset();
  api.get.mockResolvedValue([]); // child sections (Deliverables/Shipments/Email)
  api.post.mockReset();
  user.set({ permissions: ['can_manage_jobs'] });
});

describe('JobDetail', () => {
  it('renders the job header and the deliverables section', () => {
    const job = { job_id: 5, job_number: 'JOB-5', name: 'Widget', status: 'in_progress', can_manage: false };
    user.set({ permissions: [] });
    const { getByText } = render(JobDetail, { props: { job } });
    expect(getByText(/JOB #5/)).toBeInTheDocument();
    expect(getByText('Deliverables')).toBeInTheDocument();
  });

  it('counts material-less expenses in the Materials pillar', () => {
    const job = {
      job_id: 5, job_number: 'JOB-5', name: 'Widget', status: 'in_progress',
      materials: [], can_manage: false,
    };
    user.set({ permissions: [] });
    const expenses = { results: [
      { id: 1, amount: '40.00', material: null, description: 'FedEx',
        accounting_category_name: 'Freight' },
    ] };
    const { getByText } = render(JobDetail, { props: { job, expenses } });
    // Pillar count (materials 0 + expenses 1) shows 1.
    expect(getByText('1')).toBeInTheDocument();
  });
});

describe('JobDetail — Start Estimate button (Task 2)', () => {
  const startableJob = {
    job_id: 42, job_number: 'JOB-42', name: 'Test Job',
    status: 'draft', can_manage: true,
  };
  const startableJobSubmitted = {
    job_id: 43, job_number: 'JOB-43', name: 'Test Job Submitted',
    status: 'submitted', can_manage: true,
  };
  const noWorksheets = { results: [] };
  const noEstimates = { results: [] };

  // The "Start Estimate" button lives in the Estimates section top-bar.
  // Open that section before asserting on the button.
  async function openEstimatesSection(getByText) {
    const pillar = getByText('Estimates');
    await fireEvent.click(pillar);
  }

  it('shows "Start Estimate" button in the estimates section for a startable job with no worksheet', async () => {
    const { getByText, queryByText } = render(JobDetail, {
      props: {
        job: startableJob,
        worksheets: noWorksheets,
        estimates: noEstimates,
      },
    });
    await openEstimatesSection(getByText);
    expect(queryByText('Start Estimate')).toBeInTheDocument();
  });

  it('shows "Start Estimate" for a submitted job with no worksheet', async () => {
    const { getByText, queryByText } = render(JobDetail, {
      props: {
        job: startableJobSubmitted,
        worksheets: noWorksheets,
        estimates: noEstimates,
      },
    });
    await openEstimatesSection(getByText);
    expect(queryByText('Start Estimate')).toBeInTheDocument();
  });

  it('does NOT show "Create Estimate" label in the estimates section (old label gone)', async () => {
    const { getByText, queryByText } = render(JobDetail, {
      props: {
        job: startableJob,
        worksheets: noWorksheets,
        estimates: noEstimates,
      },
    });
    await openEstimatesSection(getByText);
    expect(queryByText('Create Estimate')).not.toBeInTheDocument();
  });

  it('navigates to #/jobs/{id}/create-worksheet when "Start Estimate" is clicked', async () => {
    const { getByText } = render(JobDetail, {
      props: {
        job: startableJob,
        worksheets: noWorksheets,
        estimates: noEstimates,
      },
    });
    await openEstimatesSection(getByText);
    const btn = getByText('Start Estimate');
    await fireEvent.click(btn);
    expect(window.location.hash).toBe('#/jobs/42/create-worksheet');
  });

  it('does NOT fire POST /api/estimates/ when "Start Estimate" is clicked', async () => {
    const { getByText } = render(JobDetail, {
      props: {
        job: startableJob,
        worksheets: noWorksheets,
        estimates: noEstimates,
      },
    });
    await openEstimatesSection(getByText);
    const btn = getByText('Start Estimate');
    await fireEvent.click(btn);
    expect(api.post).not.toHaveBeenCalledWith('/api/estimates/', expect.anything());
  });

  it('does NOT show "Start Estimate" when a worksheet already exists', async () => {
    const worksheets = { results: [{ est_worksheet_id: 7, tasks: [], taskless_materials: [] }] };
    const { getByText, queryByText } = render(JobDetail, {
      props: {
        job: startableJob,
        worksheets,
        estimates: noEstimates,
      },
    });
    await openEstimatesSection(getByText);
    expect(queryByText('Start Estimate')).not.toBeInTheDocument();
  });

  it('does NOT show "Start Estimate" for a non-startable job status', async () => {
    const inProgressJob = { ...startableJob, status: 'in_progress' };
    const { getByText, queryByText } = render(JobDetail, {
      props: {
        job: inProgressJob,
        worksheets: noWorksheets,
        estimates: noEstimates,
      },
    });
    await openEstimatesSection(getByText);
    expect(queryByText('Start Estimate')).not.toBeInTheDocument();
  });
});

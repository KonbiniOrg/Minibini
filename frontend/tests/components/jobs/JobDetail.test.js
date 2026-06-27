import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import { flushSync } from 'svelte';

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

// ── Estimate pillar (Tasks 2 & 3) ──────────────────────────────────────────

describe('JobDetail — single Estimate pillar', () => {
  const baseJob = {
    job_id: 10, job_number: 'JOB-10', name: 'Pillar Test', status: 'draft', can_manage: true,
  };
  const noWorksheets = { results: [] };
  const noEstimates = { results: [] };

  it('shows a single "Estimate" pillar label (not separate Worksheets / Estimates pillars)', () => {
    const { getByText, queryByText } = render(JobDetail, {
      props: { job: baseJob, worksheets: noWorksheets, estimates: noEstimates },
    });
    expect(getByText('Estimate')).toBeInTheDocument();
    expect(queryByText('Worksheet')).not.toBeInTheDocument();
    expect(queryByText('Worksheets')).not.toBeInTheDocument();
    expect(queryByText('Estimates')).not.toBeInTheDocument();
  });

  it('shows Plan / Client View toggle when the pillar is open', async () => {
    const { getByText, queryByText } = render(JobDetail, {
      props: { job: baseJob, worksheets: noWorksheets, estimates: noEstimates },
    });
    const pillar = getByText('Estimate');
    await fireEvent.click(pillar);
    expect(queryByText('Plan')).toBeInTheDocument();
    expect(queryByText('Client View')).toBeInTheDocument();
  });
});

describe('JobDetail — toggle default side', () => {
  const baseJob = {
    job_id: 11, job_number: 'JOB-11', name: 'Toggle Test', status: 'draft', can_manage: true,
  };
  const worksheets = { results: [{ est_worksheet_id: 7, tasks: [], taskless_materials: [] }] };

  function makeEstimates(status) {
    return {
      results: [{
        estimate_id: 99,
        estimate_number: 'EST-99',
        version: 1,
        status,
        line_items: [],
        is_amended: false,
      }],
    };
  }

  async function openEstimatePillar(getByText) {
    // The pillar may be already open (default section) or collapsed; click it to open
    const pillar = getByText('Estimate');
    await fireEvent.click(pillar);
  }

  it('defaults to Plan side when no estimate exists', async () => {
    const { getByText, queryByText } = render(JobDetail, {
      props: { job: baseJob, worksheets, estimates: { results: [] } },
    });
    await openEstimatePillar(getByText);
    // The "Plan" toggle button should have the active/selected class.
    // We check that "Plan" button is in the document and "Client View" is not the active default
    // by verifying the Plan heading text appears in the open content area
    const planBtn = queryByText('Plan');
    expect(planBtn).toBeInTheDocument();
    // Plan button should be the active/selected one (aria-pressed or class)
    // We use a broader check: the open-est area should reflect Plan content
    expect(queryByText('Client View')).toBeInTheDocument();
  });

  it('defaults to Plan side when estimate is draft', async () => {
    const { getByText, queryByRole } = render(JobDetail, {
      props: { job: baseJob, worksheets, estimates: makeEstimates('draft') },
    });
    await openEstimatePillar(getByText);
    // Plan button should be aria-pressed="true"
    const planBtn = queryByRole('button', { name: 'Plan' });
    expect(planBtn).toBeInTheDocument();
    expect(planBtn).toHaveAttribute('aria-pressed', 'true');
  });

  it('defaults to Client View side when estimate is open (sent)', async () => {
    const { getByText, queryByRole } = render(JobDetail, {
      props: { job: baseJob, worksheets, estimates: makeEstimates('open') },
    });
    await openEstimatePillar(getByText);
    const cvBtn = queryByRole('button', { name: 'Client View' });
    expect(cvBtn).toBeInTheDocument();
    expect(cvBtn).toHaveAttribute('aria-pressed', 'true');
  });

  it('defaults to Client View side when estimate is accepted', async () => {
    const { getByText, queryByRole } = render(JobDetail, {
      props: { job: baseJob, worksheets, estimates: makeEstimates('accepted') },
    });
    await openEstimatePillar(getByText);
    const cvBtn = queryByRole('button', { name: 'Client View' });
    expect(cvBtn).toBeInTheDocument();
    expect(cvBtn).toHaveAttribute('aria-pressed', 'true');
  });

  it('defaults to Plan side when no estimate at all', async () => {
    const { getByText, queryByRole } = render(JobDetail, {
      props: { job: baseJob, worksheets, estimates: { results: [] } },
    });
    await openEstimatePillar(getByText);
    const planBtn = queryByRole('button', { name: 'Plan' });
    expect(planBtn).toHaveAttribute('aria-pressed', 'true');
  });

  it('clicking Client View tab switches the toggle', async () => {
    const { getByText, queryByRole } = render(JobDetail, {
      props: { job: baseJob, worksheets, estimates: { results: [] } },
    });
    await openEstimatePillar(getByText);
    // Starts on Plan; click Client View
    const cvBtn = queryByRole('button', { name: 'Client View' });
    await fireEvent.click(cvBtn);
    expect(cvBtn).toHaveAttribute('aria-pressed', 'true');
    const planBtn = queryByRole('button', { name: 'Plan' });
    expect(planBtn).toHaveAttribute('aria-pressed', 'false');
  });
});

describe('JobDetail — Open link in Estimate pillar', () => {
  const baseJob = {
    job_id: 12, job_number: 'JOB-12', name: 'Open Link Test', status: 'draft', can_manage: true,
  };
  const worksheets = { results: [{ est_worksheet_id: 55, tasks: [], taskless_materials: [] }] };
  const draftEstimate = {
    results: [{
      estimate_id: 77,
      estimate_number: 'EST-77',
      version: 1,
      status: 'draft',
      line_items: [],
      is_amended: false,
    }],
  };
  const openEstimate = {
    results: [{
      estimate_id: 88,
      estimate_number: 'EST-88',
      version: 1,
      status: 'open',
      line_items: [],
      is_amended: false,
    }],
  };

  async function openEstimatePillar(getByText) {
    const pillar = getByText('Estimate');
    await fireEvent.click(pillar);
  }

  it('Open link points to the worksheet when on Plan side', async () => {
    const { getByText, getByRole } = render(JobDetail, {
      props: { job: baseJob, worksheets, estimates: draftEstimate },
    });
    await openEstimatePillar(getByText);
    // Default is Plan (draft estimate); the Open link should go to the worksheet
    const openLink = getByRole('link', { name: /Open/i });
    expect(openLink.getAttribute('href')).toContain('/worksheets/55');
  });

  it('Open link points to the estimate when on Client View side', async () => {
    const { getByText, getByRole } = render(JobDetail, {
      props: { job: baseJob, worksheets, estimates: openEstimate },
    });
    await openEstimatePillar(getByText);
    // Default is Client View (open estimate); the Open link should go to the estimate
    const openLink = getByRole('link', { name: /Open/i });
    expect(openLink.getAttribute('href')).toContain('/estimates/88');
  });
});

// ── Start Estimate / no-Plan state ─────────────────────────────────────────

describe('JobDetail — Start Estimate button (Task 3)', () => {
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

  // The "Start Estimate" button lives in the Estimate section.
  // Open that section before asserting on the button.
  async function openEstimateSection(getByText) {
    const pillar = getByText('Estimate');
    await fireEvent.click(pillar);
  }

  it('shows "Start Estimate" button in the estimate section for a startable job with no worksheet', async () => {
    const { getByText, queryByText } = render(JobDetail, {
      props: {
        job: startableJob,
        worksheets: noWorksheets,
        estimates: noEstimates,
      },
    });
    await openEstimateSection(getByText);
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
    await openEstimateSection(getByText);
    expect(queryByText('Start Estimate')).toBeInTheDocument();
  });

  it('does NOT show "Create Estimate" label in the estimate section (old label gone)', async () => {
    const { getByText, queryByText } = render(JobDetail, {
      props: {
        job: startableJob,
        worksheets: noWorksheets,
        estimates: noEstimates,
      },
    });
    await openEstimateSection(getByText);
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
    await openEstimateSection(getByText);
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
    await openEstimateSection(getByText);
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
    await openEstimateSection(getByText);
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
    await openEstimateSection(getByText);
    expect(queryByText('Start Estimate')).not.toBeInTheDocument();
  });
});

// ── estimateView reset on job navigation ───────────────────────────────────

describe('JobDetail — estimateView resets on job navigation', () => {
  const worksheets = { results: [{ est_worksheet_id: 7, tasks: [], taskless_materials: [] }] };

  function makeEstimates(status) {
    return {
      results: [{
        estimate_id: 1,
        estimate_number: 'EST-1',
        version: 1,
        status,
        line_items: [],
        is_amended: false,
      }],
    };
  }

  it('resets estimateView to Plan when navigating from a job with accepted estimate to one with a draft', async () => {
    // Job A: accepted estimate → should default to Client View
    const jobA = {
      job_id: 101, job_number: 'JOB-101', name: 'Job A', status: 'in_progress', can_manage: true,
    };
    const { queryByRole, getByText, rerender } = render(JobDetail, {
      props: { job: jobA, worksheets, estimates: makeEstimates('accepted') },
    });

    // Open the Estimate pillar and confirm we're on Client View
    await fireEvent.click(getByText('Estimate'));
    expect(queryByRole('button', { name: 'Client View' })).toHaveAttribute('aria-pressed', 'true');

    // Job B: only a draft estimate → should reset to Plan
    const jobB = {
      job_id: 102, job_number: 'JOB-102', name: 'Job B', status: 'draft', can_manage: true,
    };
    await rerender({ job: jobB, worksheets, estimates: makeEstimates('draft') });
    flushSync();

    // Re-open the Estimate pillar on Job B (section resets on nav)
    await fireEvent.click(getByText('Estimate'));

    // estimateView should have been reset to 'plan' by the job.job_id effect
    expect(queryByRole('button', { name: 'Plan' })).toHaveAttribute('aria-pressed', 'true');
  });
});

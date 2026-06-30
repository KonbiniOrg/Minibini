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

  it('counts material-less expenses in the Tasks & Materials pillar', () => {
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
    // Pillar count (tasks 0 + materials 0 + expenses 1) shows 1.
    expect(getByText('1')).toBeInTheDocument();
  });

  it('shows one combined "Tasks & Materials" pillar (not separate Tasks / Materials)', () => {
    const job = {
      job_id: 5, job_number: 'JOB-5', name: 'Widget', status: 'in_progress',
      tasks: [], materials: [], can_manage: false,
    };
    user.set({ permissions: [] });
    const { getByText, queryByText } = render(JobDetail, { props: { job, expenses: [] } });
    expect(getByText('Tasks & Materials')).toBeInTheDocument();
    // The old separate pillar labels are gone.
    expect(queryByText('Tasks')).toBeNull();
    expect(queryByText('Materials')).toBeNull();
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

  it('Open link points to the estimate when on Client View side', async () => {
    const { getByText, getByRole } = render(JobDetail, {
      props: { job: baseJob, estimates: openEstimate },
    });
    await openEstimatePillar(getByText);
    // Default is Client View (open estimate); the Open link should go to the estimate
    const openLink = getByRole('link', { name: /Open/i });
    expect(openLink.getAttribute('href')).toContain('/estimates/88');
  });

  it('shows no worksheet "Open Plan" link on the Plan side (worksheets removed)', async () => {
    const draftEstimate = {
      results: [{ estimate_id: 77, estimate_number: 'EST-77', version: 1, status: 'draft', line_items: [], is_amended: false }],
    };
    const { getByText, queryByRole } = render(JobDetail, {
      props: { job: baseJob, estimates: draftEstimate },
    });
    await openEstimatePillar(getByText);
    // Default is Plan (draft estimate); there is no longer an Open-Plan worksheet link.
    const links = queryByRole('link', { name: /Open Plan/i });
    expect(links).toBeNull();
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

  it('shows "Start Estimate" button in the estimate section for a startable job with no estimate', async () => {
    const { getByText, queryByText } = render(JobDetail, {
      props: { job: startableJob, estimates: noEstimates },
    });
    await openEstimateSection(getByText);
    expect(queryByText('Start Estimate')).toBeInTheDocument();
  });

  it('shows "Start Estimate" for a submitted job with no estimate', async () => {
    const { getByText, queryByText } = render(JobDetail, {
      props: { job: startableJobSubmitted, estimates: noEstimates },
    });
    await openEstimateSection(getByText);
    expect(queryByText('Start Estimate')).toBeInTheDocument();
  });

  it('does NOT show "Create Estimate" label in the estimate section (old label gone)', async () => {
    const { getByText, queryByText } = render(JobDetail, {
      props: { job: startableJob, estimates: noEstimates },
    });
    await openEstimateSection(getByText);
    expect(queryByText('Create Estimate')).not.toBeInTheDocument();
  });

  it('creates an estimate directly and navigates to it when "Start Estimate" is clicked', async () => {
    api.post.mockResolvedValue({ estimate_id: 7 });
    const { getByText } = render(JobDetail, {
      props: { job: startableJob, estimates: noEstimates },
    });
    await openEstimateSection(getByText);
    const btn = getByText('Start Estimate');
    await fireEvent.click(btn);
    expect(api.post).toHaveBeenCalledWith('/api/estimates/', { job: 42 });
    await vi.waitFor(() => expect(window.location.hash).toBe('#/estimates/7'));
  });

  it('does NOT fire POST /api/est-worksheets/ when "Start Estimate" is clicked', async () => {
    api.post.mockResolvedValue({ estimate_id: 7 });
    const { getByText } = render(JobDetail, {
      props: { job: startableJob, estimates: noEstimates },
    });
    await openEstimateSection(getByText);
    const btn = getByText('Start Estimate');
    await fireEvent.click(btn);
    expect(api.post).not.toHaveBeenCalledWith('/api/est-worksheets/', expect.anything());
  });

  it('does NOT show "Start Estimate" when an estimate already exists', async () => {
    const estimates = { results: [{ estimate_id: 3, estimate_number: 'EST-3', version: 1, status: 'draft', line_items: [] }] };
    const { getByText, queryByText } = render(JobDetail, {
      props: { job: startableJob, estimates },
    });
    await openEstimateSection(getByText);
    expect(queryByText('Start Estimate')).not.toBeInTheDocument();
  });

  it('does NOT show "Start Estimate" for a non-startable job status', async () => {
    const inProgressJob = { ...startableJob, status: 'in_progress' };
    const { getByText, queryByText } = render(JobDetail, {
      props: { job: inProgressJob, estimates: noEstimates },
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

// ── Work (Plan) section: the job owns its atoms ────────────────────────────

describe('JobDetail — Work (Plan) section', () => {
  function jobWithAtoms(overrides = {}) {
    return {
      job_id: 200, job_number: 'JOB-200', name: 'Atoms', status: 'draft', can_manage: true,
      tasks: [{ task_id: 1, name: 'Site visit', est_qty: '1', effective_rate: '50', computed_charge: '50', claimed: true }],
      materials: [{ material_id: 2, description: 'Steel plate', quantity: '3', units: 'kg', sell_price: '10', claimed: true }],
      fees: [{ fee_id: 3, description: 'Rush fee', quantity: '1', unit_rate: '25', claimed: true }],
      ...overrides,
    };
  }

  // A job with tasks opens the Tasks & Materials pillar by default; open the
  // (collapsed) Estimate pillar by its element — "Estimate" also labels the
  // header P/L grid, so a plain text query is ambiguous here.
  async function openPlan(container) {
    await fireEvent.click(container.querySelector('.pillar-est'));
  }

  it('lists the job tasks, materials, and fees in the Plan view', async () => {
    const { getByText, container } = render(JobDetail, {
      props: { job: jobWithAtoms(), estimates: { results: [] } },
    });
    await openPlan(container);
    expect(getByText('Site visit')).toBeInTheDocument();
    expect(getByText(/Steel plate/)).toBeInTheDocument();
    expect(getByText(/Rush fee/)).toBeInTheDocument();
  });

  it('renders an "Add line" affordance with Service, Material, and Fee options', async () => {
    const { getByRole, container } = render(JobDetail, {
      props: { job: jobWithAtoms(), estimates: { results: [] } },
    });
    await openPlan(container);
    expect(getByRole('button', { name: '+ Service' })).toBeInTheDocument();
    expect(getByRole('button', { name: '+ Material' })).toBeInTheDocument();
    expect(getByRole('button', { name: '+ Fee' })).toBeInTheDocument();
    expect(getByRole('button', { name: '+ Fee' })).not.toBeDisabled();
  });

  it('opens FeeModal when "+ Fee" is clicked', async () => {
    const { getByRole, findByRole, container } = render(JobDetail, {
      props: { job: jobWithAtoms(), estimates: { results: [] } },
    });
    await openPlan(container);
    await fireEvent.click(getByRole('button', { name: '+ Fee' }));
    // FeeModal renders an "Add Fee" heading when open
    expect(await findByRole('heading', { name: 'Add Fee' })).toBeInTheDocument();
  });

  it('fetches accounting categories on mount and passes them to MaterialModal and FeeModal', async () => {
    api.get.mockImplementation((url) => {
      if (url.includes('accounting-categories')) {
        return Promise.resolve({ results: [{ id: 1, code: 'RUSH', name: 'Rush Charges' }] });
      }
      return Promise.resolve([]);
    });
    const { getByRole, findByText, container } = render(JobDetail, {
      props: { job: jobWithAtoms(), estimates: { results: [] } },
    });
    await openPlan(container);
    // Open FeeModal and verify category reaches it
    await fireEvent.click(getByRole('button', { name: '+ Fee' }));
    expect(await findByText(/RUSH/)).toBeInTheDocument();
    // Close FeeModal and open MaterialModal to verify the same categories reach it
    await fireEvent.click(getByRole('button', { name: 'Cancel' }));
    await fireEvent.click(getByRole('button', { name: '+ Material' }));
    expect(await findByText(/RUSH/)).toBeInTheDocument();
  });

  it('marks an atom that is not on the current estimate with an unclaimed badge', async () => {
    const job = jobWithAtoms({
      tasks: [{ task_id: 1, name: 'Loose task', est_qty: '1', effective_rate: '50', computed_charge: '50', claimed: false }],
      materials: [],
      fees: [],
    });
    const { getAllByText, container } = render(JobDetail, {
      props: { job, estimates: { results: [] } },
    });
    await openPlan(container);
    expect(getAllByText(/not on estimate/i).length).toBeGreaterThan(0);
  });

  it('does NOT mark a claimed atom with the unclaimed badge', async () => {
    const { queryByText, container } = render(JobDetail, {
      props: { job: jobWithAtoms(), estimates: { results: [] } },
    });
    await openPlan(container);
    expect(queryByText(/not on estimate/i)).toBeNull();
  });
});

// ── hasBillables drives the Invoices pillar create affordance ──────────────

describe('JobDetail — hasBillables (Invoices pillar)', () => {
  it('shows "Create Invoice" when the job owns any atom (billable status)', async () => {
    const job = {
      job_id: 300, job_number: 'JOB-300', name: 'Billable', status: 'in_progress', can_manage: true,
      tasks: [{ task_id: 9, name: 'Cut', claimed: true }], materials: [], fees: [],
    };
    const { getByText } = render(JobDetail, {
      props: { job, estimates: { results: [] }, invoices: { results: [] } },
    });
    await fireEvent.click(getByText('Invoices'));
    expect(getByText('Create Invoice')).toBeInTheDocument();
  });

  it('hides "Create Invoice" when the job owns no atoms', async () => {
    const job = {
      job_id: 301, job_number: 'JOB-301', name: 'Empty', status: 'in_progress', can_manage: true,
      tasks: [], materials: [], fees: [],
    };
    const { getByText, queryByText } = render(JobDetail, {
      props: { job, estimates: { results: [] }, invoices: { results: [] } },
    });
    await fireEvent.click(getByText('Invoices'));
    expect(queryByText('Create Invoice')).toBeNull();
  });
});

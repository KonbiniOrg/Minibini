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

  it('renders the estimate document with no Work / Client View toggle', async () => {
    const { getByText, queryByRole } = render(JobDetail, {
      props: { job: baseJob, worksheets: noWorksheets, estimates: noEstimates },
    });
    await fireEvent.click(getByText('Estimate'));
    // The de-toggled pillar shows only the estimate document — no toggle buttons.
    expect(queryByRole('button', { name: 'Work' })).toBeNull();
    expect(queryByRole('button', { name: 'Client View' })).toBeNull();
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

  it('Open link points to the displayed estimate document', async () => {
    const { getByText, getByRole } = render(JobDetail, {
      props: { job: baseJob, estimates: openEstimate },
    });
    await openEstimatePillar(getByText);
    // The Open link is unconditional now and points at the estimate.
    const openLink = getByRole('link', { name: /Open/i });
    expect(openLink.getAttribute('href')).toContain('/estimates/88');
  });

  it('shows no worksheet "Open Plan" link (worksheets removed)', async () => {
    const draftEstimate = {
      results: [{ estimate_id: 77, estimate_number: 'EST-77', version: 1, status: 'draft', line_items: [], is_amended: false }],
    };
    const { getByText, queryByRole } = render(JobDetail, {
      props: { job: baseJob, estimates: draftEstimate },
    });
    await openEstimatePillar(getByText);
    // There is no longer an Open-Plan worksheet link.
    const links = queryByRole('link', { name: /Open Plan/i });
    expect(links).toBeNull();
  });
});

// ── Start Estimate / no-estimate state ─────────────────────────────────────────

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

// ── Tasks & Materials pillar: read-only overview ────────────────────────────

describe('JobDetail — Tasks & Materials pillar (read-only)', () => {
  function jobWithAtoms(overrides = {}) {
    return {
      job_id: 200, job_number: 'JOB-200', name: 'Atoms', status: 'in_progress', can_manage: true,
      tasks: [{ task_id: 1, name: 'Site visit', status: 'in_progress', assignee_name: 'Alex',
                scheme_algorithm: 'elapsed_time', est_qty: '2', actual_hours: '1',
                scheme_unit_label: 'h' }],
      materials: [{ material_id: 2, description: 'Steel plate', quantity: '3', units: 'kg', sell_price: '10' }],
      fees: [{ fee_id: 3, description: 'Rush fee', quantity: '1', unit_rate: '25' }],
      ...overrides,
    };
  }

  // A job with tasks opens the Tasks & Materials pillar by default.
  it('renders the lightweight tasks table (name, assignee, time vs. estimate)', async () => {
    const { getByText, findByText, container } = render(JobDetail, {
      props: { job: jobWithAtoms(), estimates: { results: [] }, expenses: [] },
    });
    expect(await findByText('Site visit')).toBeInTheDocument();
    expect(getByText('Alex')).toBeInTheDocument();
    // elapsed_time progress text: actual / est unit
    expect(container.textContent).toContain('1.00 / 2.00');
  });

  it('renders the materials and fees read-only lists', async () => {
    const { getByText, findByText } = render(JobDetail, {
      props: { job: jobWithAtoms(), estimates: { results: [] }, expenses: [] },
    });
    expect(await findByText(/Steel plate/)).toBeInTheDocument();
    expect(getByText(/Rush fee/)).toBeInTheDocument();
  });

  it('has no add-line buttons anywhere in the overview', async () => {
    const { queryByRole } = render(JobDetail, {
      props: { job: jobWithAtoms(), estimates: { results: [] }, expenses: [] },
    });
    expect(queryByRole('button', { name: '+ Service' })).toBeNull();
    expect(queryByRole('button', { name: '+ Material' })).toBeNull();
    expect(queryByRole('button', { name: '+ Fee' })).toBeNull();
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

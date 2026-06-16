import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), patch: vi.fn() } }));
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
  user.set({ permissions: [] });
});

describe('JobDetail', () => {
  it('renders the job header and the deliverables section', () => {
    const job = { job_id: 5, job_number: 'JOB-5', name: 'Widget', status: 'in_progress' };
    const { getByText } = render(JobDetail, { props: { job } });
    expect(getByText(/JOB #5/)).toBeInTheDocument();
    expect(getByText('Deliverables')).toBeInTheDocument();
  });

  it('counts material-less expenses in the Materials pillar', () => {
    const job = {
      job_id: 5, job_number: 'JOB-5', name: 'Widget', status: 'in_progress',
      materials: [],
    };
    const expenses = { results: [
      { id: 1, amount: '40.00', material: null, description: 'FedEx',
        accounting_category_name: 'Freight' },
    ] };
    const { getByText } = render(JobDetail, { props: { job, expenses } });
    // Pillar count (materials 0 + expenses 1) shows 1.
    expect(getByText('1')).toBeInTheDocument();
  });
});

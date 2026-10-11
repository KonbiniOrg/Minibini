import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';

import PipelineColumn from '@/components/board/PipelineColumn.svelte';

function jobWith(estimate) {
  return {
    job_id: 1,
    job_number: 'JOB-1',
    name: 'Widget',
    status: 'approved',          // accepted+amended estimates live on approved jobs
    sub_status: 'awaiting-prep',
    estimates: [estimate],
  };
}

function job(id, status, sub_status, estimates = []) {
  return { job_id: id, job_number: `JOB-${id}`, name: `Job ${id}`, status, sub_status, estimates };
}

// Section headers + card numbers in DOM order, so ordering assertions read
// as one flat list.
function flow(container) {
  return Array.from(container.querySelectorAll('.section-label, .border-num'))
    .map(el => el.textContent.trim());
}

describe('PipelineColumn estimate label', () => {
  it('shows "Amended" for an accepted estimate flagged is_amended', () => {
    const { getByText } = render(PipelineColumn, {
      props: { jobs: [jobWith({
        estimate_id: 9, estimate_number: 'EST-1', status: 'accepted',
        is_amended: true, total: '100.00',
      })] },
    });
    expect(getByText('Amended')).toBeInTheDocument();
  });

  it('shows "Accepted" for an accepted estimate not amended', () => {
    const { getByText } = render(PipelineColumn, {
      props: { jobs: [jobWith({
        estimate_id: 9, estimate_number: 'EST-1', status: 'accepted',
        is_amended: false, total: '100.00',
      })] },
    });
    expect(getByText('Accepted')).toBeInTheDocument();
  });
});

describe('PipelineColumn sections', () => {
  it('groups cards by sub-status in pipeline order, each under its header', () => {
    const { container } = render(PipelineColumn, {
      props: { jobs: [
        job(1, 'approved', 'awaiting-prep'),
        job(2, 'submitted', 'awaiting-response'),
        job(3, 'draft', 'needs-scoping'),
        job(4, 'draft', 'estimating'),
        job(5, 'draft', 'needs-scoping'),
      ] },
    });
    expect(flow(container)).toEqual([
      'Inquiries', 'JOB-3', 'JOB-5',
      'Estimating', 'JOB-4',
      'Awaiting Approval', 'JOB-2',
      'Awaiting Prep', 'JOB-1',
    ]);
  });

  it('omits the header of an empty section', () => {
    const { container, queryByText } = render(PipelineColumn, {
      props: { jobs: [job(1, 'draft', 'estimating')] },
    });
    expect(flow(container)).toEqual(['Estimating', 'JOB-1']);
    expect(queryByText('Inquiries')).toBeNull();
    expect(queryByText('Awaiting Approval')).toBeNull();
    expect(queryByText('Awaiting Prep')).toBeNull();
  });

  it('tints each header with its cards\' tab color', () => {
    const { container } = render(PipelineColumn, {
      props: { jobs: [
        job(1, 'draft', 'needs-scoping'),
        job(2, 'draft', 'estimating'),
        job(3, 'submitted', 'awaiting-response'),
        job(4, 'approved', 'awaiting-prep'),
      ] },
    });
    const colors = Array.from(container.querySelectorAll('.section-divider'))
      .map(el => el.style.getPropertyValue('--section-color'));
    expect(colors).toEqual(['#64748b', '#2563eb', '#b45309', '#ca8a04']);
  });

  it('buckets a held pre-approval job by its estimates, like the backend would unheld', () => {
    const { container } = render(PipelineColumn, {
      props: { jobs: [
        job(1, 'draft', 'on-hold', [{ estimate_id: 1, status: 'open', total: '1.00' }]),
        job(2, 'draft', 'on-hold', [{ estimate_id: 2, status: 'draft', total: '1.00' }]),
        job(3, 'draft', 'on-hold'),
        job(4, 'approved', 'on-hold'),
      ] },
    });
    expect(flow(container)).toEqual([
      'Inquiries', 'JOB-3',
      'Estimating', 'JOB-2',
      'Awaiting Approval', 'JOB-1',
      'Awaiting Prep', 'JOB-4',
    ]);
  });

  it('shows the empty message when there are no jobs', () => {
    const { getByText, container } = render(PipelineColumn, { props: { jobs: [] } });
    expect(getByText('No jobs in pipeline')).toBeInTheDocument();
    expect(container.querySelectorAll('.section-divider')).toHaveLength(0);
  });
});

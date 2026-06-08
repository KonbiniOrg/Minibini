import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';

import PipelineColumn from '@/components/board/PipelineColumn.svelte';

function jobWith(estimate) {
  return {
    job_id: 1,
    job_number: 'JOB-1',
    name: 'Widget',
    status: 'approved',          // accepted+amended estimates live on approved jobs
    estimates: [estimate],
  };
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

import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import JobCard from '@/components/board/JobCard.svelte';

const baseJob = {
  job_number: 'JOB-1', name: 'Widget', contact_id: 5, contact_name: 'Acme',
  sub_status: 'estimating',
};

describe('JobCard project manager line', () => {
  it('shows "PM: <name>" on the pipeline card, in place of the status pill', () => {
    const { getByText, container } = render(JobCard, {
      props: { job: { ...baseJob, project_manager_name: 'Rachel McConnell' } },
    });
    expect(getByText('PM: Rachel McConnell')).toBeInTheDocument();
    // The status pill is gone.
    expect(container.querySelector('.card-substatus')).toBeNull();
  });

  it('shows the PM line on the in-progress hover popup too (showProgress)', () => {
    const { getByText } = render(JobCard, {
      props: {
        job: { ...baseJob, project_manager_name: 'Rachel McConnell', task_total: 2, task_completed: 1 },
        showProgress: true,
      },
    });
    expect(getByText('PM: Rachel McConnell')).toBeInTheDocument();
  });

  it('renders no PM line when there is no PM', () => {
    const { container } = render(JobCard, { props: { job: { ...baseJob } } });
    expect(container.querySelector('.pm-line')).toBeNull();
  });
});

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

describe('JobCard on-hold treatment', () => {
  it('shows an ON HOLD banner with the reason as hover text', () => {
    const { getByText } = render(JobCard, {
      props: {
        job: { ...baseJob, sub_status: 'on-hold', on_hold: true, hold_reason: 'waiting on CO' },
        showProgress: true,
      },
    });
    const banner = getByText('ON HOLD');
    expect(banner).toBeInTheDocument();
    expect(banner.title).toContain('waiting on CO');
  });

  it('renders no hold banner on an unheld card', () => {
    const { queryByText } = render(JobCard, {
      props: { job: { ...baseJob, task_total: 1, task_completed: 0 }, showProgress: true },
    });
    expect(queryByText('ON HOLD')).toBeNull();
  });
});

describe('JobCard deposit banner', () => {
  it('renders the deposit pill from deposit_state', () => {
    const { getByText } = render(JobCard, { props: { job: { ...baseJob, deposit_state: 'requested' } } });
    expect(getByText('DEP REQUESTED')).toBeInTheDocument();
  });

  it('renders the paid deposit pill from deposit_state', () => {
    const { getByText, container } = render(JobCard, { props: { job: { ...baseJob, deposit_state: 'paid' } } });
    const banner = getByText('DEP PAID');
    expect(banner).toBeInTheDocument();
    expect(container.querySelector('.deposit-banner.deposit-paid')).not.toBeNull();
  });

  it('renders no deposit banner when deposit_state is null', () => {
    const { container } = render(JobCard, { props: { job: { ...baseJob, deposit_state: null } } });
    expect(container.querySelector('.deposit-banner')).toBeNull();
  });
});

describe('JobCard pre-approval treatment', () => {
  it('marks a pre-approval card with the dashed treatment class', () => {
    const { container } = render(JobCard, {
      props: { job: { ...baseJob, pre_approval: true }, showProgress: true },
    });
    expect(container.querySelector('.job-card')).toHaveClass('pre-approval');
  });

  it('leaves normal cards untreated', () => {
    const { container } = render(JobCard, { props: { job: baseJob } });
    expect(container.querySelector('.job-card')).not.toHaveClass('pre-approval');
  });
});

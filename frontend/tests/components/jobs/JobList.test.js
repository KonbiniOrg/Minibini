import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import JobList from '@/components/jobs/JobList.svelte';

describe('JobList project manager column', () => {
  it('renders the PM name as a link to the PM-filtered list', () => {
    const jobs = [
      { job_id: 1, job_number: 'JOB-1', name: 'Alpha', status: 'draft', project_manager: 4, project_manager_name: 'Dana Doe' },
    ];
    const { getByRole } = render(JobList, { props: { jobs } });
    const link = getByRole('link', { name: 'Dana Doe' });
    expect(link).toHaveAttribute('href', '#/jobs?pm=4');
  });

  it('shows an em dash when a job has no PM', () => {
    const jobs = [{ job_id: 2, job_number: 'JOB-2', name: 'Beta', status: 'draft' }];
    const { getByText } = render(JobList, { props: { jobs } });
    expect(getByText('—')).toBeInTheDocument();
  });
});

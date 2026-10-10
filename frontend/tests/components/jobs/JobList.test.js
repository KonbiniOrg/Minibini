import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import { viewMode } from '@/stores/viewMode.js';
import JobList from '@/components/jobs/JobList.svelte';

const jobs = [
  { job_id: 1, job_number: 'JOB-1', name: 'Alpha', status: 'draft', project_manager: 4, project_manager_name: 'Dana Doe' },
  { job_id: 2, job_number: 'JOB-2', name: 'Beta', status: 'approved' },
];

beforeEach(() => viewMode.set('lite'));

describe('JobList project manager column', () => {
  it('renders the PM name as a link to the PM-filtered list', () => {
    const { getByRole } = render(JobList, { props: { jobs: [jobs[0]] } });
    const link = getByRole('link', { name: 'Dana Doe' });
    expect(link).toHaveAttribute('href', '#/jobs?pm=4');
  });

  it('shows an em dash when a job has no PM', () => {
    const { getByText } = render(JobList, { props: { jobs: [jobs[1]] } });
    expect(getByText('—')).toBeInTheDocument();
  });
});

describe('JobList row selection', () => {
  it('renders the job number as plain text when no onSelect is given', () => {
    const { queryByRole, getByText } = render(JobList, { props: { jobs } });
    expect(queryByRole('button', { name: 'JOB-1' })).toBeNull();
    expect(getByText('JOB-1')).toBeInTheDocument();
  });

  it('renders the job number as a button that calls onSelect with the job', async () => {
    const onSelect = vi.fn();
    const { getByRole } = render(JobList, { props: { jobs, onSelect } });
    await fireEvent.click(getByRole('button', { name: 'JOB-2' }));
    expect(onSelect).toHaveBeenCalledWith(jobs[1]);
  });

  it('stamps a status class on each row', () => {
    const { container } = render(JobList, { props: { jobs } });
    const trs = container.querySelectorAll('tbody tr');
    expect(trs[0].classList.contains('status-draft')).toBe(true);
    expect(trs[1].classList.contains('status-approved')).toBe(true);
  });

  it('shows "No jobs found." for an empty list', () => {
    const { getByText } = render(JobList, { props: { jobs: [] } });
    expect(getByText('No jobs found.')).toBeInTheDocument();
  });

  it('shows all four columns in both densities (no lite-content decisions in this pass)', () => {
    const headers = (c) => Array.from(c.querySelectorAll('thead th')).map((th) => th.textContent.trim());
    const { container } = render(JobList, { props: { jobs } });
    expect(headers(container)).toEqual(['Job #', 'Name', 'Status', 'PM']);
    viewMode.set('full');
    const { container: c2 } = render(JobList, { props: { jobs } });
    expect(headers(c2)).toEqual(['Job #', 'Name', 'Status', 'PM']);
  });
});

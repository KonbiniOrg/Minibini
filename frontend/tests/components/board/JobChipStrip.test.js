import { describe, it, expect } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import JobChipStrip from '@/components/board/JobChipStrip.svelte';

const JOBS = [
  { job_id: 1, job_number: 'JOB-1', name: 'Alpha', accent_color: '#fff' },
  { job_id: 2, job_number: 'JOB-2', name: 'Beta', accent_color: '#000' },
];

const chipOf = (el) => el.closest('.job-chip');

describe('JobChipStrip', () => {
  it('renders a chip per job', () => {
    const { getByText } = render(JobChipStrip, { props: { jobs: JOBS } });
    expect(getByText('Alpha')).toBeInTheDocument();
    expect(getByText('JOB-2')).toBeInTheDocument();
  });

  it('focuses a chip on click and dims the others', async () => {
    const { getByText } = render(JobChipStrip, { props: { jobs: JOBS } });
    await fireEvent.click(getByText('Alpha'));
    expect(chipOf(getByText('Alpha'))).toHaveClass('focused');
    expect(chipOf(getByText('Beta'))).toHaveClass('dimmed');
  });

  it('treats "all selected" as no filter', async () => {
    const { getByText } = render(JobChipStrip, { props: { jobs: JOBS } });
    await fireEvent.click(getByText('Alpha'));
    await fireEvent.click(getByText('Beta'));
    expect(chipOf(getByText('Alpha'))).not.toHaveClass('focused');
    expect(chipOf(getByText('Beta'))).not.toHaveClass('dimmed');
  });
});

describe('JobChipStrip PM initials', () => {
  it('renders first+last initials in black, top-right', () => {
    const jobs = [{ job_id: 9, job_number: 'JOB-9', name: 'Gamma', accent_color: '#fff', project_manager_name: 'Mary Jane Watson' }];
    const { getByText } = render(JobChipStrip, { props: { jobs } });
    const initials = getByText('MW');
    expect(initials).toBeInTheDocument();
    expect(initials).toHaveClass('chip-pm');
  });

  it('uses one letter for a single-word name', () => {
    const jobs = [{ job_id: 10, job_number: 'JOB-10', name: 'Delta', accent_color: '#fff', project_manager_name: 'Cher' }];
    const { getByText } = render(JobChipStrip, { props: { jobs } });
    expect(getByText('C')).toBeInTheDocument();
  });

  it('renders no initials element when there is no PM', () => {
    const jobs = [{ job_id: 11, job_number: 'JOB-11', name: 'Epsilon', accent_color: '#fff' }];
    const { container } = render(JobChipStrip, { props: { jobs } });
    expect(container.querySelector('.chip-pm')).toBeNull();
  });
});

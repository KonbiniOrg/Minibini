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

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';
vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn().mockResolvedValue({ results: [] }) },
  errorMessage: (e, f) => f }));
import { api } from '@/lib/api.js';
import { JOB_WS_KEY } from '@/stores/jobWorkspace.js';
import JobContextBand from '@/components/jobs/JobContextBand.svelte';

beforeEach(() => { localStorage.removeItem(JOB_WS_KEY); api.get.mockClear(); });

const job = { job_id: 3, description: 'Big build', can_manage: false };

describe('JobContextBand', () => {
  it('starts expanded by default and shows the description', async () => {
    const { getByText } = render(JobContextBand, { props: { job } });
    expect(getByText('Big build')).toBeInTheDocument();
  });

  it('fetches emails only while expanded', async () => {
    render(JobContextBand, { props: { job } });
    await waitFor(() => expect(api.get).toHaveBeenCalledWith('/api/emails/?job=3'));
  });

  it('collapse hides content, persists, and a fresh mount stays collapsed without fetching', async () => {
    const first = render(JobContextBand, { props: { job } });
    await fireEvent.click(first.getByRole('button', { name: /hide job context/i }));
    expect(first.queryByText('Big build')).toBeNull();
    first.unmount();
    api.get.mockClear();
    const second = render(JobContextBand, { props: { job } });
    expect(second.queryByText('Big build')).toBeNull();
    expect(api.get).not.toHaveBeenCalled();
  });
});

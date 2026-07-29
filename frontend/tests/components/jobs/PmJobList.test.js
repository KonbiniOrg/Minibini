import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, waitFor } from '@testing-library/svelte';

vi.mock('svelte-spa-router', () => ({ push: vi.fn() }));
vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));

import { api } from '@/lib/api.js';
import PmJobList from '@/components/jobs/PmJobList.svelte';

beforeEach(() => {
  api.get.mockReset();
});

describe('PmJobList', () => {
  it('fetches jobs filtered by the pmId prop and renders them', async () => {
    api.get.mockResolvedValue({
      count: 1,
      results: [
        { job_id: 7, job_number: 'JOB-7', name: 'Gamma', status: 'draft', project_manager: 4, project_manager_name: 'Dana Doe' },
      ],
    });
    const { getByText } = render(PmJobList, { props: { pmId: 4 } });
    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith(expect.stringContaining('project_manager=4'));
    });
    await waitFor(() => expect(getByText('JOB-7')).toBeInTheDocument());
  });

  it('omits the project_manager param when no pmId is given', async () => {
    api.get.mockResolvedValue({ count: 0, results: [] });
    render(PmJobList, { props: {} });
    await waitFor(() => expect(api.get).toHaveBeenCalled());
    expect(api.get.mock.calls[0][0]).not.toContain('project_manager');
  });

  it('renders no heading of its own — titling stays with the host page', async () => {
    api.get.mockResolvedValue({ count: 0, results: [] });
    const { container } = render(PmJobList, { props: { pmId: 4 } });
    await waitFor(() => expect(api.get).toHaveBeenCalled());
    expect(container.querySelector('h2')).toBeNull();
    expect(container.querySelector('h3')).toBeNull();
  });

  it('reports count and pmName through onLoaded', async () => {
    api.get.mockResolvedValue({
      count: 3,
      results: [
        { job_id: 7, job_number: 'JOB-7', name: 'Gamma', status: 'draft', project_manager: 4, project_manager_name: 'Dana Doe' },
      ],
    });
    const onLoaded = vi.fn();
    render(PmJobList, { props: { pmId: 4, onLoaded } });
    await waitFor(() => expect(onLoaded).toHaveBeenCalledWith({ count: 3, pmName: 'Dana Doe' }));
  });
});

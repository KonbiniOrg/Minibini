import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));

import { api } from '@/lib/api.js';
import JobPicker from '@/components/JobPicker.svelte';

beforeEach(() => {
  api.get.mockReset();
});

describe('JobPicker', () => {
  it('searches and selects a job', async () => {
    api.get.mockResolvedValue({
      results: [{ job_id: 1, job_number: 'JOB-1', description: 'widget run' }],
    });
    const { getByPlaceholderText, findByRole, getByRole } = render(JobPicker);

    await fireEvent.input(getByPlaceholderText('Search jobs…'), { target: { value: 'wid' } });
    expect(api.get).toHaveBeenCalledWith('/api/jobs/?search=wid&page_size=10');

    await fireEvent.click(await findByRole('button', { name: /JOB-1/ }));
    expect(getByRole('button', { name: 'Clear' })).toBeInTheDocument();
  });

  it('does not search for a blank query', async () => {
    const { getByPlaceholderText } = render(JobPicker);
    await fireEvent.input(getByPlaceholderText('Search jobs…'), { target: { value: '   ' } });
    expect(api.get).not.toHaveBeenCalled();
  });

  it('clears the selection back to the search input', async () => {
    api.get.mockResolvedValue({
      results: [{ job_id: 1, job_number: 'JOB-1', description: 'x' }],
    });
    const { getByPlaceholderText, findByRole, getByRole } = render(JobPicker);
    await fireEvent.input(getByPlaceholderText('Search jobs…'), { target: { value: 'j' } });
    await fireEvent.click(await findByRole('button', { name: /JOB-1/ }));

    await fireEvent.click(getByRole('button', { name: 'Clear' }));
    expect(getByPlaceholderText('Search jobs…')).toBeInTheDocument();
  });
});

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));
import { api } from '@/lib/api.js';
import JobPicker from '@/components/JobPicker.svelte';

beforeEach(() => { api.get.mockReset(); });

describe('JobPicker', () => {
  it('searches and emits the full job; value is the id', async () => {
    api.get.mockResolvedValue({ results: [{ job_id: 1, job_number: 'JOB-1', name: 'widget run' }] });
    const onSelect = vi.fn();
    const { getByPlaceholderText, findByRole } = render(JobPicker, { props: { onSelect } });
    await fireEvent.input(getByPlaceholderText('Search jobs…'), { target: { value: 'wid' } });
    await new Promise((r) => setTimeout(r, 300));
    expect(api.get).toHaveBeenCalledWith('/api/jobs/?search=wid&page_size=25');
    await fireEvent.mouseDown(await findByRole('button', { name: /JOB-1/ }));
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ job_id: 1 }));
  });

  it('excludeArchived appends exclude_archived=true; default does not', async () => {
    api.get.mockResolvedValue({ results: [] });
    const on = render(JobPicker, { props: { excludeArchived: true } });
    await fireEvent.input(on.getByPlaceholderText('Search jobs…'), { target: { value: 'a' } });
    await new Promise((r) => setTimeout(r, 300));
    expect(api.get).toHaveBeenCalledWith('/api/jobs/?search=a&page_size=25&exclude_archived=true');
    on.unmount();
    api.get.mockClear();
    const off = render(JobPicker);
    await fireEvent.input(off.getByPlaceholderText('Search jobs…'), { target: { value: 'b' } });
    await new Promise((r) => setTimeout(r, 300));
    expect(api.get).toHaveBeenCalledWith('/api/jobs/?search=b&page_size=25');
  });

  it('renders a prefilled label from selectedItem without a fetch', async () => {
    const { findByText } = render(JobPicker, {
      props: { value: 1, selectedItem: { job_id: 1, job_number: 'JOB-1', name: 'x' } },
    });
    expect(await findByText(/JOB-1/)).toBeInTheDocument();
    expect(api.get).not.toHaveBeenCalled();
  });
});

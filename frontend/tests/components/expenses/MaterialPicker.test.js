import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));

import { api } from '@/lib/api.js';
import MaterialPicker from '@/components/expenses/MaterialPicker.svelte';

beforeEach(() => {
  api.get.mockReset();
  api.get.mockImplementation((url) => {
    if (url === '/api/jobs/1/') {
      return Promise.resolve({ job_id: 1, materials: [
        { material_id: 100, description: 'Steel', quantity: 5, units: 'kg' },
      ] });
    }
    return Promise.resolve({ results: [] });
  });
});

describe('MaterialPicker', () => {
  it('prompts to choose a job when none is selected', async () => {
    const { findByText } = render(MaterialPicker, { props: { jobId: null } });
    expect(await findByText(/Choose a job above/)).toBeInTheDocument();
  });

  it('loads the chosen job materials from the jobId prop', async () => {
    const { findByText } = render(MaterialPicker, { props: { jobId: 1 } });
    expect(await findByText(/Steel/)).toBeInTheDocument();
  });

  it('queues a new material', async () => {
    const { findByText } = render(MaterialPicker, { props: { jobId: 1 } });
    await fireEvent.click(await findByText('+ Add new material'));
    expect(await findByText(/New material/)).toBeInTheDocument();
  });
});

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));

import { api } from '@/lib/api.js';
import PayrollReport from '@/components/users/PayrollReport.svelte';

beforeEach(() => {
  api.get.mockReset();
});

describe('PayrollReport', () => {
  it('loads and renders a worker total', async () => {
    api.get.mockResolvedValue({
      workers: [{
        user_id: 1, name: 'Sam', total_minutes: 480,
        days: [{ date: '2026-03-01', shifts: [{ start: '2026-03-01T08:00:00', end: '2026-03-01T16:00:00', minutes: 480 }] }],
      }],
    });
    const { findByText } = render(PayrollReport);
    expect(await findByText(/Sam — total 8h 0m/)).toBeInTheDocument();
  });

  it('shows the empty state', async () => {
    api.get.mockResolvedValue({ workers: [] });
    const { findByText } = render(PayrollReport);
    expect(await findByText('No shifts in range.')).toBeInTheDocument();
  });
});

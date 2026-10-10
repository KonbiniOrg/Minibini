import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() }, errorMessage: (e, fallback) => e?.message || fallback }));

import { api } from '@/lib/api.js';
import PayrollReport from '@/components/users/PayrollReport.svelte';
import { viewMode } from '@/stores/viewMode.js';

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

describe('PayrollReport — DataTable', () => {
  const headersOf = (t) => Array.from(t.querySelectorAll('thead th')).map((th) => th.textContent.trim());
  const payload = { workers: [{
    user_id: 1, name: 'Sam', total_minutes: 480,
    days: [{ date: '2026-03-01', shifts: [{ start: '2026-03-01T08:00:00', end: '2026-03-01T16:00:00', minutes: 480 }] }],
  }] };
  it('renders one Date / Shifts / Day total table per worker in both densities', async () => {
    api.get.mockResolvedValue(payload);
    viewMode.set('lite');
    const { findByText, container } = render(PayrollReport);
    await findByText(/Sam — total 8h 0m/);
    const table = container.querySelector('table.data-table');
    expect(headersOf(table)).toEqual(['Date', 'Shifts', 'Day total']);
    expect(table.querySelector('td[data-col="total"]').textContent.trim()).toBe('8h 0m');
    viewMode.set('full');
    const { findByText: f2, container: c2 } = render(PayrollReport);
    await f2(/Sam — total 8h 0m/);
    expect(headersOf(c2.querySelector('table.data-table'))).toEqual(['Date', 'Shifts', 'Day total']);
  });
});

import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import RecentLoginsList from '@/components/home/RecentLoginsList.svelte';

describe('RecentLoginsList', () => {
  it('shows the empty state and the window note', () => {
    const { getByText } = render(RecentLoginsList, { props: { logins: [], sinceDays: 5 } });
    expect(getByText('No recent logins.')).toBeInTheDocument();
    expect(getByText('(past 5 days)')).toBeInTheDocument();
  });

  it('renders logins as table rows', () => {
    const logins = [
      { timestamp: '2026-07-11T08:01:00Z', ip_address: '192.0.2.10' },
      { timestamp: '2026-07-10T07:58:00Z', ip_address: null },
    ];
    const { getByRole, getAllByRole } = render(RecentLoginsList, { props: { logins, sinceDays: 5 } });
    expect(getByRole('cell', { name: '192.0.2.10' })).toBeInTheDocument();
    // Missing IP renders a dash; header + 2 data rows.
    expect(getByRole('cell', { name: '—' })).toBeInTheDocument();
    expect(getAllByRole('row')).toHaveLength(3);
  });
});

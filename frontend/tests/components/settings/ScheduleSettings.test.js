import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), patch: vi.fn() } }));

import { api } from '@/lib/api.js';
import ScheduleSettings from '@/components/settings/ScheduleSettings.svelte';

beforeEach(() => {
  api.get.mockReset();
  api.patch.mockReset();
  api.get.mockResolvedValue({});
  api.patch.mockResolvedValue({});
});

describe('ScheduleSettings', () => {
  it('pre-fills loaded values', async () => {
    api.get.mockResolvedValue({ schedule_workday_start: '09:30' });
    const { findByDisplayValue } = render(ScheduleSettings);
    expect(await findByDisplayValue('09:30')).toBeInTheDocument();
  });

  it('saves the settings and shows a confirmation', async () => {
    const { getByRole, findByText } = render(ScheduleSettings);
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    expect(api.patch).toHaveBeenCalledWith('/api/settings/', expect.objectContaining({
      schedule_workday_start: '08:00',
    }));
    expect(await findByText('Schedule settings saved.')).toBeInTheDocument();
  });

  it('surfaces field errors from the server', async () => {
    api.patch.mockRejectedValue({ data: { schedule_horizon_days: 'Must be at most 14' } });
    const { getByRole, findByText } = render(ScheduleSettings);
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    expect(await findByText('Must be at most 14')).toBeInTheDocument();
  });

  it('loads activity_recent_days and includes it in the save payload', async () => {
    api.get.mockResolvedValue({ activity_recent_days: '7' });
    const { getByRole, findByDisplayValue } = render(ScheduleSettings);
    expect(await findByDisplayValue('7')).toBeInTheDocument();
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    expect(api.patch).toHaveBeenCalledWith('/api/settings/', expect.objectContaining({
      activity_recent_days: '7',
    }));
  });

  it('defaults activity_recent_days to 5 when absent', async () => {
    const { getByRole } = render(ScheduleSettings);
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    expect(api.patch).toHaveBeenCalledWith('/api/settings/', expect.objectContaining({
      activity_recent_days: '5',
    }));
  });

  it('surfaces a field error for activity_recent_days', async () => {
    api.patch.mockRejectedValue({ data: { activity_recent_days: 'Must be at least 1' } });
    const { getByRole, findByText } = render(ScheduleSettings);
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    expect(await findByText('Must be at least 1')).toBeInTheDocument();
  });
});

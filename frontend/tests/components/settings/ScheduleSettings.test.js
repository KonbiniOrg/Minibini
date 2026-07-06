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

const WEEK = {
  mon: [['09:30', '15:00']], tue: [['08:00', '17:00']],
  wed: [['08:00', '17:00']], thu: [['08:00', '17:00']],
  fri: [['08:00', '17:00']], sat: [], sun: [],
};

describe('ScheduleSettings', () => {
  it('pre-fills the envelope from the stored JSON string', async () => {
    api.get.mockResolvedValue({ schedule_week_envelope: JSON.stringify(WEEK) });
    const { findByDisplayValue } = render(ScheduleSettings);
    expect(await findByDisplayValue('09:30')).toBeInTheDocument();
  });

  it('saves the envelope object and shows a confirmation', async () => {
    const { getByRole, findByText } = render(ScheduleSettings);
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    expect(api.patch).toHaveBeenCalledWith('/api/settings/', expect.objectContaining({
      schedule_week_envelope: expect.objectContaining({
        mon: [['08:00', '17:00']],
        sat: [],
      }),
    }));
    expect(await findByText('Schedule settings saved.')).toBeInTheDocument();
  });

  it('falls back to the default week on unparseable stored JSON', async () => {
    api.get.mockResolvedValue({ schedule_week_envelope: 'not-json{' });
    const { getByRole } = render(ScheduleSettings);
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    expect(api.patch).toHaveBeenCalledWith('/api/settings/', expect.objectContaining({
      schedule_week_envelope: expect.objectContaining({ mon: [['08:00', '17:00']] }),
    }));
  });

  it('surfaces an envelope error from the server', async () => {
    api.patch.mockRejectedValue({ data: { schedule_week_envelope: 'mon: intervals must not overlap' } });
    const { getByRole, findByText } = render(ScheduleSettings);
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    expect(await findByText(/must not overlap/)).toBeInTheDocument();
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

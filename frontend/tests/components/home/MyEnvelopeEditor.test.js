import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), put: vi.fn() },
  errorMessage: (e, fallback) =>
    e?.data?.schedule_envelope || e?.data?.detail || e?.message || fallback,
}));

import { api } from '@/lib/api.js';
import MyEnvelopeEditor from '@/components/home/MyEnvelopeEditor.svelte';

const WEEK = {
  mon: [['07:00', '15:00']], tue: [['08:00', '17:00']],
  wed: [['08:00', '17:00']], thu: [['08:00', '17:00']],
  fri: [['08:00', '17:00']], sat: [], sun: [],
};

beforeEach(() => {
  api.get.mockReset();
  api.put.mockReset();
  api.get.mockResolvedValue({ schedule_envelope: null });
  api.put.mockResolvedValue({});
});

describe('MyEnvelopeEditor', () => {
  it('shows the shop-default placeholder when the envelope is null', async () => {
    const { findByText } = render(MyEnvelopeEditor);
    expect(await findByText(/Using the shop schedule/)).toBeInTheDocument();
  });

  it('renders the personal envelope when set', async () => {
    api.get.mockResolvedValue({ schedule_envelope: WEEK });
    const { findByDisplayValue } = render(MyEnvelopeEditor);
    expect(await findByDisplayValue('07:00')).toBeInTheDocument();
  });

  it('saves the customized envelope via the self endpoint', async () => {
    const { findByText, getByRole } = render(MyEnvelopeEditor);
    await fireEvent.click(await findByText('Customize'));
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    expect(api.put).toHaveBeenCalledWith('/api/auth/me/schedule-envelope/', {
      schedule_envelope: expect.objectContaining({ mon: [['08:00', '17:00']] }),
    });
    expect(await findByText('Schedule saved.')).toBeInTheDocument();
  });

  it('saves null after resetting to the shop default', async () => {
    api.get.mockResolvedValue({ schedule_envelope: WEEK });
    const { findByText, getByRole } = render(MyEnvelopeEditor);
    await fireEvent.click(await findByText('Use shop default'));
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    expect(api.put).toHaveBeenCalledWith('/api/auth/me/schedule-envelope/', {
      schedule_envelope: null,
    });
  });

  it('shows a server validation message on failure', async () => {
    api.put.mockRejectedValue({ data: { schedule_envelope: 'mon: intervals must not overlap' } });
    const { findByText, getByRole } = render(MyEnvelopeEditor);
    await fireEvent.click(await findByText('Customize'));
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    expect(await findByText(/must not overlap/)).toBeInTheDocument();
  });
});

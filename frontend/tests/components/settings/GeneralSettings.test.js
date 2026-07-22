import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), patch: vi.fn() } }));

import { api } from '@/lib/api.js';
import GeneralSettings from '@/components/settings/GeneralSettings.svelte';

beforeEach(() => {
  api.get.mockReset();
  api.patch.mockReset();
  api.get.mockResolvedValue({});
  api.patch.mockResolvedValue({});
});

describe('GeneralSettings', () => {
  it('pre-fills the loaded values', async () => {
    api.get.mockResolvedValue({
      est_expire_days: '30',
      average_labor_cost: '45',
      job_number_sequence: 'JOB-{year}-{counter:04d}',
    });
    const { findByDisplayValue } = render(GeneralSettings);
    expect(await findByDisplayValue('30')).toBeInTheDocument();
    expect(await findByDisplayValue('45')).toBeInTheDocument();
    expect(await findByDisplayValue('JOB-{year}-{counter:04d}')).toBeInTheDocument();
  });

  it('saves the defaults section including the average labor cost', async () => {
    const { getByRole, findByText } = render(GeneralSettings);
    await fireEvent.click(getByRole('button', { name: 'Save defaults' }));
    expect(api.patch).toHaveBeenCalledWith('/api/settings/', expect.objectContaining({
      est_expire_days: '', board_closed_retention_days: '', average_labor_cost: '',
    }));
    expect(await findByText('Defaults saved.')).toBeInTheDocument();
  });

  it('surfaces an average-labor-cost validation error from the API', async () => {
    api.patch.mockRejectedValue({ data: { average_labor_cost: 'must be a non-negative number' } });
    const { getByRole, findByText } = render(GeneralSettings);
    await fireEvent.click(getByRole('button', { name: 'Save defaults' }));
    expect(await findByText('must be a non-negative number')).toBeInTheDocument();
  });

  it('saves the numbering patterns', async () => {
    const { getByRole, findByText } = render(GeneralSettings);
    await fireEvent.click(getByRole('button', { name: 'Save numbering' }));
    expect(api.patch).toHaveBeenCalledWith('/api/settings/', expect.objectContaining({
      job_number_sequence: '', po_number_sequence: '',
    }));
    expect(await findByText('Numbering saved.')).toBeInTheDocument();
  });
});

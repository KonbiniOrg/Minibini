import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), patch: vi.fn() } }));

import { api } from '@/lib/api.js';
import BusinessSettings from '@/components/settings/BusinessSettings.svelte';

beforeEach(() => {
  api.get.mockReset();
  api.patch.mockReset();
  api.get.mockResolvedValue({});
  api.patch.mockResolvedValue({});
});

describe('BusinessSettings', () => {
  it('pre-fills the loaded email', async () => {
    api.get.mockResolvedValue({ business_email: 'office@shop.com' });
    const { findByDisplayValue } = render(BusinessSettings);
    expect(await findByDisplayValue('office@shop.com')).toBeInTheDocument();
  });

  it('saves and confirms', async () => {
    const { getByRole, findByText } = render(BusinessSettings);
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    expect(api.patch).toHaveBeenCalledWith('/api/settings/', expect.objectContaining({
      business_email: '', our_public_url: '',
    }));
    expect(await findByText('Business settings saved.')).toBeInTheDocument();
  });

  it('surfaces a general error', async () => {
    api.patch.mockRejectedValue(new Error('nope'));
    const { getByRole, findByText } = render(BusinessSettings);
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    expect(await findByText('nope')).toBeInTheDocument();
  });
});

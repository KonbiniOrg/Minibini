import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), patch: vi.fn(), post: vi.fn(), delete: vi.fn() },
  errorMessage: (e) => e?.message || 'error',
}));
vi.mock('@/stores/setupStatus.js', () => ({
  refreshSetupStatus: vi.fn(),
  setupStatus: { subscribe: (fn) => { fn({ areas: null, last_pull_at: null }); return () => {}; } },
}));
vi.mock('@/stores/messages.js', () => ({
  showError: vi.fn(), showSuccess: vi.fn(),
}));

import { api } from '@/lib/api.js';
import BusinessSettings from '@/components/settings/BusinessSettings.svelte';

beforeEach(() => {
  api.get.mockReset();
  api.patch.mockReset();
  // The tab now hosts the terms import panel + manager; route their loads.
  api.get.mockImplementation(async (url) => {
    if (url === '/api/payment-terms/') return [];
    if (url.startsWith('/api/qbo/import/suggestions/')) {
      return { dismissed: false, fetched_at: null, rows: [] };
    }
    return {};
  });
  api.patch.mockResolvedValue({});
});

describe('BusinessSettings', () => {
  it('pre-fills the loaded email', async () => {
    api.get.mockResolvedValue({ business_email: 'office@shop.com' });
    const { findByDisplayValue } = render(BusinessSettings);
    expect(await findByDisplayValue('office@shop.com')).toBeInTheDocument();
  });

  it('pre-fills and saves the email domain', async () => {
    api.get.mockResolvedValue({ our_domain: 'nealscnc.com' });
    const { findByDisplayValue } = render(BusinessSettings);
    expect(await findByDisplayValue('nealscnc.com')).toBeInTheDocument();
  });

  it('saves and confirms', async () => {
    const { getByRole, findByText } = render(BusinessSettings);
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    expect(api.patch).toHaveBeenCalledWith('/api/settings/', expect.objectContaining({
      business_email: '', our_public_url: '', our_domain: '',
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

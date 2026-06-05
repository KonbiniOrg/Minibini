import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() } }));

import { api } from '@/lib/api.js';
import RateSchemeManager from '@/components/RateSchemeManager.svelte';

const SCHEME = { rate_scheme_id: 1, name: 'Hourly', algorithm: 'elapsed_time', rate: '25', unit_label: 'hr', modifiers: [], reference_counts: {} };

beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();
  api.delete.mockReset();
  api.get.mockImplementation((url) => {
    if (url.startsWith('/api/rate-schemes/')) return Promise.resolve({ results: [SCHEME] });
    if (url === '/api/accounting-categories/') return Promise.resolve({ results: [{ id: 1, code: 'C1', name: 'Labor' }] });
    if (url === '/api/settings/units/') return Promise.resolve(['none', 'hr']);
    return Promise.resolve({ results: [] });
  });
  api.post.mockResolvedValue({});
  api.delete.mockResolvedValue({});
});

describe('RateSchemeManager', () => {
  it('loads and lists schemes', async () => {
    const { findByText } = render(RateSchemeManager);
    expect(await findByText('Hourly')).toBeInTheDocument();
  });

  it('creates a scheme', async () => {
    const { findByRole, getByLabelText, getByRole } = render(RateSchemeManager);
    await fireEvent.click(await findByRole('button', { name: 'Add Rate Scheme' }));
    await fireEvent.input(getByLabelText(/Name/), { target: { value: 'Premium' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    expect(api.post).toHaveBeenCalledWith('/api/rate-schemes/', expect.objectContaining({ name: 'Premium' }));
  });

  it('deletes an unreferenced scheme after confirmation', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    const { findByRole } = render(RateSchemeManager);
    await fireEvent.click(await findByRole('button', { name: 'Delete' }));
    expect(api.delete).toHaveBeenCalledWith('/api/rate-schemes/1/');
    confirmSpy.mockRestore();
  });
});

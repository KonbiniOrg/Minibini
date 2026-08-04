import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), patch: vi.fn() } }));
import { api } from '@/lib/api.js';
import FallbackAccountingCategorySetting
  from '@/components/settings/FallbackAccountingCategorySetting.svelte';

const cats = [
  { id: 1, name: 'Service', is_active: true, is_deposit: false },
  { id: 2, name: 'Uncategorized income', is_active: true, is_deposit: false },
  { id: 3, name: 'Old category', is_active: false, is_deposit: false },
  { id: 4, name: 'Customer Deposits', is_active: true, is_deposit: true },
];

beforeEach(() => {
  api.get.mockReset(); api.patch.mockReset();
  api.get.mockImplementation((url) =>
    url.startsWith('/api/settings/')
      ? Promise.resolve({ fallback_accounting_category: '' })
      : Promise.resolve({ results: cats }));
});

describe('FallbackAccountingCategorySetting', () => {
  it('requests the AC list with include_fallback=true so the designated category still shows', async () => {
    render(FallbackAccountingCategorySetting);
    await waitFor(() => expect(api.get).toHaveBeenCalledWith(
      '/api/accounting-categories/?include_fallback=true'));
  });

  it('lists only active, non-deposit categories', async () => {
    const { findByLabelText, queryByRole } = render(FallbackAccountingCategorySetting);
    const select = await findByLabelText(/fallback accounting category/i);
    expect(select.querySelectorAll('option')).toHaveLength(3); // None + Service + Uncategorized income
    expect(queryByRole('option', { name: 'Old category' })).toBeNull();
    expect(queryByRole('option', { name: 'Customer Deposits' })).toBeNull();
  });

  it('saves the picked category', async () => {
    api.patch.mockResolvedValue({});
    const { findByLabelText, getByRole } = render(FallbackAccountingCategorySetting);
    const select = await findByLabelText(/fallback accounting category/i);
    await fireEvent.change(select, { target: { value: '2' } });
    await fireEvent.click(getByRole('button', { name: /save/i }));
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith(
      '/api/settings/', { fallback_accounting_category: '2' }));
  });

  it('can be cleared back to none', async () => {
    api.get.mockImplementation((url) =>
      url.startsWith('/api/settings/')
        ? Promise.resolve({ fallback_accounting_category: '2' })
        : Promise.resolve({ results: cats }));
    api.patch.mockResolvedValue({});
    const { findByLabelText, getByRole } = render(FallbackAccountingCategorySetting);
    const select = await findByLabelText(/fallback accounting category/i);
    await waitFor(() => expect(select.value).toBe('2'));
    await fireEvent.change(select, { target: { value: '' } });
    await fireEvent.click(getByRole('button', { name: /save/i }));
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith(
      '/api/settings/', { fallback_accounting_category: '' }));
  });
});

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), patch: vi.fn() } }));
import { api } from '@/lib/api.js';
import DefaultDepositCategorySetting
  from '@/components/settings/DefaultDepositCategorySetting.svelte';

const cats = [
  { id: 1, name: 'Service', is_active: true, is_deposit: false },
  { id: 2, name: 'Customer Deposits', is_active: true, is_deposit: true },
  { id: 3, name: 'Old Deposits', is_active: false, is_deposit: true },
];

beforeEach(() => {
  api.get.mockReset(); api.patch.mockReset();
  api.get.mockImplementation((url) =>
    url.startsWith('/api/settings/')
      ? Promise.resolve({ default_deposit_accounting_category: '' })
      : Promise.resolve({ results: cats }));
});

describe('DefaultDepositCategorySetting', () => {
  it('lists only active deposit categories', async () => {
    const { findByLabelText, queryByRole } = render(DefaultDepositCategorySetting);
    const select = await findByLabelText(/default deposit category/i);
    expect(select.querySelectorAll('option')).toHaveLength(2); // None + Deposits
    expect(queryByRole('option', { name: 'Service' })).toBeNull();
    expect(queryByRole('option', { name: 'Old Deposits' })).toBeNull();
  });

  it('saves the picked category', async () => {
    api.patch.mockResolvedValue({});
    const { findByLabelText, getByRole } = render(DefaultDepositCategorySetting);
    const select = await findByLabelText(/default deposit category/i);
    await fireEvent.change(select, { target: { value: '2' } });
    await fireEvent.click(getByRole('button', { name: /save/i }));
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith(
      '/api/settings/', { default_deposit_accounting_category: '2' }));
  });
});

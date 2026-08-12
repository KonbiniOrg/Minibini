import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), patch: vi.fn() } }));

import { api } from '@/lib/api.js';
import FallbackCategorySetting
  from '@/components/settings/FallbackCategorySetting.svelte';

beforeEach(() => {
  api.get.mockReset(); api.patch.mockReset();
  api.get.mockImplementation((url) => {
    if (url.startsWith('/api/accounting-categories/')) {
      return Promise.resolve([
        { id: 1, name: 'Materials', is_active: true, is_deposit: false },
        { id: 2, name: 'Retired', is_active: false, is_deposit: false },
        { id: 3, name: 'Deposits', is_active: true, is_deposit: true },
      ]);
    }
    return Promise.resolve({ fallback_accounting_category: '1' });
  });
  api.patch.mockResolvedValue({});
});

describe('FallbackCategorySetting', () => {
  it('loads ALL categories (no exclusion) and the current fallback', async () => {
    const { findByLabelText, queryByText, getByText } = render(FallbackCategorySetting);
    const select = await findByLabelText(/Fallback accounting category/);
    await vi.waitFor(() => expect(select.value).toBe('1'));
    // Unlike the sibling material picker, inactive and deposit categories
    // are NOT filtered out here — the fallback-designation picker must
    // offer everything.
    expect(getByText('Retired')).toBeInTheDocument();
    expect(getByText('Deposits')).toBeInTheDocument();
    expect(queryByText('Applied to uncategorized invoice lines.')).toBeInTheDocument();
  });

  it('fetches categories without the exclude_fallback param', async () => {
    render(FallbackCategorySetting);
    await vi.waitFor(() => expect(api.get).toHaveBeenCalled());
    const catCall = api.get.mock.calls.find(([url]) => url.startsWith('/api/accounting-categories/'));
    expect(catCall[0]).not.toContain('exclude_fallback');
  });

  it('saves via PATCH /api/settings/', async () => {
    const { findByLabelText, getByRole, findByText } = render(FallbackCategorySetting);
    await findByLabelText(/Fallback accounting category/);
    await fireEvent.click(getByRole('button', { name: /Save/ }));
    await vi.waitFor(() => expect(api.patch).toHaveBeenCalledWith(
      '/api/settings/', { fallback_accounting_category: '1' }));
    await findByText('Fallback accounting category saved.');
  });

  it('surfaces a validation error from the API', async () => {
    api.patch.mockRejectedValue({
      status: 400,
      data: { fallback_accounting_category: 'must not be a deposit category' },
    });
    const { findByLabelText, getByRole, findByText, queryByText } = render(FallbackCategorySetting);
    await findByLabelText(/Fallback accounting category/);
    await fireEvent.click(getByRole('button', { name: /Save/ }));

    expect(await findByText('must not be a deposit category')).toBeInTheDocument();
    expect(queryByText('Fallback accounting category saved.')).toBeNull();
  });
});

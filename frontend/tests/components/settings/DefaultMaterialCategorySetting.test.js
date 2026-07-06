import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), patch: vi.fn() } }));

import { api } from '@/lib/api.js';
import DefaultMaterialCategorySetting
  from '@/components/settings/DefaultMaterialCategorySetting.svelte';

beforeEach(() => {
  api.get.mockReset(); api.patch.mockReset();
  api.get.mockImplementation((url) => {
    if (url.startsWith('/api/accounting-categories/')) {
      return Promise.resolve([
        { id: 1, name: 'Materials', is_active: true },
        { id: 2, name: 'Retired', is_active: false },
      ]);
    }
    return Promise.resolve({ default_material_accounting_category: '1' });
  });
  api.patch.mockResolvedValue({});
});

describe('DefaultMaterialCategorySetting', () => {
  it('loads categories (active only) and the current default', async () => {
    const { findByLabelText, queryByText } = render(DefaultMaterialCategorySetting);
    const select = await findByLabelText(/Default material category/);
    await vi.waitFor(() => expect(select.value).toBe('1'));
    expect(queryByText('Retired')).toBeNull();
  });

  it('saves via PATCH /api/settings/', async () => {
    const { findByLabelText, getByRole, findByText } = render(DefaultMaterialCategorySetting);
    await findByLabelText(/Default material category/);
    await fireEvent.click(getByRole('button', { name: /Save/ }));
    await vi.waitFor(() => expect(api.patch).toHaveBeenCalledWith(
      '/api/settings/', { default_material_accounting_category: '1' }));
    await findByText('Default material category saved.');
  });

  it('surfaces a validation error from the API', async () => {
    api.patch.mockRejectedValue({
      status: 400,
      data: { default_material_accounting_category: 'unknown or inactive category' },
    });
    const { findByLabelText, getByRole, findByText, queryByText } = render(DefaultMaterialCategorySetting);
    await findByLabelText(/Default material category/);
    await fireEvent.click(getByRole('button', { name: /Save/ }));

    expect(await findByText('unknown or inactive category')).toBeInTheDocument();
    expect(queryByText('Default material category saved.')).toBeNull();
  });
});

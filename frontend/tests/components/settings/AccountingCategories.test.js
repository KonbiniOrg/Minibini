import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() } }));

import { api } from '@/lib/api.js';
import AccountingCategories from '@/components/settings/AccountingCategories.svelte';

const CAT = { id: 1, code: 'C1', name: 'Labor', taxable: true, is_active: true, default_description: '' };
const INACTIVE_CAT = { id: 2, code: 'C2', name: 'Retired', taxable: true, is_active: false, default_description: '' };

beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();
  api.patch.mockReset();
  // categories load resolves; QBO accounts rejects → qboAccounts stays null;
  // settings load resolves with no default set unless overridden per-test.
  api.get.mockImplementation((url) => {
    if (url === '/api/accounting-categories/') return Promise.resolve({ results: [CAT, INACTIVE_CAT] });
    if (url === '/api/settings/') return Promise.resolve({});
    return Promise.reject({ status: 404 });
  });
  api.post.mockResolvedValue({});
  api.patch.mockResolvedValue({});
});

describe('AccountingCategories', () => {
  it('loads and lists categories', async () => {
    const { findByRole } = render(AccountingCategories);
    expect(await findByRole('cell', { name: 'Labor' })).toBeInTheDocument();
  });

  it('creates a new category', async () => {
    const { findByRole, getByLabelText, getByRole } = render(AccountingCategories);
    await fireEvent.click(await findByRole('button', { name: 'Add category' }));

    await fireEvent.input(getByLabelText(/Code/), { target: { value: 'C2' } });
    await fireEvent.input(getByLabelText(/Name/), { target: { value: 'Materials' } });
    await fireEvent.click(getByRole('button', { name: 'Create' }));

    expect(api.post).toHaveBeenCalledWith('/api/accounting-categories/', expect.objectContaining({
      code: 'C2', name: 'Materials',
    }));
  });

  it('edits an existing category', async () => {
    const { findByRole, getByRole } = render(AccountingCategories);
    await fireEvent.click(await findByRole('button', { name: 'Edit' }));
    await fireEvent.click(getByRole('button', { name: 'Save Changes' }));

    expect(api.patch).toHaveBeenCalledWith('/api/accounting-categories/1/', expect.objectContaining({
      name: 'Labor',
    }));
  });

  describe('default material category', () => {
    it('pre-fills the current value from settings', async () => {
      api.get.mockImplementation((url) => {
        if (url === '/api/accounting-categories/') return Promise.resolve({ results: [CAT, INACTIVE_CAT] });
        if (url === '/api/settings/') return Promise.resolve({ default_material_accounting_category: '1' });
        return Promise.reject({ status: 404 });
      });
      const { findByLabelText } = render(AccountingCategories);
      const select = await findByLabelText('Default material category');
      expect(select.value).toBe('1');
    });

    it('only lists active categories as options', async () => {
      const { findByLabelText } = render(AccountingCategories);
      const select = await findByLabelText('Default material category');
      const optionText = [...select.options].map(o => o.textContent);
      expect(optionText).toContain('Labor');
      expect(optionText).not.toContain('Retired');
    });

    it('saves the selection', async () => {
      const { findByLabelText, getByRole } = render(AccountingCategories);
      const select = await findByLabelText('Default material category');
      await fireEvent.change(select, { target: { value: '1' } });
      await fireEvent.click(getByRole('button', { name: 'Save' }));

      expect(api.patch).toHaveBeenCalledWith('/api/settings/', {
        default_material_accounting_category: '1',
      });
    });

    it('surfaces a validation error from the API', async () => {
      api.patch.mockRejectedValue({
        status: 400,
        data: { default_material_accounting_category: 'unknown or inactive category' },
      });
      const { findByLabelText, getByRole, findByText } = render(AccountingCategories);
      await findByLabelText('Default material category');
      await fireEvent.click(getByRole('button', { name: 'Save' }));

      expect(await findByText('unknown or inactive category')).toBeInTheDocument();
    });
  });
});

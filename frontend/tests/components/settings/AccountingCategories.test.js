import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, within } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() } }));

import { api } from '@/lib/api.js';
import AccountingCategories from '@/components/settings/AccountingCategories.svelte';

const CAT = { id: 1, code: 'C1', name: 'Labor', taxable: true, is_active: true, default_description: '' };
const INACTIVE_CAT = { id: 2, code: 'C2', name: 'Retired', taxable: true, is_active: false, default_description: '' };

beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();
  api.patch.mockReset();
  api.delete.mockReset();
  // categories load resolves; QBO accounts rejects → qboAccounts stays null;
  // settings load resolves with no default set unless overridden per-test.
  api.get.mockImplementation((url) => {
    if (url.startsWith('/api/accounting-categories/')) return Promise.resolve({ results: [CAT, INACTIVE_CAT] });
    if (url === '/api/settings/') return Promise.resolve({});
    return Promise.reject({ status: 404 });
  });
  api.post.mockResolvedValue({});
  api.patch.mockResolvedValue({});
  api.delete.mockResolvedValue({});
});

describe('AccountingCategories', () => {
  it('loads and lists categories', async () => {
    const { findByRole } = render(AccountingCategories);
    expect(await findByRole('cell', { name: 'Labor' })).toBeInTheDocument();
  });

  it('fetches with include_fallback=true so a designated fallback stays manageable', async () => {
    api.get.mockImplementation((url) => {
      if (url.startsWith('/api/accounting-categories/')) {
        return Promise.resolve({ results: [
          { id: 1, code: 'C1', name: 'Labor', taxable: true, is_active: true,
            default_description: '' },
          { id: 3, code: 'FALL', name: 'Fallback Category', taxable: true,
            is_active: true, is_referenced: true, default_description: '' },
        ] });
      }
      return Promise.resolve({ results: [] });
    });
    const { findByRole } = render(AccountingCategories);
    expect(await findByRole('cell', { name: 'Fallback Category' })).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith('/api/accounting-categories/?include_fallback=true');
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

  it('disables taxable and deposit checkboxes for a referenced category', async () => {
    api.get.mockImplementation((url) => {
      if (url.startsWith('/api/accounting-categories/')) {
        return Promise.resolve({ results: [
          { id: 1, code: 'SVC', name: 'Service', taxable: true,
            is_deposit: false, is_active: true, is_referenced: true,
            default_description: '', qbo_item_id: '', qbo_expense_account_id: '' },
        ] });
      }
      return Promise.resolve({ results: [] });
    });
    const { getByRole, findByRole } = render(AccountingCategories);
    await fireEvent.click(await findByRole('button', { name: /edit/i }));
    expect(getByRole('checkbox', { name: /taxable by default/i })).toBeDisabled();
    expect(getByRole('checkbox', { name: /deposit category/i })).toBeDisabled();
  });

  it('sends is_deposit on create', async () => {
    const { findByRole, getByLabelText, getByRole } = render(AccountingCategories);
    await fireEvent.click(await findByRole('button', { name: 'Add category' }));

    await fireEvent.input(getByLabelText(/Code/), { target: { value: 'C3' } });
    await fireEvent.input(getByLabelText(/Name/), { target: { value: 'Deposits' } });
    await fireEvent.click(getByRole('checkbox', { name: /deposit category/i }));
    await fireEvent.click(getByRole('button', { name: 'Create' }));

    expect(api.post).toHaveBeenCalledWith('/api/accounting-categories/', expect.objectContaining({
      code: 'C3', name: 'Deposits', is_deposit: true, taxable: false,
    }));
  });

  describe('Delete', () => {
    function mockReferencedAndUnreferenced() {
      api.get.mockImplementation((url) => {
        if (url.startsWith('/api/accounting-categories/')) {
          return Promise.resolve({ results: [
            { id: 1, code: 'REF', name: 'Referenced', taxable: true,
              is_deposit: false, is_active: true, is_referenced: true,
              default_description: '' },
            { id: 2, code: 'UNREF', name: 'Unreferenced', taxable: true,
              is_deposit: false, is_active: true, is_referenced: false,
              default_description: '' },
          ] });
        }
        return Promise.resolve({ results: [] });
      });
    }

    it('shows Delete only for unreferenced categories', async () => {
      mockReferencedAndUnreferenced();
      const { findByRole, getAllByRole, getByRole } = render(AccountingCategories);
      await findByRole('cell', { name: 'Referenced' });

      const refRow = getByRole('cell', { name: 'Referenced' }).closest('tr');
      const unrefRow = getByRole('cell', { name: 'Unreferenced' }).closest('tr');

      expect(within(refRow).queryByRole('button', { name: 'Delete' })).toBeNull();
      expect(within(unrefRow).getByRole('button', { name: 'Delete' })).toBeInTheDocument();
      // sanity: two Edit buttons total, one Delete button total
      expect(getAllByRole('button', { name: 'Edit' })).toHaveLength(2);
    });

    it('deletes on confirm accept and reloads the list', async () => {
      mockReferencedAndUnreferenced();
      vi.spyOn(window, 'confirm').mockReturnValue(true);
      const { findByRole, getByRole } = render(AccountingCategories);
      await findByRole('cell', { name: 'Unreferenced' });

      const unrefRow = getByRole('cell', { name: 'Unreferenced' }).closest('tr');
      await fireEvent.click(within(unrefRow).getByRole('button', { name: 'Delete' }));

      expect(window.confirm).toHaveBeenCalledWith(
        'Delete category "Unreferenced"? This cannot be undone.');
      expect(api.delete).toHaveBeenCalledWith('/api/accounting-categories/2/');
      // reload after delete
      expect(api.get).toHaveBeenCalledWith('/api/accounting-categories/?include_fallback=true');
    });

    it('does not call delete when confirm is cancelled', async () => {
      mockReferencedAndUnreferenced();
      vi.spyOn(window, 'confirm').mockReturnValue(false);
      const { findByRole, getByRole } = render(AccountingCategories);
      await findByRole('cell', { name: 'Unreferenced' });

      const unrefRow = getByRole('cell', { name: 'Unreferenced' }).closest('tr');
      await fireEvent.click(within(unrefRow).getByRole('button', { name: 'Delete' }));

      expect(window.confirm).toHaveBeenCalled();
      expect(api.delete).not.toHaveBeenCalled();
    });
  });
});

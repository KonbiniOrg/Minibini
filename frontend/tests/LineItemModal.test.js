import { render, fireEvent } from '@testing-library/svelte';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import LineItemModal from '../src/components/LineItemModal.svelte';

// Stub the API so save() does not hit the network.
vi.mock('../src/lib/api.js', () => ({
  api: { post: vi.fn().mockResolvedValue({}), patch: vi.fn().mockResolvedValue({}) },
}));
import { api } from '../src/lib/api.js';

const categories = [{ id: 7, name: 'Materials', code: 'MAT' }];

describe('LineItemModal — is-material marker', () => {
  beforeEach(() => { api.post.mockClear(); });

  it('checking material prefills the AC from the config default and posts is_material=true', async () => {
    const { getByLabelText, getByText } = render(LineItemModal, {
      props: {
        open: true, mode: 'create', apiBase: '/api/estimates/1',
        categories, showMaterialMarker: true, defaultMaterialCategoryId: 7,
      },
    });

    await fireEvent.input(getByLabelText(/Description/i), { target: { value: 'M77 ABS' } });
    // No manual AC selection — checking "is material" fills it from the default.
    await fireEvent.click(getByLabelText(/Is this a material/i));
    expect(getByLabelText(/Accounting Category/i)).toHaveValue('7');
    await fireEvent.click(getByText('Save'));

    expect(api.post).toHaveBeenCalledTimes(1);
    const [, payload] = api.post.mock.calls[0];
    expect(payload.is_material).toBe(true);
    expect(payload.accounting_category).toBe(7);
  });

  it('a material line does not require a manually chosen AC (default may be unset — backend fills it)', async () => {
    const { getByLabelText, getByText } = render(LineItemModal, {
      props: {
        open: true, mode: 'create', apiBase: '/api/estimates/1',
        categories, showMaterialMarker: true, defaultMaterialCategoryId: null,
      },
    });

    await fireEvent.input(getByLabelText(/Description/i), { target: { value: 'M77 ABS' } });
    await fireEvent.click(getByLabelText(/Is this a material/i));
    await fireEvent.click(getByText('Save'));

    // Not blocked on AC — the material branch defers to the backend default.
    expect(api.post).toHaveBeenCalledTimes(1);
    const [, payload] = api.post.mock.calls[0];
    expect(payload.is_material).toBe(true);
  });

  it('a fee (unchecked) still blocks save with no accounting category', async () => {
    const { getByLabelText, getByText, queryByText } = render(LineItemModal, {
      props: {
        open: true, mode: 'create', apiBase: '/api/estimates/1',
        categories, showMaterialMarker: true,
      },
    });

    await fireEvent.input(getByLabelText(/Description/i), { target: { value: 'Rush' } });
    await fireEvent.click(getByText('Save'));

    expect(api.post).not.toHaveBeenCalled();
    expect(queryByText(/Accounting Category is required/i)).not.toBeNull();
  });

  it('hides the checkbox when showMaterialMarker is false', () => {
    const { queryByLabelText } = render(LineItemModal, {
      props: {
        open: true, mode: 'create', apiBase: '/api/invoices/1',
        categories, showMaterialMarker: false,
      },
    });
    expect(queryByLabelText(/Is this a material/i)).toBeNull();
  });
});

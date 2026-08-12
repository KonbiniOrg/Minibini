import { render, fireEvent } from '@testing-library/svelte';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import LineItemModal from '../src/components/LineItemModal.svelte';

// Stub the API so save() does not hit the network.
vi.mock('../src/lib/api.js', () => ({
  api: { post: vi.fn().mockResolvedValue({}), patch: vi.fn().mockResolvedValue({}) },
}));
import { api } from '../src/lib/api.js';

const categories = [{ id: 7, name: 'Materials', code: 'MAT' }];

describe('LineItemModal — material-ness derives from the AC (RM 2026-08-11)', () => {
  beforeEach(() => { api.post.mockClear(); });

  it('offers no "Is this a material?" checkbox and posts no is_material', async () => {
    const { getByLabelText, getByText, queryByLabelText } = render(LineItemModal, {
      props: {
        open: true, mode: 'create', apiBase: '/api/estimates/1', categories,
      },
    });

    expect(queryByLabelText(/Is this a material/i)).toBeNull();

    await fireEvent.input(getByLabelText(/Description/i), { target: { value: 'M77 ABS' } });
    await fireEvent.change(getByLabelText(/Accounting Category/i), { target: { value: '7' } });
    await fireEvent.click(getByText('Save'));

    expect(api.post).toHaveBeenCalledTimes(1);
    const [, payload] = api.post.mock.calls[0];
    expect(payload.accounting_category).toBe(7);
    // The server derives is_material from the chosen AC — never client-sent.
    expect('is_material' in payload).toBe(false);
  });

  it('every manual line blocks save with no accounting category (no material exemption)', async () => {
    const { getByLabelText, getByText, queryByText } = render(LineItemModal, {
      props: {
        open: true, mode: 'create', apiBase: '/api/estimates/1', categories,
      },
    });

    await fireEvent.input(getByLabelText(/Description/i), { target: { value: 'Rush' } });
    await fireEvent.click(getByText('Save'));

    expect(api.post).not.toHaveBeenCalled();
    expect(queryByText(/Accounting Category is required/i)).not.toBeNull();
  });
});

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

describe('LineItemModal — linked-deliverable edit dialog (RM 2026-08-12)', () => {
  beforeEach(() => { api.post.mockClear(); api.patch.mockClear(); });

  const ITEM = {
    line_item_id: 44, description: '3 chairs', qty: '3', units: 'ea',
    price: '500.00', accounting_category: 7,
    linked_deliverables: [{ id: 9, description: '3 chairs', qty_ordered: '3.00', units: 'ea' }],
  };

  function editProps(item = ITEM) {
    return { open: true, mode: 'edit', apiBase: '/api/estimates/1', categories, item };
  }

  it('asks before saving a qty change; "update deliverable" PATCHes with the param and reports back', async () => {
    const onSaved = vi.fn();
    const { getByLabelText, getByText, findByText } = render(LineItemModal, {
      props: { ...editProps(), onSaved },
    });
    await fireEvent.input(getByLabelText(/Quantity/i), { target: { value: '5' } });
    await fireEvent.click(getByText('Save'));
    expect(api.patch).not.toHaveBeenCalled();
    await findByText(/Update it to match these changes\?/);
    await fireEvent.click(getByText('Save and update deliverable'));
    await vi.waitFor(() => expect(api.patch).toHaveBeenCalledWith(
      '/api/estimates/1/line-items/44/?update_deliverables=true',
      expect.objectContaining({ qty: 5 })));
    expect(onSaved).toHaveBeenCalledWith({ deliverablesUpdated: true });
  });

  it('"keep deliverable as is" PATCHes without the param', async () => {
    const onSaved = vi.fn();
    const { getByLabelText, getByText, findByText } = render(LineItemModal, {
      props: { ...editProps(), onSaved },
    });
    await fireEvent.input(getByLabelText(/Quantity/i), { target: { value: '5' } });
    await fireEvent.click(getByText('Save'));
    await findByText(/Update it to match these changes\?/);
    await fireEvent.click(getByText('Save, keep deliverable as is'));
    await vi.waitFor(() => expect(api.patch).toHaveBeenCalledWith(
      '/api/estimates/1/line-items/44/',
      expect.objectContaining({ qty: 5 })));
    expect(onSaved).toHaveBeenCalledWith({ deliverablesUpdated: false });
  });

  it('a price-only change saves directly — deliverables carry no price', async () => {
    const { getByLabelText, getByText, queryByText } = render(LineItemModal, {
      props: editProps(),
    });
    await fireEvent.input(getByLabelText(/^Price/i), { target: { value: '550' } });
    await fireEvent.click(getByText('Save'));
    expect(queryByText(/Update it to match these changes\?/)).toBeNull();
    await vi.waitFor(() => expect(api.patch).toHaveBeenCalledWith(
      '/api/estimates/1/line-items/44/',
      expect.objectContaining({ price: 550 })));
  });

  it('an unlinked line never asks', async () => {
    const { getByLabelText, getByText, queryByText } = render(LineItemModal, {
      props: editProps({ ...ITEM, linked_deliverables: [] }),
    });
    await fireEvent.input(getByLabelText(/Quantity/i), { target: { value: '5' } });
    await fireEvent.click(getByText('Save'));
    expect(queryByText(/Update it to match these changes\?/)).toBeNull();
    await vi.waitFor(() => expect(api.patch).toHaveBeenCalled());
  });

  it('Back returns to the form without saving', async () => {
    const { getByLabelText, getByText, findByText, queryByText } = render(LineItemModal, {
      props: editProps(),
    });
    await fireEvent.input(getByLabelText(/Quantity/i), { target: { value: '5' } });
    await fireEvent.click(getByText('Save'));
    await findByText(/Update it to match these changes\?/);
    await fireEvent.click(getByText('Back'));
    expect(queryByText(/Update it to match these changes\?/)).toBeNull();
    expect(api.patch).not.toHaveBeenCalled();
  });
});


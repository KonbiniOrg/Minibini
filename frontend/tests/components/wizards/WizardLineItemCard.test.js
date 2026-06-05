import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), patch: vi.fn(), post: vi.fn(), delete: vi.fn() } }));

import { api } from '@/lib/api.js';
import WizardLineItemCard from '@/components/wizards/WizardLineItemCard.svelte';

function lineItem(overrides) {
  return { line_item_id: 7, line_number: 1, description: 'Line', qty: '2', units: 'none', price: '10', sources: [], ...overrides };
}

beforeEach(() => {
  api.get.mockReset();
  api.patch.mockReset();
  api.post.mockReset();
  api.delete.mockReset();
  api.get.mockResolvedValue([]); // UnitsSelect
  api.patch.mockResolvedValue({ description: 'Line2', qty: '2', units: 'none', price: '10' });
  api.delete.mockResolvedValue({});
  api.post.mockResolvedValue({});
});

describe('WizardLineItemCard', () => {
  it('saves an edited line item', async () => {
    const { getByPlaceholderText, getByRole } = render(WizardLineItemCard, {
      props: { lineItem: lineItem(), apiBase: '/api/estimates/3' },
    });
    await fireEvent.input(getByPlaceholderText('Name this line item…'), { target: { value: 'Line2' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    expect(api.patch).toHaveBeenCalledWith('/api/estimates/3/line-items/7/', {
      description: 'Line2', qty: '2', units: 'none', price: '10',
    });
  });

  it('deletes the line item', async () => {
    const { getByRole } = render(WizardLineItemCard, {
      props: { lineItem: lineItem(), apiBase: '/api/estimates/3' },
    });
    await fireEvent.click(getByRole('button', { name: '×' }));
    expect(api.delete).toHaveBeenCalledWith('/api/estimates/3/line-items/7/');
  });

  it('flags an overridden bundled price', () => {
    // sources sum 10 over qty 2 → expected $5/unit, but saved price is $10 → overridden
    const { getByText } = render(WizardLineItemCard, {
      props: {
        lineItem: lineItem({ price: '10', sources: [{ source_id: 9, description: 'atom', computed_amount: '10' }] }),
        apiBase: '/api/estimates/3',
      },
    });
    expect(getByText(/overridden/)).toBeInTheDocument();
  });
});

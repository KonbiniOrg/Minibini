import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));

import { api } from '@/lib/api.js';
import MaterialPicker from '@/components/expenses/MaterialPicker.svelte';

beforeEach(() => {
  api.get.mockReset();
  api.get.mockResolvedValue({ results: [] }); // PriceListItemPicker catalog
});

describe('MaterialPicker (expense purchased item)', () => {
  it('prompts to choose a job when none is selected', async () => {
    const { findByText } = render(MaterialPicker, { props: { jobId: null } });
    expect(await findByText(/Choose a job above/)).toBeInTheDocument();
  });

  it('reveals freeform item fields after "Add"', async () => {
    const { getByText, getByLabelText } = render(MaterialPicker, { props: { jobId: 1 } });
    await fireEvent.click(getByText('+ Add a purchased item'));
    expect(getByLabelText('Item description')).toBeInTheDocument();
    expect(getByLabelText('Quantity')).toBeInTheDocument();
    expect(getByLabelText('Unit cost')).toBeInTheDocument();
  });

  it('does not offer an existing-material list (no joining)', async () => {
    const { getByText, queryByText } = render(MaterialPicker, { props: { jobId: 1 } });
    await fireEvent.click(getByText('+ Add a purchased item'));
    // The control only creates new items; it never lists existing materials.
    expect(queryByText(/existing material/i)).toBeNull();
  });
});

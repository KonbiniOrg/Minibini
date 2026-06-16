import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));

import { api } from '@/lib/api.js';
import CatalogPicker from '@/components/CatalogPicker.svelte';

beforeEach(() => {
  api.get.mockReset();
  api.get.mockImplementation((url) => {
    if (url.startsWith('/api/task-templates/')) {
      return Promise.resolve({ results: [{ template_id: 1, template_name: 'Welding', description: 'weld', rate: '25', units: 'hr' }] });
    }
    if (url.startsWith('/api/inventory/')) {
      return Promise.resolve({ results: [{ inventory_item_id: 2, code: 'STEEL', description: 'steel', selling_price: '5', units: 'kg' }] });
    }
    return Promise.resolve({ results: [] });
  });
});

describe('CatalogPicker', () => {
  it('loads both catalogs on focus', async () => {
    const { getByPlaceholderText, findByText } = render(CatalogPicker);
    await fireEvent.focus(getByPlaceholderText('Search catalogs…'));
    expect(await findByText('Welding')).toBeInTheDocument();
    expect(await findByText('STEEL')).toBeInTheDocument();
  });

  it('selects a task template', async () => {
    const onSelect = vi.fn();
    const { getByPlaceholderText, findByRole } = render(CatalogPicker, { props: { onSelect } });
    await fireEvent.focus(getByPlaceholderText('Search catalogs…'));
    await fireEvent.click(await findByRole('button', { name: /Welding/ }));
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ kind: 'task_template' }));
  });

  it('offers a manual entry option', async () => {
    const onSelect = vi.fn();
    const { getByPlaceholderText, findByRole } = render(CatalogPicker, { props: { onSelect } });
    await fireEvent.focus(getByPlaceholderText('Search catalogs…'));
    await fireEvent.click(await findByRole('button', { name: /Enter manually/ }));
    expect(onSelect).toHaveBeenCalledWith({ kind: 'manual', item: null });
  });
});

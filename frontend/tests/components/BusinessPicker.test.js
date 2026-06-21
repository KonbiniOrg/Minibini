import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));
import { api } from '@/lib/api.js';
import BusinessPicker from '@/components/BusinessPicker.svelte';

beforeEach(() => { api.get.mockReset(); });

describe('BusinessPicker', () => {
  it('searches and emits the picked business', async () => {
    api.get.mockResolvedValue({ results: [{ business_id: 5, business_name: 'Acme Steel', default_contact: 9 }] });
    const onSelect = vi.fn();
    const { getByPlaceholderText, findByRole } = render(BusinessPicker, { props: { onSelect } });
    await fireEvent.input(getByPlaceholderText(/business/i), { target: { value: 'ac' } });
    await new Promise((r) => setTimeout(r, 300));
    expect(api.get).toHaveBeenCalledWith('/api/businesses/?search=ac&page_size=10');
    await fireEvent.click(await findByRole('button', { name: /Acme Steel/ }));
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ business_id: 5 }));
  });
});

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));
import { api } from '@/lib/api.js';
import CustomerPicker from '@/components/CustomerPicker.svelte';

beforeEach(() => { api.get.mockReset(); });

describe('CustomerPicker', () => {
  it('merges businesses and contacts and emits {type,id}', async () => {
    api.get.mockImplementation((url) =>
      url.includes('/businesses/')
        ? Promise.resolve({ results: [{ business_id: 5, business_name: 'Acme' }] })
        : Promise.resolve({ results: [{ contact_id: 3, name: 'Pat', business: { business_name: 'Acme' } }] }));
    const onSelect = vi.fn();
    const { getByPlaceholderText, findByRole } = render(CustomerPicker, { props: { onSelect } });
    await fireEvent.input(getByPlaceholderText(/customer or vendor/i), { target: { value: 'ac' } });
    await new Promise((r) => setTimeout(r, 300));
    await fireEvent.mouseDown(await findByRole('button', { name: /Acme \(business\)/ }));
    expect(onSelect).toHaveBeenCalledWith({ type: 'business', id: 5 });
  });
});

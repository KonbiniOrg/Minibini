import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));

import { api } from '@/lib/api.js';
import CustomerPicker from '@/components/CustomerPicker.svelte';

beforeEach(() => { api.get.mockReset(); });

describe('CustomerPicker', () => {
  it('merges business + contact results and tags them', async () => {
    api.get.mockImplementation((url) => {
      if (url.includes('/api/businesses/')) {
        return Promise.resolve({ results: [{ business_id: 1, business_name: 'Acme' }] });
      }
      return Promise.resolve({
        results: [{ contact_id: 9, name: 'Jane Roe', business: { business_name: 'Acme' } }],
      });
    });

    const { getByPlaceholderText, findByText } = render(CustomerPicker);
    await fireEvent.input(getByPlaceholderText(/customer or vendor/i),
      { target: { value: 'ac' } });

    expect(await findByText(/Acme \(business\)/)).toBeInTheDocument();
    expect(await findByText(/Jane Roe.*\(contact\)/)).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith('/api/businesses/?search=ac&page_size=10');
    expect(api.get).toHaveBeenCalledWith('/api/contacts/?search=ac&page_size=10');
  });

  it('emits {type,id} on select and shows a Clear button', async () => {
    api.get.mockImplementation((url) =>
      url.includes('/api/businesses/')
        ? Promise.resolve({ results: [{ business_id: 1, business_name: 'Acme' }] })
        : Promise.resolve({ results: [] }));

    const onSelect = vi.fn();
    const { getByPlaceholderText, findByText, getByRole } =
      render(CustomerPicker, { props: { onSelect } });
    await fireEvent.input(getByPlaceholderText(/customer or vendor/i),
      { target: { value: 'ac' } });
    await fireEvent.mouseDown(await findByText(/Acme \(business\)/));

    expect(onSelect).toHaveBeenCalledWith({ type: 'business', id: 1 });
    expect(getByRole('button', { name: 'Clear' })).toBeInTheDocument();
  });

  it('does not hit the server for a blank query', async () => {
    const { getByPlaceholderText } = render(CustomerPicker);
    await fireEvent.input(getByPlaceholderText(/customer or vendor/i),
      { target: { value: '  ' } });
    expect(api.get).not.toHaveBeenCalled();
  });
});

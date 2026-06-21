import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));
import { api } from '@/lib/api.js';
import ContactPicker from '@/components/ContactPicker.svelte';

beforeEach(() => { api.get.mockReset(); });

describe('ContactPicker', () => {
  it('searches and emits the picked contact; value is the id', async () => {
    api.get.mockResolvedValue({ results: [
      { contact_id: 3, name: 'Pat Quinn', business: { business_name: 'Acme' } },
    ] });
    const onSelect = vi.fn();
    const { getByPlaceholderText, findByRole } = render(ContactPicker, { props: { onSelect } });
    await fireEvent.input(getByPlaceholderText(/contact/i), { target: { value: 'pat' } });
    await new Promise((r) => setTimeout(r, 300));
    expect(api.get).toHaveBeenCalledWith('/api/contacts/?search=pat&page_size=10');
    await fireEvent.click(await findByRole('button', { name: /Pat Quinn/ }));
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ contact_id: 3 }));
  });
});

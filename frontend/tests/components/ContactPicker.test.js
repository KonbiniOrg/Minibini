import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

// Mock the network seam, not fetch. ContactPicker imports `api` from
// '../lib/api.js'; that resolves to the same module as '@/lib/api.js', so this
// mock intercepts it. vi.mock is hoisted above the imports automatically.
vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));

import { api } from '@/lib/api.js';
import ContactPicker from '@/components/ContactPicker.svelte';

beforeEach(() => {
  api.get.mockReset();
});

describe('ContactPicker', () => {
  it('searches, renders results, and selects one', async () => {
    api.get.mockResolvedValue({
      results: [{ contact_id: 5, name: 'Bob', business: { business_name: 'Acme' } }],
    });

    const { getByPlaceholderText, findByText, getByRole } = render(ContactPicker);

    // Typing fires oninput -> search() -> awaits api.get. findByText polls until
    // the async result row appears (don't assert synchronously).
    await fireEvent.input(getByPlaceholderText(/search contacts/i), {
      target: { value: 'bob' },
    });
    const resultRow = await findByText('Bob from Acme');

    expect(api.get).toHaveBeenCalledWith(
      '/api/contacts/?search=bob&page_size=10',
    );

    // Picking a result collapses the search UI into the selected label + Change.
    await fireEvent.click(resultRow);
    expect(getByRole('button', { name: 'Change' })).toBeInTheDocument();
  });

  it('does not hit the server for a blank query', async () => {
    const { getByPlaceholderText } = render(ContactPicker);
    await fireEvent.input(getByPlaceholderText(/search contacts/i), {
      target: { value: '   ' },
    });
    expect(api.get).not.toHaveBeenCalled();
  });

  it('shows "No matches." when the search returns nothing', async () => {
    api.get.mockResolvedValue({ results: [] });
    const { getByPlaceholderText, findByText } = render(ContactPicker);
    await fireEvent.input(getByPlaceholderText(/search contacts/i), {
      target: { value: 'zzz' },
    });
    expect(await findByText('No matches.')).toBeInTheDocument();
  });
});

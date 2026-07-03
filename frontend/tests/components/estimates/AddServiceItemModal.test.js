import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn() } }));

import { api } from '@/lib/api.js';
import AddServiceItemModal from '@/components/estimates/AddServiceItemModal.svelte';

const SERVICE_ITEMS = [
  { template_id: 7, template_name: 'CAM coding' },
  { template_id: 8, template_name: 'V-Carve' },
];

beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();
  api.get.mockResolvedValue({ results: SERVICE_ITEMS });
});

describe('AddServiceItemModal', () => {
  it('creates a deferred service line (no Task), one API call', async () => {
    api.post.mockResolvedValueOnce({ line_item_id: 1, service_item: 7 });
    const onSaved = vi.fn();
    const { getByRole, findByText } = render(AddServiceItemModal, {
      props: { open: true, jobId: 9, estimateId: 3, onSaved },
    });

    await findByText('CAM coding');
    await fireEvent.change(getByRole('combobox'), { target: { value: '7' } });
    await fireEvent.input(getByRole('spinbutton'), { target: { value: '2' } });
    await fireEvent.click(getByRole('button', { name: 'Add' }));

    await vi.waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(api.post).toHaveBeenCalledTimes(1);
    expect(api.post).toHaveBeenCalledWith(
      '/api/estimates/3/line-items-from-service/',
      { service_item: 7, qty: '2' },
    );
  });

  it('does not call the API when no service item is selected', async () => {
    const { getByRole, findByText } = render(AddServiceItemModal, {
      props: { open: true, jobId: 9, estimateId: 3 },
    });
    await findByText('CAM coding');
    await fireEvent.click(getByRole('button', { name: 'Add' }));
    expect(api.post).not.toHaveBeenCalled();
  });
});

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn() } }));

import { api } from '@/lib/api.js';
import AddServiceItemModal from '@/components/estimates/AddServiceItemModal.svelte';

const SERVICE_ITEMS = [
  { template_id: 7, template_name: 'CAM coding', rate_scheme_detail: { rate: '95', algorithm: 'elapsed_time' } },
  { template_id: 8, template_name: 'V-Carve', rate_scheme_detail: null },
];

beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();
  api.get.mockResolvedValue({ results: SERVICE_ITEMS });
});

describe('AddServiceItemModal', () => {
  it('creates a Task from the service item, then an atom-backed estimate line', async () => {
    api.post
      .mockResolvedValueOnce({ task_id: 42 })      // add-from-template → Task
      .mockResolvedValueOnce({ line_item_id: 1 });  // line-items-from-atoms → line
    const onSaved = vi.fn();
    const { getByRole, findByText } = render(AddServiceItemModal, {
      props: { open: true, jobId: 9, estimateId: 3, onSaved },
    });

    await findByText('CAM coding');  // service items loaded into the picker
    await fireEvent.change(getByRole('combobox'), { target: { value: '7' } });
    await fireEvent.input(getByRole('spinbutton'), { target: { value: '2' } });
    await fireEvent.click(getByRole('button', { name: 'Add' }));

    await vi.waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(api.post).toHaveBeenNthCalledWith(
      1, '/api/jobs/9/add-from-template/', { service_item_id: 7, est_qty: 2 },
    );
    expect(api.post).toHaveBeenNthCalledWith(
      2, '/api/estimates/3/line-items-from-atoms/', { atoms: [{ type: 'task', id: 42 }] },
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

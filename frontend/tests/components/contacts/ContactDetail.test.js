import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn() } }));

import { api } from '@/lib/api.js';
import { viewMode } from '@/stores/viewMode.js';
import ContactDetail from '@/components/contacts/ContactDetail.svelte';

function contact() {
  return {
    contact_id: 1, name: 'Jane', email: 'j@x.com', tags: [],
    jobs: [
      { job_id: 1, job_number: 'JOB-1', name: 'Open', status: 'pending' },
      { job_id: 2, job_number: 'JOB-2', name: 'Done', status: 'completed' },
    ],
  };
}

beforeEach(() => {
  api.get.mockReset();
  api.get.mockResolvedValue({ results: [] }); // TagEditor's tag fetch
  viewMode.set('lite');
});

describe('ContactDetail', () => {
  it('shows all jobs in full mode', () => {
    viewMode.set('full');
    const { getByText } = render(ContactDetail, { props: { contact: contact() } });
    expect(getByText('JOB-1')).toBeInTheDocument();
    expect(getByText('JOB-2')).toBeInTheDocument();
  });

  it('hides closed jobs in lite mode', () => {
    viewMode.set('lite');
    const { getByText, queryByText } = render(ContactDetail, { props: { contact: contact() } });
    expect(getByText('JOB-1')).toBeInTheDocument();
    expect(queryByText('JOB-2')).toBeNull();
  });

  it('pages purchase orders via the callback', async () => {
    const onPOPageChange = vi.fn();
    const { getByRole } = render(ContactDetail, {
      props: {
        contact: contact(),
        purchaseOrders: { results: [{ po_id: 1, po_number: 'PO-1', status: 'open' }], next: 'http://x/?page=2', previous: null, count: 30 },
        onPOPageChange,
      },
    });
    await fireEvent.click(getByRole('button', { name: 'Next' }));
    expect(onPOPageChange).toHaveBeenCalledWith(2);
  });

  it('fires edit and delete callbacks', async () => {
    const onEdit = vi.fn();
    const onDelete = vi.fn();
    const { getByRole } = render(ContactDetail, { props: { contact: contact(), onEdit, onDelete } });
    await fireEvent.click(getByRole('button', { name: 'Edit' }));
    await fireEvent.click(getByRole('button', { name: 'Delete' }));
    expect(onEdit).toHaveBeenCalled();
    expect(onDelete).toHaveBeenCalled();
  });
});

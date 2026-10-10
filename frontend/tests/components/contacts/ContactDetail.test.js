import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn() } }));

import { api } from '@/lib/api.js';
import { viewMode } from '@/stores/viewMode.js';
import { user } from '@/stores/auth.js';
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
  user.set({ id: 1, permissions: ['can_manage_jobs'] });
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

  it('fires edit and delete callbacks (manager)', async () => {
    const onEdit = vi.fn();
    const onDelete = vi.fn();
    const { getByRole } = render(ContactDetail, { props: { contact: contact(), onEdit, onDelete } });
    await fireEvent.click(getByRole('button', { name: 'Edit' }));
    await fireEvent.click(getByRole('button', { name: 'Delete' }));
    expect(onEdit).toHaveBeenCalled();
    expect(onDelete).toHaveBeenCalled();
  });

  it('hides edit/delete and the tag editor from a non-manager (shows tags read-only)', () => {
    user.set({ id: 2, permissions: [] });
    const c = { ...contact(), tags: [{ tag_id: 1, name: 'VIP' }] };
    const { queryByRole, getByText } = render(ContactDetail, {
      props: { contact: c, onEdit: vi.fn(), onDelete: vi.fn() },
    });
    expect(queryByRole('button', { name: 'Edit' })).toBeNull();
    expect(queryByRole('button', { name: 'Delete' })).toBeNull();
    expect(queryByRole('textbox')).toBeNull(); // no tag-add input
    expect(getByText('VIP')).toBeInTheDocument(); // tags still visible, read-only
  });
});

describe('ContactDetail — DataTable lists', () => {
  const headersOf = (t) => Array.from(t.querySelectorAll('thead th')).map((th) => th.textContent.trim());

  it('renders the Jobs table with the same headers in lite and full, stamped with data-col', async () => {
    viewMode.set('full');
    const { container } = render(ContactDetail, { props: { contact: contact() } });
    const jobs = container.querySelector('table.data-table');
    expect(headersOf(jobs)).toEqual(['Job #', 'Name', 'Status']);
    expect(jobs.querySelector('td[data-col="number"] a')).toHaveAttribute('href', '#/jobs/1');
    viewMode.set('lite');
    const { container: c2 } = render(ContactDetail, { props: { contact: contact() } });
    expect(headersOf(c2.querySelector('table.data-table'))).toEqual(['Job #', 'Name', 'Status']);
  });

  it('renders the Invoices and PO tables with their headers when results are supplied', () => {
    viewMode.set('full');
    const invoices = { count: 1, next: null, previous: null, results: [
      { invoice_id: 5, display_number: 'INV-5', job: 1, job_number: 'JOB-1', status: 'open', total: '10', amount_paid: '0', balance: '10' },
    ] };
    const purchaseOrders = { count: 1, next: null, previous: null, results: [{ po_id: 3, po_number: 'PO-3', status: 'draft' }] };
    const { container } = render(ContactDetail, { props: { contact: contact(), invoices, purchaseOrders } });
    const tables = container.querySelectorAll('table.data-table');
    expect(tables).toHaveLength(3);
    expect(headersOf(tables[1])).toEqual(['Invoice #', 'Job', 'Status', 'Total', 'Paid', 'Balance']);
    expect(headersOf(tables[2])).toEqual(['PO #', 'Status']);
    expect(tables[1].querySelector('td[data-col="total"]').textContent.trim()).toBe('$10.00');
  });
});

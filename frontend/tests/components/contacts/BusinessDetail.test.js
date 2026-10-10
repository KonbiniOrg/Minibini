import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn() } }));

import { api } from '@/lib/api.js';
import { viewMode } from '@/stores/viewMode.js';
import { user } from '@/stores/auth.js';
import BusinessDetail from '@/components/contacts/BusinessDetail.svelte';

function business() {
  return {
    business_id: 1, business_name: 'Acme', our_reference_code: 'R1',
    business_phone: '', business_address: '', website: '', tax_exemption_number: '',
    tax_multiplier: null, terms: '', default_contact: { contact_id: 9, name: 'Boss' }, tags: [],
    jobs: [
      { job_id: 1, job_number: 'JOB-1', name: 'Open', status: 'pending' },
      { job_id: 2, job_number: 'JOB-2', name: 'Done', status: 'completed' },
    ],
  };
}

beforeEach(() => {
  api.get.mockReset();
  api.get.mockResolvedValue({ results: [] });
  viewMode.set('lite');
  user.set({ id: 1, permissions: ['can_manage_jobs'] });
});

describe('BusinessDetail', () => {
  it('shows all jobs in full mode', () => {
    viewMode.set('full');
    const { getByText } = render(BusinessDetail, { props: { business: business() } });
    expect(getByText('JOB-1')).toBeInTheDocument();
    expect(getByText('JOB-2')).toBeInTheDocument();
  });

  it('hides closed jobs in lite mode', () => {
    viewMode.set('lite');
    const { getByText, queryByText } = render(BusinessDetail, { props: { business: business() } });
    expect(getByText('JOB-1')).toBeInTheDocument();
    expect(queryByText('JOB-2')).toBeNull();
  });

  it('fires edit and delete callbacks (manager)', async () => {
    const onEdit = vi.fn();
    const onDelete = vi.fn();
    const { getByRole } = render(BusinessDetail, { props: { business: business(), onEdit, onDelete } });
    await fireEvent.click(getByRole('button', { name: 'Edit' }));
    await fireEvent.click(getByRole('button', { name: 'Delete' }));
    expect(onEdit).toHaveBeenCalled();
    expect(onDelete).toHaveBeenCalled();
  });

  it('hides edit/delete and the tag editor from a non-manager (shows tags read-only)', () => {
    user.set({ id: 2, permissions: [] });
    const b = { ...business(), tags: [{ tag_id: 1, name: 'Wholesale' }] };
    const { queryByRole, getByText } = render(BusinessDetail, {
      props: { business: b, onEdit: vi.fn(), onDelete: vi.fn() },
    });
    expect(queryByRole('button', { name: 'Edit' })).toBeNull();
    expect(queryByRole('button', { name: 'Delete' })).toBeNull();
    expect(queryByRole('textbox')).toBeNull();
    expect(getByText('Wholesale')).toBeInTheDocument();
  });
});

describe('BusinessDetail — DataTable lists', () => {
  const headersOf = (t) => Array.from(t.querySelectorAll('thead th')).map((th) => th.textContent.trim());

  it('renders the Contacts table (full only) and the Jobs table with stable headers', () => {
    viewMode.set('full');
    const biz = { ...business(), contacts: [{ contact_id: 9, name: 'Boss', email: 'b@x.com', mobile_number: '555-1' }] };
    const { container } = render(BusinessDetail, { props: { business: biz } });
    const tables = container.querySelectorAll('table.data-table');
    expect(headersOf(tables[0])).toEqual(['Name', 'Email', 'Phone']);
    expect(tables[0].querySelector('td[data-col="name"]').textContent).toContain('(default)');
    expect(headersOf(tables[1])).toEqual(['Job #', 'Name', 'Status']);
    viewMode.set('lite');
    const { container: c2 } = render(BusinessDetail, { props: { business: biz } });
    // Contacts section is <FullOnly>; the Jobs table is the first table in lite.
    expect(headersOf(c2.querySelector('table.data-table'))).toEqual(['Job #', 'Name', 'Status']);
  });

  it('shows "No contacts." in the full-only Contacts section when the business has none', () => {
    viewMode.set('full');
    const { getByText } = render(BusinessDetail, { props: { business: { ...business(), contacts: [] } } });
    expect(getByText('No contacts.')).toBeInTheDocument();
  });
});

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

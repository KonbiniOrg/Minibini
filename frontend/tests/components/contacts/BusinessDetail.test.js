import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, within } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn() } }));

import { api } from '@/lib/api.js';
import { viewMode } from '@/stores/viewMode.js';
import { user } from '@/stores/auth.js';
import BusinessDetail from '@/components/contacts/BusinessDetail.svelte';

function business() {
  return {
    business_id: 1, business_name: 'Acme', our_reference_code: 'R1',
    phones: [{ number: '555-0100', label: 'main' }], business_address: '1 Main St\nTown', website: 'acme.test',
    tax_exemption_number: '', tax_multiplier: null, terms: 2, terms_name: 'Net 30',
    default_contact: { contact_id: 9, name: 'Boss' }, tags: [],
    contacts: [
      { contact_id: 9, name: 'Boss', email: 'boss@acme.test', phone: '555-1' },
      { contact_id: 10, name: 'Worker', email: '', phone: '555-2' },
    ],
    jobs: [
      { job_id: 1, job_number: 'JOB-1', name: 'Open', status: 'in_progress', contact: 9, contact_name: 'Boss', start_date: null, created_date: '2026-01-01T00:00:00Z', estimated_amount: '10.00' },
      { job_id: 2, job_number: 'JOB-2', name: 'Done', status: 'completed', contact: 10, contact_name: 'Worker', start_date: null, created_date: '2025-01-01T00:00:00Z', estimated_amount: '20.00' },
    ],
  };
}

beforeEach(() => {
  api.get.mockReset();
  api.get.mockResolvedValue({ results: [] });
  viewMode.set('full');
  user.set({ id: 1, permissions: ['can_manage_jobs', 'can_manage_financials'] });
});

describe('BusinessDetail — identity panels', () => {
  it('renders Contact and Billing facts without the old Name / Reference rows', () => {
    const { container, getByText } = render(BusinessDetail, { props: { business: business() } });
    const panels = container.querySelectorAll('.identity .panel');
    expect(Array.from(panels).map((p) => p.querySelector('.panel-head').textContent.trim())).toEqual(['Contact', 'Billing', 'Tags']);
    expect(within(panels[0]).getByRole('link', { name: 'acme.test' })).toHaveAttribute('href', 'https://acme.test');
    expect(getByText('555-0100')).toBeInTheDocument();
    expect(getByText('Net 30')).toBeInTheDocument();
    expect(getByText('Not exempt')).toBeInTheDocument();
    expect(getByText('full rate')).toBeInTheDocument();
    expect(getByText('R1')).toBeInTheDocument();
    expect(within(panels[0]).queryByText('Name')).toBeNull();
    expect(within(panels[1]).queryByText('Name')).toBeNull();
  });

  it('shows tags read-only to a non-manager', () => {
    user.set({ id: 2, permissions: [] });
    const b = { ...business(), tags: [{ tag_id: 1, name: 'Wholesale' }] };
    const { queryByRole, getByText } = render(BusinessDetail, { props: { business: b } });
    expect(queryByRole('textbox')).toBeNull();
    expect(getByText('Wholesale')).toBeInTheDocument();
  });
});

describe('BusinessDetail — activity column', () => {
  it('renders Contacts first, always, with the default chip and a Contact column on Recent Jobs', () => {
    const { container } = render(BusinessDetail, { props: { business: business() } });
    const keys = Array.from(container.querySelectorAll('[data-section]')).map((el) => el.dataset.section);
    expect(keys[0]).toBe('contacts');
    const contacts = container.querySelector('[data-section="contacts"]');
    expect(within(contacts).getByText('default')).toBeInTheDocument();
    const jobs = container.querySelector('[data-section="jobs"]');
    expect(Array.from(jobs.querySelectorAll('thead th')).map((th) => th.textContent.trim()))
      .toEqual(['Job #', 'Name', 'Contact', 'Status', 'Started', 'Estimate']);
  });

  it('threads Set as default and New job (per row) to the page callbacks', async () => {
    const onSetDefault = vi.fn();
    const onNewJobFor = vi.fn();
    const { container } = render(BusinessDetail, { props: { business: business(), onSetDefault, onNewJobFor } });
    const rows = container.querySelectorAll('[data-section="contacts"] tbody tr');
    await fireEvent.click(within(rows[1]).getByRole('button', { name: 'Set as default' }));
    expect(onSetDefault).toHaveBeenCalledWith(10);
    await fireEvent.click(within(rows[1]).getByRole('button', { name: 'New job' }));
    expect(onNewJobFor).toHaveBeenCalledWith(10);
  });

  it('New contact opens the contact modal pre-attached to this business', async () => {
    const { findByRole } = render(BusinessDetail, { props: { business: business() } });
    await fireEvent.click(await findByRole('button', { name: 'New contact' }));
    expect(await findByRole('dialog', { name: 'New contact' })).toBeInTheDocument();
  });

  it('offers New purchase order on the collapsed PO line, scoped to the business', () => {
    const { getByRole } = render(BusinessDetail, { props: { business: business(), purchaseOrders: [] } });
    expect(getByRole('link', { name: 'New purchase order' })).toHaveAttribute('href', '#/purchase-orders/new?business=1');
  });
});

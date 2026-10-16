import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, within } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn() } }));

import { api } from '@/lib/api.js';
import { viewMode } from '@/stores/viewMode.js';
import { user } from '@/stores/auth.js';
import ContactDetail from '@/components/contacts/ContactDetail.svelte';

function contact() {
  return {
    contact_id: 1, name: 'Jane', email: 'j@x.com', phones: [{ number: '555-0162', label: 'Mobile' }],
    addr1: '1 Main St', city: 'Alameda', municipality: 'CA', postal_code: '94501', tags: [],
    business: { business_id: 7, business_name: 'Acme', default_contact: { contact_id: 1 } },
    jobs: [
      { job_id: 1, job_number: 'JOB-1', name: 'Open', status: 'in_progress', contact: 1, contact_name: 'Jane', start_date: null, created_date: '2026-01-01T00:00:00Z', estimated_amount: '10.00' },
      { job_id: 2, job_number: 'JOB-2', name: 'Done', status: 'completed', contact: 1, contact_name: 'Jane', start_date: null, created_date: '2025-01-01T00:00:00Z', estimated_amount: '20.00' },
    ],
  };
}
const BUSINESS = {
  business_id: 7, business_name: 'Acme', phone: '555-0100', terms_name: 'Net 30', tax_exemption_number: 'X1',
  contacts: [{ contact_id: 1, name: 'Jane' }, { contact_id: 2, name: 'Marcus' }, { contact_id: 3, name: 'Priya' }],
  jobs: [{ job_id: 1, contact: 1 }, { job_id: 5, contact: 2 }, { job_id: 6, contact: 2 }],
};

beforeEach(() => {
  api.get.mockReset();
  api.get.mockResolvedValue({ results: [] }); // TagEditor's tag fetch
  viewMode.set('full');
  user.set({ id: 1, permissions: ['can_manage_jobs'] });
});

describe('ContactDetail — identity panels', () => {
  it('renders the Contact panel with mailto / tel links and the address block', () => {
    const { container } = render(ContactDetail, { props: { contact: contact() } });
    const panel = container.querySelector('.identity .panel');
    expect(panel.querySelector('.panel-head').textContent.trim()).toBe('Contact');
    expect(within(panel).getByRole('link', { name: 'j@x.com' })).toHaveAttribute('href', 'mailto:j@x.com');
    expect(within(panel).getByRole('link', { name: '555-0162' })).toHaveAttribute('href', 'tel:555-0162');
    expect(within(panel).getByRole('button', { name: 'copy' })).toBeInTheDocument();
    expect(panel.textContent).toContain('Alameda, CA 94501');
    expect(within(panel).queryByText('Work')).toBeNull(); // blank numbers are omitted
  });

  it('renders the Business card with the mid-call line and the "Also here" siblings with job counts', () => {
    const { container } = render(ContactDetail, { props: { contact: contact(), business: BUSINESS } });
    const panels = container.querySelectorAll('.identity .panel');
    expect(panels[1].querySelector('.panel-head').textContent.trim()).toBe('Business');
    expect(within(panels[1]).getByRole('link', { name: 'Acme' })).toHaveAttribute('href', '#/businesses/7');
    expect(panels[1].textContent).toContain('555-0100 · Net 30 · tax exempt');
    const items = panels[1].querySelectorAll('.siblings li');
    expect(items).toHaveLength(2);
    expect(items[0].textContent).toMatch(/Marcus\s*2 jobs/);
    expect(items[1].textContent).toMatch(/Priya\s*no jobs/);
    expect(within(panels[1]).queryByText('Jane')).toBeNull();
  });

  it('omits the Business panel for an individual', () => {
    const c = { ...contact(), business: null };
    const { container } = render(ContactDetail, { props: { contact: c } });
    const heads = Array.from(container.querySelectorAll('.identity .panel-head')).map((h) => h.textContent.trim());
    expect(heads).toEqual(['Contact', 'Tags']);
  });

  it('shows tags read-only to a non-manager', () => {
    user.set({ id: 2, permissions: [] });
    const c = { ...contact(), tags: [{ tag_id: 1, name: 'VIP' }] };
    const { queryByRole, getByText } = render(ContactDetail, { props: { contact: c } });
    expect(queryByRole('textbox')).toBeNull();
    expect(getByText('VIP')).toBeInTheDocument();
  });
});

describe('ContactDetail — activity column', () => {
  it('renders Recent Jobs without a Contact column and hides the completed job behind the toggle', () => {
    const { container, getByRole, queryByText } = render(ContactDetail, { props: { contact: contact() } });
    const jobs = container.querySelector('[data-section="jobs"]');
    expect(Array.from(jobs.querySelectorAll('thead th')).map((th) => th.textContent.trim()))
      .toEqual(['Job #', 'Name', 'Status', 'Started', 'Estimate']);
    expect(jobs.querySelector('td[data-col="number"] a')).toHaveAttribute('href', '#/jobs/1');
    expect(queryByText('Done')).toBeNull();
    expect(getByRole('button', { name: 'show 1 completed' })).toBeInTheDocument();
    expect(container.querySelector('[data-section="contacts"]')).toBeNull();
  });

  it('scopes the New purchase order link to the contact and its business', () => {
    user.set({ id: 1, permissions: ['can_manage_financials'] });
    const { getByRole } = render(ContactDetail, { props: { contact: contact(), purchaseOrders: [] } });
    expect(getByRole('link', { name: 'New purchase order' }))
      .toHaveAttribute('href', '#/purchase-orders/new?business=7&contact=1');
  });
});

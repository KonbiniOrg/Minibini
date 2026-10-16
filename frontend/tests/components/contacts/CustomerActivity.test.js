import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, within } from '@testing-library/svelte';
import { user } from '@/stores/auth.js';
import { viewMode } from '@/stores/viewMode.js';
import CustomerActivity from '@/components/contacts/CustomerActivity.svelte';

const JOBS = [
  { job_id: 1, job_number: 'JOB-2026-0142', name: 'Tap handles', status: 'in_progress', contact: 9, contact_name: 'Dana', start_date: '2026-09-26T10:00:00Z', created_date: '2026-09-01T10:00:00Z', estimated_amount: '6480.00' },
  { job_id: 2, job_number: 'JOB-2025-0391', name: 'Bar top', status: 'completed', contact: 9, contact_name: 'Dana', start_date: null, created_date: '2025-11-03T10:00:00Z', estimated_amount: '12750.00' },
  { job_id: 3, job_number: 'JOB-2024-0210', name: 'Keg rack', status: 'cancelled', contact: 9, contact_name: 'Dana', start_date: null, created_date: '2024-03-02T10:00:00Z', estimated_amount: '0.00' },
];
const INVOICES = [
  { invoice_id: 5, display_number: 'INV-5', job: 1, job_number: 'JOB-2026-0142', status: 'open', sent_date: '2026-09-30T10:00:00Z', total: '3920.00', amount_paid: '0.00', balance: '3920.00' },
  { invoice_id: 6, display_number: 'INV-6', job: 2, job_number: 'JOB-2025-0391', status: 'paid', sent_date: null, total: '100.00', amount_paid: '100.00', balance: '0.00' },
];
const CONTACTS = [
  { contact_id: 9, name: 'Dana Whitfield', email: 'dana@x.test', phone: '555-0162' },
  { contact_id: 10, name: 'Marcus Lee', email: '', phone: '555-0171' },
];

const headersOf = (t) => Array.from(t.querySelectorAll('thead th')).map((th) => th.textContent.trim());
const section = (container, key) => container.querySelector(`[data-section="${key}"]`);

beforeEach(() => {
  viewMode.set('full');
  user.set({ id: 1, permissions: ['can_manage_jobs', 'can_manage_financials'] });
});

describe('CustomerActivity — Recent Jobs', () => {
  it('shows open jobs only, labels the toggle, and extends the table in place', async () => {
    const { container, getByRole, queryByText, getByText } = render(CustomerActivity, { props: { jobs: JOBS } });
    const sec = section(container, 'jobs');
    expect(headersOf(sec.querySelector('table'))).toEqual(['Job #', 'Name', 'Status', 'Started', 'Estimate']);
    expect(getByText('2026-0142')).toBeInTheDocument();          // JOB- prefix stripped
    expect(queryByText('2025-0391')).toBeNull();
    expect(sec.querySelector('.status-badge').textContent).toBe('In progress');
    expect(sec.querySelector('td[data-col="estimate"]').textContent.trim()).toBe('$6,480.00');

    await fireEvent.click(getByRole('button', { name: 'show 2 completed' }));
    expect(getByText('2025-0391')).toBeInTheDocument();
    expect(getByText('2024-0210')).toBeInTheDocument();
    await fireEvent.click(getByRole('button', { name: 'hide 2 completed' }));
    expect(queryByText('2025-0391')).toBeNull();
  });

  it('adds the Contact column only when asked', () => {
    const { container } = render(CustomerActivity, { props: { jobs: JOBS, showContactColumn: true } });
    const sec = section(container, 'jobs');
    expect(headersOf(sec.querySelector('table'))).toEqual(['Job #', 'Name', 'Contact', 'Status', 'Started', 'Estimate']);
    expect(sec.querySelector('td[data-col="contact"] a')).toHaveAttribute('href', '#/contacts/9');
  });

  it('omits the toggle when nothing is closed', () => {
    const { queryByRole } = render(CustomerActivity, { props: { jobs: [JOBS[0]] } });
    expect(queryByRole('button', { name: /completed/ })).toBeNull();
  });
});

describe('CustomerActivity — Open Invoices and POs', () => {
  it('renders open invoices with a "show N paid" toggle', async () => {
    const { container, getByRole, queryByText, getByText } = render(CustomerActivity, { props: { invoices: INVOICES } });
    const sec = section(container, 'invoices');
    expect(headersOf(sec.querySelector('table'))).toEqual(['Invoice #', 'Job', 'Status', 'Sent', 'Total', 'Paid', 'Balance']);
    expect(getByText('INV-5')).toBeInTheDocument();
    expect(queryByText('INV-6')).toBeNull();
    await fireEvent.click(getByRole('button', { name: 'show 1 paid' }));
    expect(getByText('INV-6')).toBeInTheDocument();
  });

  it('an empty section keeps its heading, shows the "yet" box, sinks below populated ones, and carries the PO action', () => {
    const { container } = render(CustomerActivity, {
      props: { jobs: [], invoices: INVOICES, purchaseOrders: [], newPOHref: '#/purchase-orders/new?business=1' },
    });
    const keys = Array.from(container.querySelectorAll('[data-section]')).map((el) => el.dataset.section);
    expect(keys).toEqual(['invoices', 'jobs', 'pos', 'history']);
    const pos = section(container, 'pos');
    expect(pos.tagName).toBe('SECTION');
    expect(within(pos).getByRole('heading', { name: 'Purchase orders' })).toHaveClass('section-title');
    expect(pos.querySelector('.empty-box').textContent.trim()).toBe('No purchase orders yet.');
    expect(within(pos).getByRole('link', { name: 'New purchase order' })).toHaveAttribute('href', '#/purchase-orders/new?business=1');
    const jobs = section(container, 'jobs');
    expect(within(jobs).getByRole('heading', { name: 'Recent Jobs' })).toHaveClass('section-title');
    expect(jobs.querySelector('.empty-box').textContent.trim()).toBe('No jobs yet.');
    expect(jobs.querySelector('table')).toBeNull();
    // A populated section uses the very same heading style.
    expect(within(section(container, 'invoices')).getByRole('heading', { name: 'Open Invoices' })).toHaveClass('section-title');
  });

  it('a section whose rows are all closed shows the "open" box under the toggle, and the table replaces it on expand', async () => {
    const closedOnly = [JOBS[1], JOBS[2]];
    const paidOnly = [INVOICES[1]];
    const { container, getByRole } = render(CustomerActivity, { props: { jobs: closedOnly, invoices: paidOnly } });
    const jobs = section(container, 'jobs');
    expect(jobs.querySelector('.empty-box').textContent.trim()).toBe('No open jobs.');
    expect(jobs.querySelector('table')).toBeNull();
    expect(section(container, 'invoices').querySelector('.empty-box').textContent.trim()).toBe('No open invoices.');

    await fireEvent.click(getByRole('button', { name: 'show 2 completed' }));
    expect(jobs.querySelector('.empty-box')).toBeNull();
    expect(jobs.querySelectorAll('tbody tr')).toHaveLength(2);
    await fireEvent.click(getByRole('button', { name: 'hide 2 completed' }));
    expect(jobs.querySelector('.empty-box').textContent.trim()).toBe('No open jobs.');
  });

  it('hides the New purchase order link from a user with neither the financials nor jobs atom', () => {
    user.set({ id: 2, permissions: [] });
    const { queryByRole } = render(CustomerActivity, { props: { purchaseOrders: [], newPOHref: '#/x' } });
    expect(queryByRole('link', { name: 'New purchase order' })).toBeNull();
  });

  it('shows the New purchase order link to a jobs-atom user', () => {
    user.set({ id: 2, permissions: ['can_manage_jobs'] });
    const { queryByRole } = render(CustomerActivity, { props: { purchaseOrders: [], newPOHref: '#/x' } });
    expect(queryByRole('link', { name: 'New purchase order' })).not.toBeNull();
  });
});

describe('CustomerActivity — Contacts (business pages)', () => {
  it('lists contacts first with the default chip, mailto links, and row actions', async () => {
    const onNewJobFor = vi.fn();
    const onSetDefault = vi.fn();
    const onNewContact = vi.fn();
    const { container, getByRole } = render(CustomerActivity, {
      props: { jobs: JOBS, contacts: CONTACTS, defaultContactId: 9, onNewJobFor, onSetDefault, onNewContact },
    });
    const keys = Array.from(container.querySelectorAll('[data-section]')).map((el) => el.dataset.section);
    expect(keys[0]).toBe('contacts');
    const sec = section(container, 'contacts');
    expect(headersOf(sec.querySelector('table'))).toEqual(['Name', 'Email', 'Phone', '']);
    const rows = sec.querySelectorAll('tbody tr');
    expect(within(rows[0]).getByText('default')).toBeInTheDocument();
    expect(within(rows[0]).getByRole('link', { name: 'dana@x.test' })).toHaveAttribute('href', 'mailto:dana@x.test');
    expect(rows[1].querySelector('td[data-col="phone"]').textContent.trim()).toBe('555-0171'); // work fallback

    expect(within(rows[0]).getByRole('button', { name: 'Set as default' })).toBeDisabled();
    await fireEvent.click(within(rows[1]).getByRole('button', { name: 'Set as default' }));
    expect(onSetDefault).toHaveBeenCalledWith(10);
    await fireEvent.click(within(rows[1]).getByRole('button', { name: 'New job' }));
    expect(onNewJobFor).toHaveBeenCalledWith(10);
    await fireEvent.click(getByRole('button', { name: 'New contact' }));
    expect(onNewContact).toHaveBeenCalled();
  });

  it('omits the Contacts section entirely on contact pages (contacts = null)', () => {
    const { container } = render(CustomerActivity, { props: { jobs: JOBS } });
    expect(section(container, 'contacts')).toBeNull();
  });

  it('hides the actions column and New contact from a non-manager', () => {
    user.set({ id: 2, permissions: [] });
    const { container, queryByRole } = render(CustomerActivity, {
      props: { contacts: CONTACTS, defaultContactId: 9, onNewJobFor: vi.fn(), onSetDefault: vi.fn(), onNewContact: vi.fn() },
    });
    expect(headersOf(section(container, 'contacts').querySelector('table'))).toEqual(['Name', 'Email', 'Phone']);
    expect(queryByRole('button', { name: 'New contact' })).toBeNull();
  });

  it('shows no row actions for an inactive contact', () => {
    const contacts = [
      { contact_id: 9, name: 'Dana Whitfield', email: 'd@x.test', phone: '1', is_active: true },
      { contact_id: 10, name: 'Gone Away', email: '', phone: '2', is_active: false },
    ];
    const { container } = render(CustomerActivity, {
      props: { jobs: JOBS, contacts, defaultContactId: 9, onNewJobFor: vi.fn(), onSetDefault: vi.fn() },
    });
    const rows = section(container, 'contacts').querySelectorAll('tbody tr');
    expect(within(rows[0]).getByRole('button', { name: 'New job' })).toBeInTheDocument();
    expect(within(rows[1]).queryByRole('button', { name: 'New job' })).toBeNull();
    expect(within(rows[1]).queryByRole('button', { name: 'Set as default' })).toBeNull();
  });
});

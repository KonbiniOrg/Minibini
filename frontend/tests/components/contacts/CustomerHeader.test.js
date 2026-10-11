import { describe, it, expect, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import CustomerHeader from '@/components/contacts/CustomerHeader.svelte';
import Harness from './_CustomerHeaderHarness.svelte';

const FIN = {
  invoiced: '48910.00', profit: '17205.40', open_jobs: 2, outstanding: '4320.00',
  first_job_date: '2024-03-02', last_job_start: '2026-09-26',
};

describe('CustomerHeader', () => {
  it('renders the name', () => {
    const { getByText } = render(CustomerHeader, { props: { name: 'Jane Doe' } });
    expect(getByText('Jane Doe')).toBeInTheDocument();
  });

  it('links the business when provided (contact pages) and shows the default-contact chip', () => {
    const business = { business_id: 7, business_name: 'Acme Corp' };
    const { getByRole, getByText, rerender } = render(CustomerHeader, {
      props: { name: 'Jane Doe', kind: 'contact', business, isDefaultContact: true },
    });
    expect(getByRole('link', { name: 'Acme Corp' })).toHaveAttribute('href', '#/businesses/7');
    expect(getByText('default contact')).toBeInTheDocument();
  });

  it('shows (individual) for a contact without a business', () => {
    const { getByText } = render(CustomerHeader, { props: { name: 'Jane Doe', kind: 'contact' } });
    expect(getByText('(individual)')).toBeInTheDocument();
  });

  it('links the default contact and counts contacts (business pages)', () => {
    const defaultContact = { contact_id: 3, name: 'Jane Doe' };
    const { getByRole, getByText } = render(CustomerHeader, {
      props: { name: 'Acme Corp', defaultContact, contactCount: 3 },
    });
    expect(getByRole('link', { name: 'Jane Doe' })).toHaveAttribute('href', '#/contacts/3');
    expect(getByText(/3 contacts/)).toBeInTheDocument();
  });

  it('renders no subtitle on a business page without a default contact', () => {
    const { queryByRole, queryByText } = render(CustomerHeader, { props: { name: 'Acme Corp' } });
    expect(queryByRole('link')).toBeNull();
    expect(queryByText('(individual)')).toBeNull();
  });

  it('renders the numbers box and the facts line from the financials rollup', () => {
    const { getByText } = render(CustomerHeader, {
      props: { name: 'Acme Corp', financials: FIN, terms: 'Net 30' },
    });
    expect(getByText('2')).toBeInTheDocument();                 // open jobs
    expect(getByText('$4,320.00')).toBeInTheDocument();         // outstanding
    expect(getByText('$48,910.00')).toBeInTheDocument();        // invoiced
    expect(getByText('$17,205.40')).toBeInTheDocument();        // profit
    expect(getByText('Customer since Mar 2024 · Last job started Sep 26, 2026 · Net 30')).toBeInTheDocument();
  });

  it('says "Contact since" on contact pages and omits a missing last-job date', () => {
    const { getByText } = render(CustomerHeader, {
      props: { name: 'Jane', kind: 'contact', financials: { ...FIN, last_job_start: null } },
    });
    expect(getByText('Contact since Mar 2024')).toBeInTheDocument();
  });

  it('renders the page-supplied actions snippet', async () => {
    const onNewJob = vi.fn();
    const { getByRole } = render(Harness, { props: { name: 'Acme Corp', onNewJob } });
    await fireEvent.click(getByRole('button', { name: 'New Job' }));
    expect(onNewJob).toHaveBeenCalled();
    expect(getByRole('button', { name: 'Edit' })).toBeInTheDocument();
  });
});

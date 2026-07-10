import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import CustomerHeader from '@/components/contacts/CustomerHeader.svelte';

describe('CustomerHeader', () => {
  it('renders the name', () => {
    const { getByText } = render(CustomerHeader, { props: { name: 'Jane Doe' } });
    expect(getByText('Jane Doe')).toBeInTheDocument();
  });

  it('links the business when provided (contact pages)', () => {
    const business = { business_id: 7, business_name: 'Acme Corp' };
    const { getByRole } = render(CustomerHeader, { props: { name: 'Jane Doe', kind: 'contact', business } });
    const link = getByRole('link', { name: 'Acme Corp' });
    expect(link).toHaveAttribute('href', '#/businesses/7');
  });

  it('shows (individual) for a contact without a business', () => {
    const { getByText } = render(CustomerHeader, { props: { name: 'Jane Doe', kind: 'contact' } });
    expect(getByText('(individual)')).toBeInTheDocument();
  });

  it('links the default contact when provided (business pages)', () => {
    const defaultContact = { contact_id: 3, name: 'Jane Doe' };
    const { getByRole } = render(CustomerHeader, { props: { name: 'Acme Corp', defaultContact } });
    const link = getByRole('link', { name: 'Jane Doe' });
    expect(link).toHaveAttribute('href', '#/contacts/3');
  });

  it('renders no subtitle on a business page without a default contact (no stray "(individual)")', () => {
    const { queryByRole, queryByText } = render(CustomerHeader, { props: { name: 'Acme Corp' } });
    expect(queryByRole('link')).toBeNull();
    expect(queryByText('(individual)')).toBeNull();
  });

  it('renders the financial figures when provided', () => {
    const financials = { invoiced: '1200.00', profit: '300.00' };
    const { getByText } = render(CustomerHeader, { props: { name: 'Jane Doe', financials } });
    expect(getByText('$1,200.00')).toBeInTheDocument();
    expect(getByText('$300.00')).toBeInTheDocument();
  });
});

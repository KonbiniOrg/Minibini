import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import { viewMode } from '@/stores/viewMode.js';
import BusinessList from '@/components/contacts/BusinessList.svelte';

const businesses = [
  { business_id: 1, our_reference_code: 'ACM', business_name: 'Acme Corp', business_phone: '555-0200' },
  { business_id: 2, our_reference_code: 'GLB', business_name: 'Globex', business_phone: null },
];

const headers = (c) => Array.from(c.querySelectorAll('thead th')).map((th) => th.textContent.trim());

beforeEach(() => viewMode.set('lite'));

describe('BusinessList', () => {
  it('renders Reference / Name / Phone with data-col in both densities', () => {
    const { container } = render(BusinessList, { props: { businesses } });
    expect(headers(container)).toEqual(['Reference', 'Name', 'Phone']);
    expect(container.querySelectorAll('td[data-col="phone"]')[1].textContent.trim()).toBe('');
    viewMode.set('full');
    const { container: c2 } = render(BusinessList, { props: { businesses } });
    expect(headers(c2)).toEqual(['Reference', 'Name', 'Phone']);
  });

  it('renders the name as a button that calls onSelect with the row when given', async () => {
    const onSelect = vi.fn();
    const { getByRole } = render(BusinessList, { props: { businesses, onSelect } });
    await fireEvent.click(getByRole('button', { name: 'Globex' }));
    expect(onSelect).toHaveBeenCalledWith(businesses[1]);
  });

  it('renders the name as plain text when no onSelect is given', () => {
    const { queryByRole, getByText } = render(BusinessList, { props: { businesses } });
    expect(queryByRole('button', { name: 'Acme Corp' })).toBeNull();
    expect(getByText('Acme Corp')).toBeInTheDocument();
  });

  it('shows "No businesses found." for an empty list', () => {
    const { getByText } = render(BusinessList, { props: { businesses: [] } });
    expect(getByText('No businesses found.')).toBeInTheDocument();
  });
});

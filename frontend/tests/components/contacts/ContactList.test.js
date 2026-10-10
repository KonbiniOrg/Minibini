import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import { viewMode } from '@/stores/viewMode.js';
import ContactList from '@/components/contacts/ContactList.svelte';

const contacts = [
  { contact_id: 1, name: 'Jane Doe', email: 'jane@example.com', work_number: '555-0100' },
  { contact_id: 2, name: 'Sam Roe', email: '', mobile_number: '555-0200' },
];

const headers = (c) => Array.from(c.querySelectorAll('thead th')).map((th) => th.textContent.trim());

beforeEach(() => viewMode.set('lite'));

describe('ContactList', () => {
  it('renders Name / Email / Phone with data-col in both densities', async () => {
    const { container } = render(ContactList, { props: { contacts } });
    expect(headers(container)).toEqual(['Name', 'Email', 'Phone']);
    expect(container.querySelectorAll('td[data-col="phone"]')[1].textContent.trim()).toBe('555-0200');
    viewMode.set('full');
    const { container: c2 } = render(ContactList, { props: { contacts } });
    expect(headers(c2)).toEqual(['Name', 'Email', 'Phone']);
  });

  it('renders the name as a button that calls onSelect with the row when given', async () => {
    const onSelect = vi.fn();
    const { getByRole } = render(ContactList, { props: { contacts, onSelect } });
    await fireEvent.click(getByRole('button', { name: 'Jane Doe' }));
    expect(onSelect).toHaveBeenCalledWith(contacts[0]);
  });

  it('renders the name as plain text when no onSelect is given', () => {
    const { queryByRole, getByText } = render(ContactList, { props: { contacts } });
    expect(queryByRole('button', { name: 'Sam Roe' })).toBeNull();
    expect(getByText('Sam Roe')).toBeInTheDocument();
  });

  it('shows "No contacts found." for an empty list', () => {
    const { getByText } = render(ContactList, { props: { contacts: [] } });
    expect(getByText('No contacts found.')).toBeInTheDocument();
  });
});

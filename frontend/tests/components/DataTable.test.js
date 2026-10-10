import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from '@testing-library/svelte';
import { tick } from 'svelte';

// Replace the matchMedia-backed readable with a writable so tests can drive
// the layout axis directly (the store itself is covered in tests/stores/).
vi.mock('@/stores/layout.js', async () => {
  const { writable } = await import('svelte/store');
  return { layout: writable('desktop'), PHONE_MAX_WIDTH: 720 };
});

import { viewMode } from '@/stores/viewMode.js';
import { layout } from '@/stores/layout.js';
import Harness from './_DataTableHarness.svelte';

const rows = [
  { kind: 'contact',  id: 1, name: 'Jane Doe',  href: '#/contacts/1',   email: 'j@x.com', phone: '555-0100', tags: 'vip', total: '10.00' },
  { kind: 'business', id: 1, name: 'Acme Corp', href: '#/businesses/1', email: '',        phone: null,       tags: '',    total: '20.00' },
];

function headers(container) {
  return Array.from(container.querySelectorAll('thead th')).map((th) => th.textContent.trim());
}

beforeEach(() => {
  viewMode.set('lite');
  layout.set('desktop');
});

describe('DataTable — density (lite/full) column filtering', () => {
  it('omits lite:false columns in lite density', () => {
    const { container } = render(Harness, { props: { rows } });
    expect(headers(container)).toEqual(['Name', 'Email', 'Phone', 'Total']);
  });

  it('shows every column in full density', () => {
    viewMode.set('full');
    const { container } = render(Harness, { props: { rows } });
    expect(headers(container)).toEqual(['Name', 'Kind', 'Email', 'Phone number', 'Tags', 'Total']);
  });

  it('uses liteLabel only in lite density', async () => {
    const { container } = render(Harness, { props: { rows } });
    expect(headers(container)).toContain('Phone');
    expect(headers(container)).not.toContain('Phone number');
    viewMode.set('full');
    await tick();
    expect(headers(container)).toContain('Phone number');
    expect(headers(container)).not.toContain('Phone');
  });

  it('reacts to a density change after mount', async () => {
    const { container } = render(Harness, { props: { rows } });
    expect(headers(container)).not.toContain('Kind');
    viewMode.set('full');
    await tick();
    expect(headers(container)).toContain('Kind');
    viewMode.set('lite');
    await tick();
    expect(headers(container)).not.toContain('Kind');
  });
});

describe('DataTable — cells', () => {
  it('renders field columns as text and cell columns via the snippet', () => {
    viewMode.set('full');
    const { container, getByRole } = render(Harness, { props: { rows } });
    expect(getByRole('link', { name: 'Jane Doe' })).toHaveAttribute('href', '#/contacts/1');
    const firstRow = container.querySelector('tbody tr');
    expect(firstRow.querySelector('td[data-col="kind"]').textContent.trim()).toBe('contact');
    expect(firstRow.querySelector('td[data-col="email"]').textContent.trim()).toBe('j@x.com');
  });

  it('renders null/undefined field values as empty, never "null"/"undefined"', () => {
    const { container } = render(Harness, { props: { rows } });
    const secondRow = container.querySelectorAll('tbody tr')[1];
    expect(secondRow.querySelector('td[data-col="phone"]').textContent.trim()).toBe('');
    const bare = [{ kind: 'contact', id: 9, name: 'No Phone', href: '#/contacts/9' }];
    const { container: c2 } = render(Harness, { props: { rows: bare } });
    expect(c2.querySelector('td[data-col="phone"]').textContent.trim()).toBe('');
    expect(c2.textContent).not.toMatch(/undefined|null/);
  });

  it('stamps data-col on header and body cells and applies align', () => {
    const { container } = render(Harness, { props: { rows } });
    expect(container.querySelector('th[data-col="total"]')).toBeTruthy();
    const totalCell = container.querySelector('td[data-col="total"]');
    expect(totalCell).toBeTruthy();
    expect(totalCell.getAttribute('style')).toMatch(/text-align:\s*right/);
  });

  it('keys rows by the supplied key so same-id rows of different kinds both render', () => {
    const { container } = render(Harness, { props: { rows } });
    expect(container.querySelectorAll('tbody tr')).toHaveLength(2);
  });

  it('always wraps rows in thead/tbody', () => {
    const { container } = render(Harness, { props: { rows } });
    expect(container.querySelectorAll('table > tr')).toHaveLength(0);
    expect(container.querySelectorAll('thead > tr')).toHaveLength(1);
    expect(container.querySelectorAll('tbody > tr')).toHaveLength(2);
  });
});

describe('DataTable — empty state', () => {
  it('renders the default empty text and no table when rows is empty', () => {
    const { container, getByText } = render(Harness, { props: { rows: [] } });
    expect(getByText('No results found.')).toBeInTheDocument();
    expect(container.querySelector('table')).toBeNull();
  });

  it('renders a custom emptyText', () => {
    const { getByText } = render(Harness, { props: { rows: [], emptyText: 'No contacts yet.' } });
    expect(getByText('No contacts yet.')).toBeInTheDocument();
  });
});

describe('DataTable — phone layout', () => {
  it('renders stacked cards instead of a table, omitting phone:false columns', () => {
    layout.set('phone');
    const { container } = render(Harness, { props: { rows } });
    expect(container.querySelector('table')).toBeNull();
    const cards = container.querySelectorAll('ul.data-cards > li.data-card');
    expect(cards).toHaveLength(2);
    const labels = Array.from(cards[0].querySelectorAll('dt')).map((dt) => dt.textContent.trim());
    // lite + phone: Kind (lite:false), Email (phone:false), Tags (both) are gone.
    expect(labels).toEqual(['Name', 'Phone', 'Total']);
    expect(cards[0].querySelector('dd[data-col="name"] a')).toHaveAttribute('href', '#/contacts/1');
  });

  it('phone layout in full density hides phone:false columns but shows lite:false ones', () => {
    layout.set('phone');
    viewMode.set('full');
    const { container } = render(Harness, { props: { rows } });
    const labels = Array.from(container.querySelectorAll('li.data-card')[0].querySelectorAll('dt'))
      .map((dt) => dt.textContent.trim());
    expect(labels).toEqual(['Name', 'Kind', 'Phone number', 'Total']);
  });

  it('switches between table and cards when layout changes after mount', async () => {
    const { container } = render(Harness, { props: { rows } });
    expect(container.querySelector('table')).toBeTruthy();
    layout.set('phone');
    await tick();
    expect(container.querySelector('table')).toBeNull();
    expect(container.querySelector('ul.data-cards')).toBeTruthy();
    layout.set('desktop');
    await tick();
    expect(container.querySelector('table')).toBeTruthy();
  });

  it('passes the extra class to whichever root is rendered', async () => {
    const { container } = render(Harness, { props: { rows, extraClass: 'contacts-table' } });
    expect(container.querySelector('table.data-table.contacts-table')).toBeTruthy();
    layout.set('phone');
    await tick();
    expect(container.querySelector('ul.data-cards.contacts-table')).toBeTruthy();
  });
});

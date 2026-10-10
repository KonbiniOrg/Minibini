import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, waitFor } from '@testing-library/svelte';
import { tick } from 'svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() }, errorMessage: (e, fallback) => e?.message || fallback }));
vi.mock('svelte-spa-router', async () => {
  const { readable } = await import('svelte/store');
  return { querystring: readable('q=acme'), push: vi.fn(), link: () => {} };
});

import { api } from '@/lib/api.js';
import { viewMode } from '@/stores/viewMode.js';
import Search from '@/routes/Search.svelte';

const payload = {
  query: 'acme', total: 2,
  results: {
    jobs: [{
      job: { job_id: 7, job_number: 'JOB-7', name: 'Acme signage', contact_name: 'Jane', status: 'approved',
             created_date: '2026-09-01T00:00:00Z', start_date: null, description: 'Big acme sign', customer_po_number: 'PO-1' },
      tasks: [{ name: 'Cut acme letters' }],
    }],
    contacts: [{ contact_id: 3, name: 'Acme Jane', business_name: 'Acme Corp', email: 'j@acme.com',
                 mobile_number: '555-1', work_number: '555-2', home_number: '555-3', city: 'Springfield' }],
    businesses: [], invoices: [], estimates: [], purchase_orders: [], inventory_items: [],
  },
};

function headersOf(table) {
  return Array.from(table.querySelectorAll('thead th')).map((th) => th.textContent.trim());
}

beforeEach(() => {
  api.get.mockReset();
  api.get.mockResolvedValue(payload);
  viewMode.set('lite');
});

describe('Search results tables — DataTable pilot', () => {
  it('renders job and contact result tables with highlighted, linked identifiers', async () => {
    const { container, getByRole } = render(Search);
    await waitFor(() => expect(container.querySelectorAll('table.data-table')).toHaveLength(2));
    const jobLink = getByRole('link', { name: /JOB-7/ });
    expect(jobLink).toHaveAttribute('href', '#/jobs/7');
    // hl() wraps the match in <mark>; the snippet must still emit it as HTML.
    expect(container.querySelector('td[data-col="name"] mark')).toBeTruthy();
    expect(getByRole('link', { name: /Acme Jane/ })).toHaveAttribute('href', '#/contacts/3');
  });

  it('shows the same columns in lite and full (no lite-content decisions yet)', async () => {
    const jobHeaders = ['Job #', 'Name', 'Contact', 'Status', 'Created', 'Started', 'Description', 'Customer PO', 'Matching Tasks'];
    const contactHeaders = ['Name', 'Business', 'Email', 'Mobile', 'Work', 'Home', 'City'];
    const { container } = render(Search);
    await waitFor(() => expect(container.querySelectorAll('table.data-table')).toHaveLength(2));
    let [jobs, contacts] = container.querySelectorAll('table.data-table');
    expect(headersOf(jobs)).toEqual(jobHeaders);
    expect(headersOf(contacts)).toEqual(contactHeaders);
    viewMode.set('full');
    await tick();
    [jobs, contacts] = container.querySelectorAll('table.data-table');
    expect(headersOf(jobs)).toEqual(jobHeaders);
    expect(headersOf(contacts)).toEqual(contactHeaders);
  });

  it('renders dashes for empty values via hl()', async () => {
    viewMode.set('full');
    const { container } = render(Search);
    await waitFor(() => expect(container.querySelectorAll('table.data-table')).toHaveLength(2));
    const jobs = container.querySelector('table.data-table');
    expect(jobs.querySelector('td[data-col="started"]').textContent.trim()).toBe('—');
  });
});

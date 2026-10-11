import { describe, it, expect } from 'vitest';
import {
  isClosedJob, isClosedInvoice, isClosedPO,
  splitRows, showLabel, orderSections, statusLabel, canDeleteBusiness, canDeleteContact,
  customerFacts, siblingJobCounts,
} from '@/lib/customerActivity.js';

describe('customerActivity — closed sets', () => {
  it('jobs: completed / rejected / cancelled are closed', () => {
    expect(isClosedJob({ status: 'completed' })).toBe(true);
    expect(isClosedJob({ status: 'rejected' })).toBe(true);
    expect(isClosedJob({ status: 'cancelled' })).toBe(true);
    expect(isClosedJob({ status: 'in_progress' })).toBe(false);
    expect(isClosedJob({ status: 'work_complete' })).toBe(false);
  });
  it('invoices: paid / cancelled / superseded are closed; partly-paid is open', () => {
    expect(isClosedInvoice({ status: 'paid' })).toBe(true);
    expect(isClosedInvoice({ status: 'superseded' })).toBe(true);
    expect(isClosedInvoice({ status: 'partly-paid' })).toBe(false);
    expect(isClosedInvoice({ status: 'open' })).toBe(false);
  });
  it('POs: received_in_full / cancelled are closed', () => {
    expect(isClosedPO({ status: 'received_in_full' })).toBe(true);
    expect(isClosedPO({ status: 'partly_received' })).toBe(false);
  });
});

describe('customerActivity — splitRows and labels', () => {
  const rows = [{ status: 'open' }, { status: 'paid' }, { status: 'paid' }];
  it('splits open from closed, preserving order', () => {
    const { open, closed } = splitRows(rows, isClosedInvoice);
    expect(open).toEqual([{ status: 'open' }]);
    expect(closed).toHaveLength(2);
  });
  it('labels the toggle with the count and the kind word', () => {
    expect(showLabel(3, 'completed', false)).toBe('show 3 completed');
    expect(showLabel(3, 'completed', true)).toBe('hide 3 completed');
    expect(showLabel(1, 'paid', false)).toBe('show 1 paid');
    expect(showLabel(0, 'paid', false)).toBeNull();
  });
  it('maps raw statuses to human labels', () => {
    expect(statusLabel('in_progress')).toBe('In progress');
    expect(statusLabel('work_complete')).toBe('Work complete');
    expect(statusLabel('partly-paid')).toBe('Partly paid');
    expect(statusLabel('received_in_full')).toBe('Received in full');
    expect(statusLabel('mystery_status')).toBe('Mystery status');
  });
});

describe('customerActivity — section ordering', () => {
  it('keeps the canonical order among populated sections and sinks empty ones', () => {
    const sections = [
      { key: 'jobs', total: 0 },
      { key: 'invoices', total: 2 },
      { key: 'pos', total: 1 },
    ];
    expect(orderSections(sections).map((s) => s.key)).toEqual(['invoices', 'pos', 'jobs']);
  });
  it('is stable when nothing is empty', () => {
    const sections = [{ key: 'jobs', total: 1 }, { key: 'invoices', total: 1 }, { key: 'pos', total: 1 }];
    expect(orderSections(sections).map((s) => s.key)).toEqual(['jobs', 'invoices', 'pos']);
  });
});

describe('customerActivity — delete rule', () => {
  it('a business is deletable only with no jobs, no POs and at most one contact', () => {
    expect(canDeleteBusiness({ jobs: [], poCount: 0, contacts: [{}] })).toBe(true);
    expect(canDeleteBusiness({ jobs: [], poCount: 0, contacts: [] })).toBe(true);
    expect(canDeleteBusiness({ jobs: [{}], poCount: 0, contacts: [{}] })).toBe(false);
    expect(canDeleteBusiness({ jobs: [], poCount: 1, contacts: [{}] })).toBe(false);
    expect(canDeleteBusiness({ jobs: [], poCount: 0, contacts: [{}, {}] })).toBe(false);
  });
  it('a contact is deletable only with no jobs and not as the only contact of its business', () => {
    expect(canDeleteContact({ jobs: [], hasBusiness: false, siblingCount: 0 })).toBe(true);
    expect(canDeleteContact({ jobs: [], hasBusiness: true, siblingCount: 1 })).toBe(true);
    expect(canDeleteContact({ jobs: [], hasBusiness: true, siblingCount: 0 })).toBe(false);
    expect(canDeleteContact({ jobs: [{}], hasBusiness: false, siblingCount: 0 })).toBe(false);
  });
});

describe('customerActivity — banner facts line', () => {
  it('joins the present facts with dots and omits nulls', () => {
    const f = { first_job_date: '2024-03-02', last_job_start: '2026-09-26' };
    expect(customerFacts(f, { kind: 'business', terms: 'Net 30' }))
      .toBe('Customer since Mar 2024 · Last job started Sep 26, 2026 · Net 30');
    expect(customerFacts({ first_job_date: null, last_job_start: null }, { kind: 'contact' })).toBe('');
    expect(customerFacts({ first_job_date: '2024-03-02', last_job_start: null }, { kind: 'contact' }))
      .toBe('Contact since Mar 2024');
  });
  it('returns an empty string without financials', () => {
    expect(customerFacts(null, { kind: 'business' })).toBe('');
  });
});

describe('customerActivity — siblings', () => {
  it('counts jobs per contact from the business payload and excludes self', () => {
    const business = {
      contacts: [{ contact_id: 1, name: 'Me' }, { contact_id: 2, name: 'A' }, { contact_id: 3, name: 'B' }],
      jobs: [{ contact: 2 }, { contact: 2 }, { contact: 1 }],
    };
    expect(siblingJobCounts(business, 1)).toEqual([
      { contact_id: 2, name: 'A', jobCount: 2 },
      { contact_id: 3, name: 'B', jobCount: 0 },
    ]);
    expect(siblingJobCounts(null, 1)).toEqual([]);
  });
});

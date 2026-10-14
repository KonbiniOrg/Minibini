import { describe, it, expect } from 'vitest';
import { UNPAID_SECTIONS, unpaidSectionKey, unpaidSectionColor } from '@/lib/unpaidSections.js';

const inv = (status) => ({ invoice_id: 1, status });

describe('unpaidSectionKey', () => {
  it('trusts a work_complete sub-status as-is', () => {
    expect(unpaidSectionKey({ status: 'work_complete', sub_status: 'needs-invoice', invoices: [] })).toBe('needs-invoice');
    expect(unpaidSectionKey({ status: 'work_complete', sub_status: 'invoice-prepped', invoices: [] })).toBe('invoice-prepped');
    expect(unpaidSectionKey({ status: 'work_complete', sub_status: 'invoice-sent', invoices: [] })).toBe('invoice-sent');
  });

  // Mirror of BoardService._work_complete_sub_status for cards whose
  // sub_status is not one of the three: held (on-hold), cancelled (null),
  // in_progress (work-ready / in-progress / ...).
  it('derives Awaiting Payment from any sent-and-owed invoice', () => {
    for (const status of ['open', 'partly-paid', 'defaulted']) {
      expect(unpaidSectionKey({ status: 'in_progress', sub_status: 'in-progress', invoices: [inv(status)] })).toBe('invoice-sent');
    }
  });

  it('a sent invoice outranks a draft on the same job', () => {
    expect(unpaidSectionKey({ status: 'cancelled', sub_status: null, invoices: [inv('draft'), inv('open')] })).toBe('invoice-sent');
  });

  it('derives Invoice Drafted from a draft when nothing is sent', () => {
    expect(unpaidSectionKey({ status: 'in_progress', sub_status: 'work-ready', invoices: [inv('draft'), inv('paid')] })).toBe('invoice-prepped');
  });

  it('falls through to Needs Invoice when only paid invoices remain (deposit paid, final not started)', () => {
    expect(unpaidSectionKey({ status: 'work_complete', sub_status: 'on-hold', invoices: [inv('paid')] })).toBe('needs-invoice');
    expect(unpaidSectionKey({ status: 'work_complete', sub_status: 'on-hold' })).toBe('needs-invoice');
  });

  it('ignores cancelled and superseded invoices', () => {
    expect(unpaidSectionKey({ status: 'work_complete', sub_status: 'on-hold', invoices: [inv('cancelled'), inv('superseded')] })).toBe('needs-invoice');
  });
});

describe('UNPAID_SECTIONS', () => {
  it('lists the three groups in column order with their tab colors', () => {
    expect(UNPAID_SECTIONS.map((s) => s.key)).toEqual(['needs-invoice', 'invoice-prepped', 'invoice-sent']);
    expect(unpaidSectionColor('needs-invoice')).toBe('#64748b');
    expect(unpaidSectionColor('invoice-prepped')).toBe('#f59e0b');
    expect(unpaidSectionColor('invoice-sent')).toBe('#3b82f6');
  });
});

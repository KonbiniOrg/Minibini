import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import UnpaidCard from '@/components/board/UnpaidCard.svelte';

// sub_status 'needs-invoice' renders the simple block (no invoice table),
// keeping the fixture minimal for these display assertions.
const baseJob = {
  job_number: 'JOB-1', name: 'Widget', contact_id: 5, contact_name: 'Acme',
  sub_status: 'needs-invoice', invoices: [], billed: 0, spent: 0, profit: 0,
};

describe('UnpaidCard project manager line', () => {
  it('shows "PM: <name>" under the customer when a PM is set', () => {
    const { getByText } = render(UnpaidCard, {
      props: { job: { ...baseJob, project_manager_name: 'Rachel McConnell' } },
    });
    expect(getByText('PM: Rachel McConnell')).toBeInTheDocument();
  });

  it('renders no PM line when there is no PM', () => {
    const { container } = render(UnpaidCard, { props: { job: { ...baseJob } } });
    expect(container.querySelector('.pm-line')).toBeNull();
  });
});

describe('UnpaidCard deposit banner', () => {
  it('shows DEP REQUESTED when the job has an outstanding deposit request', () => {
    const { getByText } = render(UnpaidCard, {
      props: { job: { ...baseJob, deposit_state: 'requested' } },
    });
    expect(getByText('DEP REQUESTED')).toBeInTheDocument();
  });

  it('shows DEP PAID when the deposit is paid and unconsumed', () => {
    const { getByText, container } = render(UnpaidCard, {
      props: { job: { ...baseJob, deposit_state: 'paid' } },
    });
    expect(getByText('DEP PAID')).toBeInTheDocument();
    expect(container.querySelector('.deposit-banner.deposit-paid')).not.toBeNull();
  });

  it('renders no banner when deposit_state is null', () => {
    const { container } = render(UnpaidCard, { props: { job: { ...baseJob } } });
    expect(container.querySelector('.deposit-banner')).toBeNull();
  });
});

describe('UnpaidCard tab color follows the section bucket', () => {
  const tab = (container) => container.querySelector('.card-border').style.background;

  it('grey for needs-invoice, amber for a draft, blue for sent', () => {
    expect(tab(render(UnpaidCard, { props: { job: { ...baseJob } } }).container)).toBe('rgb(100, 116, 139)');
    expect(tab(render(UnpaidCard, { props: { job: {
      ...baseJob, sub_status: 'invoice-prepped', invoices: [{ invoice_id: 1, display_number: 'INV-1', status: 'draft', total: '10.00' }],
    } } }).container)).toBe('rgb(245, 158, 11)');
    expect(tab(render(UnpaidCard, { props: { job: {
      ...baseJob, sub_status: 'invoice-sent', invoices: [{ invoice_id: 1, display_number: 'INV-1', status: 'partly-paid', total: '10.00' }],
    } } }).container)).toBe('rgb(59, 130, 246)');
  });

  it('derives the color from invoices when sub_status is not an invoice state (cancelled job, draft invoice → amber)', () => {
    const { container } = render(UnpaidCard, { props: { job: {
      ...baseJob, status: 'cancelled', sub_status: null,
      invoices: [{ invoice_id: 1, display_number: 'INV-1', status: 'draft', total: '10.00' }],
    } } });
    expect(tab(container)).toBe('rgb(245, 158, 11)');
  });

  it('a held work_complete job with only a paid deposit renders the Needs Invoice block, not an empty table', () => {
    const { container, getByText } = render(UnpaidCard, { props: { job: {
      ...baseJob, status: 'work_complete', sub_status: 'on-hold', on_hold: true,
      invoices: [{ invoice_id: 1, display_number: 'INV-1', status: 'paid', total: '10.00' }],
    } } });
    expect(getByText('Needs Invoice')).toBeInTheDocument();
    expect(container.querySelector('.line-table')).toBeNull();
  });
});

describe('UnpaidCard job-status badge', () => {
  const sentJob = {
    ...baseJob, sub_status: 'invoice-sent',
    invoices: [{ invoice_id: 1, display_number: 'INV-1', status: 'open', total: '10.00' }],
  };

  it('renders no badge for a work_complete job', () => {
    const { container } = render(UnpaidCard, { props: { job: { ...sentJob, status: 'work_complete' } } });
    expect(container.querySelector('.status-badge')).toBeNull();
  });

  it('badges an in_progress job so the reader sees why active work sits in the money column', () => {
    const { container } = render(UnpaidCard, { props: { job: { ...sentJob, status: 'in_progress', sub_status: 'in-progress' } } });
    expect(container.querySelector('.status-badge').textContent.trim()).toBe('In Progress');
  });

  it('badges a cancelled job carrying a receivable', () => {
    const { container } = render(UnpaidCard, { props: { job: { ...sentJob, status: 'cancelled', sub_status: null } } });
    expect(container.querySelector('.status-badge').textContent.trim()).toBe('Cancelled');
  });
});

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), postMultipart: vi.fn() },
}));
vi.mock('svelte-spa-router', () => ({
  link: () => {},
  push: vi.fn(),
}));

import { api } from '@/lib/api.js';
import { push } from 'svelte-spa-router';
import InvoiceSendPage from '@/routes/invoices/InvoiceSendPage.svelte';

const INVOICE = {
  invoice_id: 5, job: 9, display_number: 'INV-5', status: 'draft',
  qbo_id: null, line_items: [],
};
const SEND_DEFAULTS = { to: 'client@example.com', subject: 'S', body: 'B', attachments_preview: [] };

function makeInvoice(overrides = {}) {
  return {
    invoice_id: 1, job: 9, display_number: 'INV-1', status: 'draft', line_items: [],
    ...overrides,
  };
}
function makeDepositLine(overrides = {}) {
  return {
    line_item_id: 501, line_number: 1, description: 'Deposit on JOB-9',
    qty: '1', price: '5000.00', units: 'none', is_deposit: true, sources: [],
    ...overrides,
  };
}

function mockApi({ jobInvoices = [] } = {}) {
  api.get.mockReset();
  api.get.mockImplementation((url) => {
    if (url === '/api/invoices/5/') return Promise.resolve({ ...INVOICE });
    if (url === '/api/invoices/5/send-defaults/') return Promise.resolve({ ...SEND_DEFAULTS });
    if (url.startsWith('/api/invoices/?job=')) return Promise.resolve({ results: jobInvoices });
    return Promise.resolve({});
  });
}

beforeEach(() => {
  api.postMultipart?.mockReset?.();
  push.mockReset?.();
});

// A test that asserts an exact window.confirm call count must never leak
// its spy into the next test — restore unconditionally, even after an
// assertion failure (vi.spyOn on an already-spied method reuses the same
// mock and its accumulated call history otherwise).
afterEach(() => {
  vi.restoreAllMocks();
});

describe('InvoiceSendPage — unapplied deposit credit send-time confirm', () => {
  it('confirms twice (send + deposit-credit) and proceeds with the send when an unapplied credit exists', async () => {
    const paidDeposit = makeInvoice({
      invoice_id: 100, display_number: 'INV-1042', status: 'paid',
      line_items: [makeDepositLine()],
    });
    mockApi({ jobInvoices: [INVOICE, paidDeposit] });
    api.postMultipart.mockResolvedValue({ message: 'sent' });
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);

    const { findByRole } = render(InvoiceSendPage, { props: { params: { id: '5' } } });
    await fireEvent.click(await findByRole('button', { name: 'Send Invoice' }));

    await waitFor(() => expect(api.postMultipart).toHaveBeenCalled());
    expect(confirmSpy).toHaveBeenCalledWith(
      "There's an unapplied deposit credit on this job — send anyway?"
    );
    expect(confirmSpy).toHaveBeenCalledTimes(2);
    await waitFor(() => expect(push).toHaveBeenCalledWith('/invoices/5'));
    confirmSpy.mockRestore();
  });

  it('aborts the send when the deposit-credit confirm is cancelled, leaving state intact', async () => {
    const paidDeposit = makeInvoice({
      invoice_id: 100, display_number: 'INV-1042', status: 'paid',
      line_items: [makeDepositLine()],
    });
    mockApi({ jobInvoices: [INVOICE, paidDeposit] });
    api.postMultipart.mockResolvedValue({ message: 'sent' });
    // First confirm (DocumentSendForm's "Send this email to…?") → OK.
    // Second confirm (ours, the deposit-credit guard) → Cancel.
    const confirmSpy = vi.spyOn(window, 'confirm')
      .mockReturnValueOnce(true)
      .mockReturnValueOnce(false);

    const { findByRole } = render(InvoiceSendPage, { props: { params: { id: '5' } } });
    await fireEvent.click(await findByRole('button', { name: 'Send Invoice' }));

    expect(confirmSpy).toHaveBeenCalledTimes(2);
    expect(api.postMultipart).not.toHaveBeenCalled();
    expect(push).not.toHaveBeenCalled();
    // Send dialog/state intact: the button is enabled again (not stuck on "Sending…").
    expect(await findByRole('button', { name: 'Send Invoice' })).not.toBeDisabled();
    confirmSpy.mockRestore();
  });

  it('does not confirm about deposit credits when none are unapplied', async () => {
    mockApi({ jobInvoices: [INVOICE] });
    api.postMultipart.mockResolvedValue({ message: 'sent' });
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);

    const { findByRole } = render(InvoiceSendPage, { props: { params: { id: '5' } } });
    await fireEvent.click(await findByRole('button', { name: 'Send Invoice' }));

    await waitFor(() => expect(api.postMultipart).toHaveBeenCalled());
    expect(confirmSpy).toHaveBeenCalledTimes(1); // just DocumentSendForm's own confirm
    confirmSpy.mockRestore();
  });

  it('renders a negative line/total with the sign before the dollar sign (I2)', async () => {
    api.get.mockReset();
    api.get.mockImplementation((url) => {
      if (url === '/api/invoices/5/') {
        return Promise.resolve({
          ...INVOICE,
          line_items: [
            { line_item_id: 1, line_number: 1, description: 'Credit', qty: '1', price: '-500.00' },
          ],
        });
      }
      if (url === '/api/invoices/5/send-defaults/') return Promise.resolve({ ...SEND_DEFAULTS });
      if (url.startsWith('/api/invoices/?job=')) return Promise.resolve({ results: [] });
      return Promise.resolve({});
    });

    const { findAllByText } = render(InvoiceSendPage, { props: { params: { id: '5' } } });
    const matches = await findAllByText('-$500.00');
    expect(matches.length).toBeGreaterThan(0);
  });

  it('does not confirm about deposit credits when the only credit is already applied', async () => {
    const paidDeposit = makeInvoice({
      invoice_id: 100, display_number: 'INV-1042', status: 'paid',
      line_items: [makeDepositLine()],
    });
    const claiming = makeInvoice({
      invoice_id: 200, display_number: 'INV-2000', status: 'open',
      line_items: [{
        line_item_id: 601, line_number: 1, description: 'Less deposit (INV-1042)',
        qty: '1', price: '-5000.00', units: 'none', is_deposit: false,
        sources: [{ source_id: 1, source_type: 'deposit', source_pk: 501 }],
      }],
    });
    mockApi({ jobInvoices: [INVOICE, paidDeposit, claiming] });
    api.postMultipart.mockResolvedValue({ message: 'sent' });
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);

    const { findByRole } = render(InvoiceSendPage, { props: { params: { id: '5' } } });
    await fireEvent.click(await findByRole('button', { name: 'Send Invoice' }));

    await waitFor(() => expect(api.postMultipart).toHaveBeenCalled());
    expect(confirmSpy).toHaveBeenCalledTimes(1);
    confirmSpy.mockRestore();
  });
});

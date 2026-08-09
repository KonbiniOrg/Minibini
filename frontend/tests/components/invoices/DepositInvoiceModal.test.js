import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { post: vi.fn() },
  errorMessage: (e, fallback) => e?.data?.detail || e?.message || fallback || 'Error',
}));
vi.mock('@/stores/messages.js', () => ({ showError: vi.fn(), showSuccess: vi.fn() }));

import { api } from '@/lib/api.js';
import { showError } from '@/stores/messages.js';
import DepositInvoiceModal from '@/components/invoices/DepositInvoiceModal.svelte';

const JOB = { job_id: 9, job_number: 'JOB-9' };

beforeEach(() => {
  api.post.mockReset();
  showError.mockReset();
});

describe('DepositInvoiceModal', () => {
  it('renders an Amount input when open', () => {
    const { getByLabelText } = render(DepositInvoiceModal, {
      props: { open: true, job: JOB },
    });
    expect(getByLabelText(/amount/i)).toBeInTheDocument();
  });

  it('Create posts the invoice-create then the deposit line with the exact payload', async () => {
    api.post.mockImplementation((url) => {
      if (url === '/api/invoices/') return Promise.resolve({ invoice_id: 42 });
      return Promise.resolve({ line_item_id: 1 });
    });
    const onCreated = vi.fn();
    const { getByLabelText, getByRole } = render(DepositInvoiceModal, {
      props: { open: true, job: JOB, onCreated },
    });
    await fireEvent.input(getByLabelText(/amount/i), { target: { value: '2500' } });
    await fireEvent.click(getByRole('button', { name: /create/i }));

    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(42));
    expect(api.post).toHaveBeenNthCalledWith(1, '/api/invoices/', { job: 9, seed: false });
    expect(api.post).toHaveBeenNthCalledWith(2, '/api/invoices/42/line-items/', {
      deposit: true, description: 'Deposit on JOB-9', qty: '1', units: 'none', price: '2500',
    });
  });

  it('progress variant retitles the modal and posts a progress-billing line description (spec §7.2 relabel)', async () => {
    api.post.mockImplementation((url) => {
      if (url === '/api/invoices/') return Promise.resolve({ invoice_id: 42 });
      return Promise.resolve({ line_item_id: 1 });
    });
    const onCreated = vi.fn();
    const { getByLabelText, getByRole } = render(DepositInvoiceModal, {
      props: { open: true, job: JOB, onCreated, variant: 'progress' },
    });
    expect(getByRole('heading', { name: /add progress invoice/i })).toBeInTheDocument();
    await fireEvent.input(getByLabelText(/amount/i), { target: { value: '2500' } });
    await fireEvent.click(getByRole('button', { name: /create/i }));

    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(42));
    // Still an unseeded draft with a deposit-rail line — only the words change.
    expect(api.post).toHaveBeenNthCalledWith(1, '/api/invoices/', { job: 9, seed: false });
    expect(api.post).toHaveBeenNthCalledWith(2, '/api/invoices/42/line-items/', {
      deposit: true, description: 'Progress billing on JOB-9', qty: '1', units: 'none', price: '2500',
    });
  });

  it('Cancel posts nothing', async () => {
    const onClose = vi.fn();
    const { getByLabelText, getByRole } = render(DepositInvoiceModal, {
      props: { open: true, job: JOB, onClose },
    });
    await fireEvent.input(getByLabelText(/amount/i), { target: { value: '2500' } });
    await fireEvent.click(getByRole('button', { name: /cancel/i }));
    expect(api.post).not.toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });

  it('blocks an invalid (empty) amount with a field error and posts nothing', async () => {
    const { getByRole, findByText } = render(DepositInvoiceModal, {
      props: { open: true, job: JOB },
    });
    await fireEvent.click(getByRole('button', { name: /create/i }));
    expect(await findByText(/greater than 0/i)).toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
  });

  it('blocks a zero/negative amount with a field error and posts nothing', async () => {
    const { getByLabelText, getByRole, findByText } = render(DepositInvoiceModal, {
      props: { open: true, job: JOB },
    });
    await fireEvent.input(getByLabelText(/amount/i), { target: { value: '0' } });
    await fireEvent.click(getByRole('button', { name: /create/i }));
    expect(await findByText(/greater than 0/i)).toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
  });

  it('on step-1 failure, shows the form error and does not attempt the deposit line', async () => {
    api.post.mockRejectedValueOnce({
      status: 400, message: 'Bad request',
      data: { detail: 'Job must be approved before invoicing.' },
    });
    const { getByLabelText, getByRole, findByText } = render(DepositInvoiceModal, {
      props: { open: true, job: JOB },
    });
    await fireEvent.input(getByLabelText(/amount/i), { target: { value: '2500' } });
    await fireEvent.click(getByRole('button', { name: /create/i }));
    expect(await findByText(/job must be approved/i)).toBeInTheDocument();
    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
  });

  it('on step-2 failure, still shows the created draft (via onCreated) and surfaces the coaching message via the overlay', async () => {
    api.post.mockImplementation((url) => {
      if (url === '/api/invoices/') return Promise.resolve({ invoice_id: 42 });
      return Promise.reject({
        status: 400, message: 'Bad request',
        data: { accounting_category: ['No default deposit accounting category is configured.'] },
      });
    });
    const onCreated = vi.fn();
    const { getByLabelText, getByRole } = render(DepositInvoiceModal, {
      props: { open: true, job: JOB, onCreated },
    });
    await fireEvent.input(getByLabelText(/amount/i), { target: { value: '2500' } });
    await fireEvent.click(getByRole('button', { name: /create/i }));

    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(42));
    expect(showError).toHaveBeenCalledWith(expect.stringMatching(/no default deposit accounting category/i));
  });
});

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn(), delete: vi.fn() }, errorMessage: (e, fb) => e?.message || fb }));
vi.mock('@/lib/paymentAccounts.js', () => ({ getPaymentAccounts: vi.fn() }));

import { api } from '@/lib/api.js';
import { getPaymentAccounts } from '@/lib/paymentAccounts.js';
import UserReimbursementPanel from '@/components/expenses/UserReimbursementPanel.svelte';

const OUTSTANDING = [
  { id: 1, purchased_on: '2026-03-01', description: 'Lunch', accounting_category: 'Meals', amount: '12.50' },
];

const BATCH = {
  id: 9, paid_on: '2026-02-01', expense_count: 2, total: '40.00',
  reference_number: '', qbo_sync_status: 'sync_failed',
};

beforeEach(() => {
  api.get.mockReset();
  getPaymentAccounts.mockReset();
  getPaymentAccounts.mockResolvedValue([
    { qbo_account_id: '35', display_name: 'Checking', account_type: 'Bank' },
  ]);
  api.get.mockImplementation((url) => {
    if (url.includes('/api/expenses/') && url.includes('status=submitted')) return Promise.resolve({ results: OUTSTANDING });
    if (url.startsWith('/api/reimbursements/')) return Promise.resolve({ results: [BATCH] });
    return Promise.resolve({ results: [] });
  });
  api.delete.mockReset();
  api.delete.mockResolvedValue({});
});

describe('UserReimbursementPanel', () => {
  it('loads and lists outstanding reimbursements', async () => {
    const { findByText } = render(UserReimbursementPanel, { props: { user: { id: 7 } } });
    expect(await findByText('Lunch')).toBeInTheDocument();
  });

  it('reveals the batch action once a row is selected', async () => {
    const { findAllByRole, findByText } = render(UserReimbursementPanel, { props: { user: { id: 7 } } });
    const checkboxes = await findAllByRole('checkbox');
    // [0] is the header select-all; [1] is the first row.
    await fireEvent.click(checkboxes[1]);
    expect(await findByText(/Reimburse selected/)).toBeInTheDocument();
  });

  it('unwinds a batch through the confirm-guarded delete endpoint', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    const { findByRole } = render(UserReimbursementPanel, { props: { user: { id: 7 } } });
    await fireEvent.click(await findByRole('button', { name: 'unwind' }));
    expect(api.delete).toHaveBeenCalledWith('/api/reimbursements/9/?confirm=true');
    confirmSpy.mockRestore();
  });

  it('does not unwind when the confirm is declined', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false);
    const { findByRole } = render(UserReimbursementPanel, { props: { user: { id: 7 } } });
    await fireEvent.click(await findByRole('button', { name: 'unwind' }));
    expect(api.delete).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });

  it('blocks reimbursing with a message when no payment accounts are configured', async () => {
    getPaymentAccounts.mockResolvedValue([]);
    const { findAllByRole, findByText, queryByText } = render(UserReimbursementPanel, { props: { user: { id: 7 } } });
    const checkboxes = await findAllByRole('checkbox');
    await fireEvent.click(checkboxes[1]);
    expect(await findByText(/Configure payment accounts/i)).toBeInTheDocument();
    expect(queryByText(/Reimburse selected/)).toBeNull();
  });
});

describe('UserReimbursementPanel — batch form is a modal (2026-10-10)', () => {
  it('Reimburse selected opens the batch modal with the count and total, and submits', async () => {
    const { within, waitFor } = await import('@testing-library/svelte');
    api.post.mockResolvedValue({ id: 10 });
    const { findAllByRole, findByRole, findByText } = render(UserReimbursementPanel, { props: { user: { id: 7 } } });
    const checkboxes = await findAllByRole('checkbox');
    await fireEvent.click(checkboxes[1]);
    await fireEvent.click(await findByText(/Reimburse selected/));
    const dialog = await findByRole('dialog', { name: 'Create reimbursement' });
    expect(dialog).toHaveTextContent(/Reimburse 1 expense/);
    expect(dialog).toHaveTextContent('$12.50');
    await fireEvent.click(within(dialog).getByRole('button', { name: 'Confirm reimbursement' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/api/reimbursements/', expect.objectContaining({ purchased_by: 7, expense_ids: [1] })));
  });
});

describe('UserReimbursementPanel — batch modal reopens clean (review fix)', () => {
  it('a submit error does not survive Cancel → reopen', async () => {
    const { within, waitFor } = await import('@testing-library/svelte');
    api.post.mockRejectedValue({ status: 400, data: { detail: 'Batch failed.' }, message: 'Batch failed.' });
    const { findAllByRole, findByRole, findByText, queryByText } = render(UserReimbursementPanel, { props: { user: { id: 7 } } });
    await fireEvent.click((await findAllByRole('checkbox'))[1]);
    await fireEvent.click(await findByText(/Reimburse selected/));
    const dialog = await findByRole('dialog', { name: 'Create reimbursement' });
    await fireEvent.click(within(dialog).getByRole('button', { name: 'Confirm reimbursement' }));
    await waitFor(() => expect(within(dialog).getByText('Batch failed.')).toBeInTheDocument());
    await fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }));
    await fireEvent.click(await findByText(/Reimburse selected/));
    await findByRole('dialog', { name: 'Create reimbursement' });
    expect(queryByText('Batch failed.')).toBeNull();
  });
});

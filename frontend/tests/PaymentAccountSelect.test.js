// frontend/tests/PaymentAccountSelect.test.js
import { render } from '@testing-library/svelte';
import { vi, test, expect, beforeEach } from 'vitest';
import PaymentAccountSelect from '../src/components/qbo/PaymentAccountSelect.svelte';

vi.mock('../src/lib/paymentAccounts.js', () => ({
  getPaymentAccounts: vi.fn(async () => ([
    { qbo_account_id: '35', display_name: 'Checking', account_type: 'Bank' },
    { qbo_account_id: '42', display_name: 'Visa', account_type: 'Credit Card' },
  ])),
}));

test('renders an option per configured account', async () => {
  const { findAllByRole } = render(PaymentAccountSelect, { props: { value: '' } });
  const opts = await findAllByRole('option');
  // placeholder + 2 accounts
  expect(opts.length).toBe(3);
  expect(opts.map(o => o.textContent)).toEqual(
    expect.arrayContaining(['Checking', 'Visa']));
});

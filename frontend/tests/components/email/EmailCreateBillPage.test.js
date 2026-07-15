// frontend/tests/components/email/EmailCreateBillPage.test.js
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('svelte-spa-router', () => ({ link: () => ({}), push: vi.fn() }));
vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() } }));
vi.mock('@/lib/email.js', () => ({
  emailApi: { senderInfo: vi.fn(), get: vi.fn() },
  resolveSenderToContact: vi.fn(),
}));
vi.mock('@/components/email/SenderResolutionForm.svelte', () => ({
  default: vi.fn().mockReturnValue(null),
}));

import { push } from 'svelte-spa-router';
import { api } from '@/lib/api.js';
import { emailApi, resolveSenderToContact } from '@/lib/email.js';
import EmailCreateBillPage from '@/routes/email/EmailCreateBillPage.svelte';

const SENDER_INFO = {
  sender_name: 'Vendor Bob',
  sender_email: 'bob@vendor.com',
  matching_contacts: [],
  matching_businesses: [],
};

beforeEach(() => {
  vi.mocked(push).mockReset();
  api.get.mockReset();
  emailApi.senderInfo.mockReset();
  emailApi.get.mockReset();
  resolveSenderToContact.mockReset();
});

describe('EmailCreateBillPage PO pre-fill', () => {
  it('appends &po=<id> when the email has a correlated purchase_order', async () => {
    emailApi.senderInfo.mockResolvedValue(SENDER_INFO);
    emailApi.get.mockResolvedValue({ email_record_id: 7, purchase_order: 5, po_number: 'PO-2025-0001' });
    resolveSenderToContact.mockResolvedValue({ contactId: 10, businessId: 3 });

    const { getByRole } = render(EmailCreateBillPage, { props: { params: { id: '7' } } });
    // wait for senderInfo load
    await new Promise((r) => setTimeout(r, 0));
    await new Promise((r) => setTimeout(r, 0));

    const form = getByRole('button', { name: /Continue to Bill/i });
    await fireEvent.click(form);
    // flush async in handleSubmit
    await new Promise((r) => setTimeout(r, 0));
    await new Promise((r) => setTimeout(r, 0));

    expect(push).toHaveBeenCalledOnce();
    const url = vi.mocked(push).mock.calls[0][0];
    expect(url).toMatch(/\/bills\/new/);
    expect(url).toMatch(/[?&]po=5(&|$)/);
  });

  it('does NOT append &po= when the email has no correlated purchase_order', async () => {
    emailApi.senderInfo.mockResolvedValue(SENDER_INFO);
    emailApi.get.mockResolvedValue({ email_record_id: 8, purchase_order: null, po_number: null });
    resolveSenderToContact.mockResolvedValue({ contactId: 10, businessId: 3 });

    const { getByRole } = render(EmailCreateBillPage, { props: { params: { id: '8' } } });
    await new Promise((r) => setTimeout(r, 0));
    await new Promise((r) => setTimeout(r, 0));

    const form = getByRole('button', { name: /Continue to Bill/i });
    await fireEvent.click(form);
    await new Promise((r) => setTimeout(r, 0));
    await new Promise((r) => setTimeout(r, 0));

    expect(push).toHaveBeenCalledOnce();
    const url = vi.mocked(push).mock.calls[0][0];
    expect(url).toMatch(/\/bills\/new/);
    expect(url).not.toMatch(/[?&]po=/);
  });
});

describe('EmailCreateBillPage duplicate contact', () => {
  it('shows the duplicate-contact modal instead of navigating on a 409', async () => {
    emailApi.senderInfo.mockResolvedValue(SENDER_INFO);
    const err = new Error('conflict');
    err.status = 409;
    err.data = {
      code: 'duplicate_email',
      existing_contact: { contact_id: 42, name: 'Bob Vendor', email: 'bob@vendor.com' },
    };
    resolveSenderToContact.mockRejectedValue(err);

    const { getByRole, findByText } = render(EmailCreateBillPage, { props: { params: { id: '7' } } });
    await new Promise((r) => setTimeout(r, 0));
    await new Promise((r) => setTimeout(r, 0));

    const button = getByRole('button', { name: /Continue to Bill/i });
    await fireEvent.click(button);
    await new Promise((r) => setTimeout(r, 0));
    await new Promise((r) => setTimeout(r, 0));

    expect(await findByText(/may already exist/i)).toBeTruthy();
    expect(await findByText('Bob Vendor')).toBeTruthy();
    expect(push).not.toHaveBeenCalled();
  });
});

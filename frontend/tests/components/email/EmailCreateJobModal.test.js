import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';

vi.mock('svelte-spa-router', () => ({ push: vi.fn(), link: () => ({}) }));
vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn() }, errorMessage: (e, f) => e?.message || f }));
vi.mock('@/lib/email.js', () => ({
  emailApi: { senderInfo: vi.fn(), createJob: vi.fn() },
  resolveSenderToContact: vi.fn(),
}));

import { push } from 'svelte-spa-router';
import { emailApi, resolveSenderToContact } from '@/lib/email.js';
import EmailCreateJobModal from '@/components/email/EmailCreateJobModal.svelte';

const MATCHED = { subject: 'Quote please', suggested_body: 'body', matching_contacts: [{ id: 4, name: 'A' }], matching_businesses: [] };

beforeEach(() => {
  push.mockReset();
  emailApi.senderInfo.mockReset(); emailApi.createJob.mockReset(); resolveSenderToContact.mockReset();
});

describe('EmailCreateJobModal', () => {
  it('loads sender info on open and prefills the job name from the subject', async () => {
    emailApi.senderInfo.mockResolvedValue(MATCHED);
    const { findByLabelText } = render(EmailCreateJobModal, { props: { emailRecordId: 1, open: true } });
    expect((await findByLabelText(/Job Name/)).value).toBe('Quote please');
  });

  it('creates the job, closes and navigates', async () => {
    emailApi.senderInfo.mockResolvedValue(MATCHED);
    resolveSenderToContact.mockResolvedValue({ contactId: 4 });
    emailApi.createJob.mockResolvedValue({ job_id: 31 });
    const onClose = vi.fn();
    const { findByRole } = render(EmailCreateJobModal, { props: { emailRecordId: 1, open: true, onClose } });
    await fireEvent.click(await findByRole('button', { name: 'Create Job' }));
    await waitFor(() => expect(emailApi.createJob).toHaveBeenCalledWith(1, expect.objectContaining({ contact: 4, name: 'Quote please' })));
    expect(onClose).toHaveBeenCalled();
    expect(push).toHaveBeenCalledWith('/jobs/31');
  });

  it('duplicate contact → notice sub-state; Go Back returns to the form', async () => {
    emailApi.senderInfo.mockResolvedValue({ subject: 'Q', suggested_body: '', matching_contacts: [], matching_businesses: [], sender_name: 'Ann Lee', sender_email: 'a@b.c' });
    resolveSenderToContact.mockRejectedValue({ status: 409, data: { code: 'duplicate_email', existing_contact: { contact_id: 9, name: 'Ann Lee', email: 'a@b.c' } } });
    const { findByRole, findByText, getByRole, getByLabelText } = render(EmailCreateJobModal, { props: { emailRecordId: 1, open: true } });
    await fireEvent.click(await findByRole('button', { name: 'Create Job' }));
    expect(await findByText('This contact may already exist')).toBeInTheDocument();
    expect(document.querySelectorAll('[role="dialog"]').length).toBe(1);
    await fireEvent.click(getByRole('button', { name: 'Go Back and Edit' }));
    expect(getByLabelText(/Job Name/).value).toBe('Q');
  });

  it('duplicate business → business notice sub-state', async () => {
    emailApi.senderInfo.mockResolvedValue({ subject: 'Q', suggested_body: '', matching_contacts: [], matching_businesses: [], sender_name: 'Ann Lee', sender_email: 'a@b.c', extracted_company: 'Acme' });
    resolveSenderToContact.mockRejectedValue({ status: 409, data: { code: 'duplicate_business_name', existing_business: { business_id: 2, business_name: 'Acme' } } });
    const { findByRole, findByText } = render(EmailCreateJobModal, { props: { emailRecordId: 1, open: true } });
    await fireEvent.click(await findByRole('button', { name: 'Create Job' }));
    expect(await findByText('This business may already exist')).toBeInTheDocument();
  });
});

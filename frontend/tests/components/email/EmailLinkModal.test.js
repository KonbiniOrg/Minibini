import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() }, errorMessage: (e, f) => e?.message || f }));
vi.mock('@/lib/email.js', () => ({ emailApi: { linkToJob: vi.fn(), linkToPo: vi.fn() } }));

import { api } from '@/lib/api.js';
import { emailApi } from '@/lib/email.js';
import EmailLinkModal from '@/components/email/EmailLinkModal.svelte';

beforeEach(() => {
  api.get.mockReset(); api.get.mockResolvedValue({ results: [] });
  emailApi.linkToJob.mockReset(); emailApi.linkToPo.mockReset();
});

describe('EmailLinkModal', () => {
  it('renders the job search input on mount (regression: the picker value must start null, not "")', async () => {
    const { findByPlaceholderText, findByRole } = render(EmailLinkModal, { props: { emailRecordId: 1, kind: 'job', open: true } });
    await findByRole('dialog', { name: 'Link to job' });
    expect(await findByPlaceholderText('Search jobs…')).toBeInTheDocument();
  });

  it('renders the PO search input for kind=po', async () => {
    const { findByPlaceholderText, findByRole } = render(EmailLinkModal, { props: { emailRecordId: 1, kind: 'po', open: true } });
    await findByRole('dialog', { name: 'Link to purchase order' });
    expect(await findByPlaceholderText('Search purchase order…')).toBeInTheDocument();
  });

  it('submit without a selection shows a message and does not call the API', async () => {
    const { findByRole, findByText } = render(EmailLinkModal, { props: { emailRecordId: 1, kind: 'job', open: true } });
    await fireEvent.click(await findByRole('button', { name: 'Link to job' }));
    expect(await findByText('Please select a job.')).toBeInTheDocument();
    expect(emailApi.linkToJob).not.toHaveBeenCalled();
  });
});

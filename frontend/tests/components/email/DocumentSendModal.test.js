import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), postMultipart: vi.fn() },
  errorMessage: (e, fallback) => e?.data?.detail || e?.message || fallback,
}));

import { api } from '@/lib/api.js';
import DocumentSendModal from '@/components/email/DocumentSendModal.svelte';

const PROPS = {
  open: true, label: 'Send estimate', title: 'Send Estimate',
  defaultsUrl: '/api/estimates/7/send-defaults/', sendUrl: '/api/estimates/7/send/',
  submitLabel: 'Send Email',
};

beforeEach(() => {
  api.get.mockReset(); api.postMultipart.mockReset();
  vi.spyOn(window, 'confirm').mockReturnValue(true);
});
afterEach(() => { vi.restoreAllMocks(); });

describe('DocumentSendModal', () => {
  it('loads defaults on open and prefills To', async () => {
    api.get.mockResolvedValue({ to: 'cust@example.com', cc: '', bcc: '', subject: 'S', body: 'B', attachments_preview: [] });
    const { findByDisplayValue, findByRole } = render(DocumentSendModal, { props: PROPS });
    await findByRole('dialog', { name: 'Send estimate' });
    expect(await findByDisplayValue('cust@example.com')).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith('/api/estimates/7/send-defaults/');
  });

  it('posts multipart to sendUrl and calls onSent', async () => {
    api.get.mockResolvedValue({ to: 'c@x.y', attachments_preview: [] });
    api.postMultipart.mockResolvedValue({});
    const onSent = vi.fn();
    const { findByRole } = render(DocumentSendModal, { props: { ...PROPS, onSent } });
    await fireEvent.click(await findByRole('button', { name: 'Send Email' }));
    await waitFor(() => expect(api.postMultipart).toHaveBeenCalledWith('/api/estimates/7/send/', expect.any(FormData)));
    expect(onSent).toHaveBeenCalled();
  });

  it('beforeSubmit false aborts without posting and keeps the modal open', async () => {
    api.get.mockResolvedValue({ to: 'c@x.y', attachments_preview: [] });
    const beforeSubmit = vi.fn().mockResolvedValue(false);
    const { findByRole, getByDisplayValue } = render(DocumentSendModal, { props: { ...PROPS, beforeSubmit } });
    await fireEvent.click(await findByRole('button', { name: 'Send Email' }));
    await waitFor(() => expect(beforeSubmit).toHaveBeenCalled());
    expect(window.confirm).toHaveBeenCalledTimes(1); // the form's own recipient confirm ran first
    expect(api.postMultipart).not.toHaveBeenCalled();
    expect(getByDisplayValue('c@x.y')).toBeInTheDocument();
    expect(await findByRole('button', { name: 'Send Email' })).not.toBeDisabled();
  });

  it('renders the server refusal as a form message and stays open', async () => {
    api.get.mockResolvedValue({ to: 'c@x.y', attachments_preview: [] });
    api.postMultipart.mockRejectedValue({ status: 400, data: { detail: 'Cannot send an empty change order.' }, message: 'Cannot send an empty change order.' });
    const onClose = vi.fn();
    const { findByRole, findByText } = render(DocumentSendModal, { props: { ...PROPS, onClose } });
    await fireEvent.click(await findByRole('button', { name: 'Send Email' }));
    expect(await findByText('Cannot send an empty change order.')).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
  });

  it('Cancel closes', async () => {
    api.get.mockResolvedValue({ to: 'c@x.y', attachments_preview: [] });
    const onClose = vi.fn();
    const { findByRole } = render(DocumentSendModal, { props: { ...PROPS, onClose } });
    await fireEvent.click(await findByRole('button', { name: 'Cancel' }));
    expect(onClose).toHaveBeenCalled();
  });

  it('shows a load error when the defaults fetch fails', async () => {
    api.get.mockRejectedValue({ message: 'boom' });
    const { findByText } = render(DocumentSendModal, { props: PROPS });
    expect(await findByText('boom')).toBeInTheDocument();
  });
});

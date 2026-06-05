import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/email.js', () => ({
  emailApi: { replyDefaults: vi.fn(), reply: vi.fn() },
}));

import { emailApi } from '@/lib/email.js';
import EmailReplyComposer from '@/components/email/EmailReplyComposer.svelte';

beforeEach(() => {
  emailApi.replyDefaults.mockReset();
  emailApi.reply.mockReset();
  emailApi.replyDefaults.mockResolvedValue({ to: 'a@b.com', subject: 'Re: x', body: 'orig' });
  emailApi.reply.mockResolvedValue({});
});

describe('EmailReplyComposer', () => {
  it('loads defaults and pre-fills the To field', async () => {
    const { findByDisplayValue } = render(EmailReplyComposer, {
      props: { emailRecordId: 1, mode: 'reply', onClose: vi.fn(), onSent: vi.fn() },
    });
    expect(await findByDisplayValue('a@b.com')).toBeInTheDocument();
  });

  it('sends the reply as FormData and reports sent', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    const onSent = vi.fn();
    const { findByRole } = render(EmailReplyComposer, {
      props: { emailRecordId: 1, mode: 'reply', onClose: vi.fn(), onSent },
    });
    await fireEvent.click(await findByRole('button', { name: 'Send' }));
    expect(emailApi.reply).toHaveBeenCalledWith(1, expect.any(FormData));
    expect(onSent).toHaveBeenCalled();
    confirmSpy.mockRestore();
  });

  it('closes via onClose', async () => {
    const onClose = vi.fn();
    const { findByRole } = render(EmailReplyComposer, {
      props: { emailRecordId: 1, mode: 'reply', onClose, onSent: vi.fn() },
    });
    await fireEvent.click(await findByRole('button', { name: 'Cancel' }));
    expect(onClose).toHaveBeenCalled();
  });
});

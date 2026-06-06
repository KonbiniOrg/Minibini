import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/email.js', () => ({
  emailApi: { unlinkFromJob: vi.fn(), unlinkFromPo: vi.fn(), unlinkFromBill: vi.fn() },
}));

import { emailApi } from '@/lib/email.js';
import { user } from '@/stores/auth.js';
import EmailActionPanel from '@/components/email/EmailActionPanel.svelte';

beforeEach(() => {
  emailApi.unlinkFromJob.mockReset();
  user.set({ permissions: [] });
});

describe('EmailActionPanel', () => {
  it('always offers reply and reply-all', async () => {
    const onReply = vi.fn();
    const { getByRole } = render(EmailActionPanel, { props: { emailRecord: { email_record_id: 1 }, onReply } });
    await fireEvent.click(getByRole('button', { name: 'Reply' }));
    await fireEvent.click(getByRole('button', { name: 'Reply All' }));
    expect(onReply).toHaveBeenNthCalledWith(1, 'reply');
    expect(onReply).toHaveBeenNthCalledWith(2, 'reply-all');
  });

  it('hides the Job section without the jobs permission', () => {
    const { queryByRole } = render(EmailActionPanel, { props: { emailRecord: { email_record_id: 1 } } });
    expect(queryByRole('heading', { name: 'Job' })).toBeNull();
  });

  it('disassociates a linked job without prompting (re-link is one action away)', async () => {
    user.set({ permissions: ['can_manage_jobs'] });
    const confirmSpy = vi.spyOn(window, 'confirm');
    const onChange = vi.fn();
    const { getByRole } = render(EmailActionPanel, {
      props: { emailRecord: { email_record_id: 1, job: 5, job_number: 'JOB-5' }, onChange },
    });
    await fireEvent.click(getByRole('button', { name: 'Disassociate' }));
    expect(emailApi.unlinkFromJob).toHaveBeenCalledWith(1);
    expect(onChange).toHaveBeenCalled();
    expect(confirmSpy).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });
});

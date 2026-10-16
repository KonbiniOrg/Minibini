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

describe('EmailActionPanel — job/PO actions open modals (2026-10-10)', () => {
  it('Create new / Link existing are buttons that report their action (PO section included)', async () => {
    user.set({ permissions: ['can_manage_jobs', 'can_manage_financials'] });
    const onAction = vi.fn();
    const { getAllByRole, queryByRole } = render(EmailActionPanel, {
      props: { emailRecord: { email_record_id: 1 }, onAction },
    });
    const creates = getAllByRole('button', { name: 'Create new' });
    expect(creates).toHaveLength(2);
    await fireEvent.click(creates[0]);
    await fireEvent.click(creates[1]);
    expect(onAction).toHaveBeenNthCalledWith(1, 'create-job');
    expect(onAction).toHaveBeenNthCalledWith(2, 'create-po');
    expect(queryByRole('link', { name: 'Create new' })).toBeNull();
  });

  it('a jobs-only user sees the PO "Create new" but not "Link existing"', () => {
    user.set({ permissions: ['can_manage_jobs'] });
    const { getByRole, getAllByRole, queryByRole } = render(EmailActionPanel, {
      props: { emailRecord: { email_record_id: 1 }, onAction: vi.fn() },
    });
    expect(getByRole('heading', { name: 'Purchase Order' })).toBeInTheDocument();
    expect(getAllByRole('button', { name: 'Create new' })).toHaveLength(2);
    expect(getAllByRole('button', { name: 'Link existing' })).toHaveLength(1);   // the Job one only
    expect(queryByRole('link', { name: 'Create new' })).toBeNull();
  });
});

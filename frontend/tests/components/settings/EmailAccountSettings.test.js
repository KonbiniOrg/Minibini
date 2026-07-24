import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), patch: vi.fn(), post: vi.fn() } }));
vi.mock('@/stores/setupStatus.js', () => ({ refreshSetupStatus: vi.fn() }));

import { api } from '@/lib/api.js';
import { refreshSetupStatus } from '@/stores/setupStatus.js';
import EmailAccountSettings from '@/components/settings/EmailAccountSettings.svelte';

beforeEach(() => {
  api.get.mockReset(); api.patch.mockReset(); api.post.mockReset();
  api.get.mockResolvedValue({});
  api.patch.mockResolvedValue({});
});

describe('EmailAccountSettings', () => {
  it('pre-fills loaded values but never the password', async () => {
    api.get.mockResolvedValue({
      email_imap_server: 'imap.tenant.com', email_address: 'shop@tenant.com',
      email_password: 'secret', email_smtp_host: 'smtp.tenant.com',
      email_smtp_port: '465',
    });
    const { findByDisplayValue, getByPlaceholderText, queryByDisplayValue } =
      render(EmailAccountSettings);
    expect(await findByDisplayValue('imap.tenant.com')).toBeInTheDocument();
    expect(await findByDisplayValue('shop@tenant.com')).toBeInTheDocument();
    expect(queryByDisplayValue('secret')).toBeNull();
    expect(getByPlaceholderText('(unchanged)')).toBeInTheDocument();
  });

  it('saves without password when left blank', async () => {
    const { getByRole, findByText } = render(EmailAccountSettings);
    await fireEvent.click(getByRole('button', { name: 'Save email account' }));
    expect(api.patch).toHaveBeenCalledWith('/api/settings/', expect.not.objectContaining({
      email_password: expect.anything(),
    }));
    expect(await findByText('Email account saved.')).toBeInTheDocument();
    expect(refreshSetupStatus).toHaveBeenCalled();
  });

  it('renders both verify results', async () => {
    api.post.mockResolvedValue({
      imap: { ok: true, error: '' },
      smtp: { ok: false, error: 'auth refused' },
    });
    const { getByRole, findByText } = render(EmailAccountSettings);
    await fireEvent.click(getByRole('button', { name: 'Verify connection' }));
    expect(api.post).toHaveBeenCalledWith('/api/settings/email-verify/', {});
    expect(await findByText('OK')).toBeInTheDocument();
    expect(await findByText(/auth refused/)).toBeInTheDocument();
  });
});

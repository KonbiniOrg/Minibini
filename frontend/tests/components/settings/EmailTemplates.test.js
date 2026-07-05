import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), patch: vi.fn() },
  errorMessage: (e, fallback) =>
    e?.data?.detail || e?.message || fallback || 'Something went wrong.',
}));

import { api } from '@/lib/api.js';
import EmailTemplates from '@/components/settings/EmailTemplates.svelte';

beforeEach(() => {
  api.get.mockReset();
  api.patch.mockReset();
  api.get.mockResolvedValue({}); // no stored rows → built-in defaults
  api.patch.mockResolvedValue({});
});

describe('EmailTemplates', () => {
  it('pre-fills the built-in default when no row is stored', async () => {
    const { findByDisplayValue } = render(EmailTemplates);
    expect(await findByDisplayValue('Estimate {document_number}')).toBeInTheDocument();
  });

  it('includes a Change Order template block pre-filled with its default', async () => {
    const { findByDisplayValue } = render(EmailTemplates);
    expect(await findByDisplayValue('Change order {document_number}')).toBeInTheDocument();
  });

  it('saves the change order body key', async () => {
    const { findAllByRole } = render(EmailTemplates);
    const saveBodyButtons = await findAllByRole('button', { name: 'Save body' });
    // Order matches TEMPLATES: Estimate, PO, Invoice, Change Order → index 3.
    await fireEvent.click(saveBodyButtons[3]);
    expect(api.patch).toHaveBeenCalledWith('/api/settings/', expect.objectContaining({
      change_order_email_body_template: expect.stringContaining('{object_url}'),
    }));
  });

  it('saves a single template key and flashes saved', async () => {
    const { findAllByRole, findByText } = render(EmailTemplates);
    const saveSubjectButtons = await findAllByRole('button', { name: 'Save subject' });
    await fireEvent.click(saveSubjectButtons[0]); // Estimate subject

    expect(api.patch).toHaveBeenCalledWith('/api/settings/', {
      estimate_email_subject_template: 'Estimate {document_number}',
    });
    expect(await findByText('saved')).toBeInTheDocument();
  });

  it('saves the retention setting', async () => {
    const { findByRole } = render(EmailTemplates);
    const btn = await findByRole('button', { name: 'Save retention' });
    await fireEvent.click(btn);
    expect(api.patch).toHaveBeenCalledWith('/api/settings/', { email_retention_days: '90' });
  });

  it('saves the inbox display limit', async () => {
    const { findByRole } = render(EmailTemplates);
    const btn = await findByRole('button', { name: 'Save display limit' });
    await fireEvent.click(btn);
    expect(api.patch).toHaveBeenCalledWith('/api/settings/', { email_display_limit: '30' });
  });

  it('shows an inline error next to the failed save (field-keyed body)', async () => {
    api.patch.mockRejectedValueOnce(Object.assign(new Error('Request failed'), {
      status: 400, data: { email_retention_days: ['Must be a positive number.'] },
    }));
    const { findByRole } = render(EmailTemplates);
    const btn = await findByRole('button', { name: 'Save retention' });
    await fireEvent.click(btn);
    expect(await findByRole('alert')).toHaveTextContent('Must be a positive number.');
  });

  it('shows an inline error next to the failed save (operation error)', async () => {
    api.patch.mockRejectedValueOnce(Object.assign(new Error('Request failed'), {
      status: 400, data: { detail: 'Settings are read-only.' },
    }));
    const { findByRole } = render(EmailTemplates);
    const btn = await findByRole('button', { name: 'Save retention' });
    await fireEvent.click(btn);
    expect(await findByRole('alert')).toHaveTextContent('Settings are read-only.');
  });
});

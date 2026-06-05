import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), patch: vi.fn() } }));

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
});

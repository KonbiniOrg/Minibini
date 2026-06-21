// Regression test for Fix 1: selectedJobId initialised as $state(null), not $state('').
// SearchPicker treats '' != null as a real value → tries to resolve a label → fetches
// /api/jobs// (404) → leaves the component stuck in the empty-selected state (a lone
// "Clear" button, NO search input) on mount.
// This test asserts the search input is present after the email loads.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from '@testing-library/svelte';

vi.mock('svelte-spa-router', () => ({ link: () => ({}), push: vi.fn() }));
vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));
vi.mock('@/lib/email.js', () => ({
  emailApi: { get: vi.fn() },
}));

import { emailApi } from '@/lib/email.js';
import EmailAssociatePage from '@/routes/email/EmailAssociatePage.svelte';

beforeEach(() => {
  emailApi.get.mockReset();
});

describe('EmailAssociatePage', () => {
  it('renders the job search input on mount (not stuck in empty-selected state)', async () => {
    emailApi.get.mockResolvedValue({
      email_record_id: 1,
      temp_email: { from_email: 'sender@example.com', subject: 'Test subject' },
    });

    const { findByPlaceholderText } = render(EmailAssociatePage, {
      props: { params: { id: '1' } },
    });

    // After the email load resolves, the form renders with the picker's search input.
    // If selectedJobId were '' instead of null, SearchPicker would show only a "Clear"
    // button and the input would be absent.
    const input = await findByPlaceholderText(/search jobs/i);
    expect(input).toBeInTheDocument();
  });
});

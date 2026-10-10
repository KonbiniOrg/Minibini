import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from '@testing-library/svelte';

vi.mock('svelte-spa-router', () => ({ link: () => ({}), push: vi.fn() }));
vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() }, errorMessage: (e, fallback) => e?.message || fallback }));
vi.mock('@/lib/email.js', () => ({ emailApi: { get: vi.fn() } }));

import { emailApi } from '@/lib/email.js';
import EmailAssociatePOPage from '@/routes/email/EmailAssociatePOPage.svelte';

const dts = (c) => Array.from(c.querySelectorAll('dl dt')).map((dt) => dt.textContent.trim());

beforeEach(() => emailApi.get.mockReset());

describe('EmailAssociatePOPage — email summary as a definition list', () => {
  it('renders From / Subject as dt/dd pairs', async () => {
    emailApi.get.mockResolvedValue({ email_record_id: 1, temp_email: { from_email: 'vendor@example.com', subject: 'Invoice 42' } });
    const { findByText, container } = render(EmailAssociatePOPage, { props: { params: { id: '1' } } });
    await findByText('Invoice 42');
    expect(dts(container)).toEqual(['From', 'Subject']);
    expect(container.querySelector('table')).toBeNull();
  });
});

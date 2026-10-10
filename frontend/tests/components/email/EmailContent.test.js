import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import EmailContent from '@/components/email/EmailContent.svelte';

const dts = (c) => Array.from(c.querySelectorAll('dl dt')).map((dt) => dt.textContent.trim());
const emailRecord = { email_record_id: 1 };

describe('EmailContent — header fields as a definition list', () => {
  it('renders From / To / Date / Subject (and CC when present) as dt/dd pairs from full content', () => {
    const content = { from: 'a@x.com', to: 'b@x.com', cc: ['c@x.com'], date: '2026-07-11T08:01:00Z', subject: 'Hello', body: '' };
    const { container } = render(EmailContent, { props: { content, emailRecord } });
    expect(dts(container)).toEqual(['From', 'To', 'CC', 'Date', 'Subject']);
    const dds = Array.from(container.querySelectorAll('dl dd')).map((dd) => dd.textContent.trim());
    expect(dds[0]).toBe('a@x.com');
    expect(dds[4]).toBe('Hello');
    expect(container.querySelector('table')).toBeNull();
  });

  it('omits CC when absent and falls back to the cached metadata without full content', () => {
    const tempEmail = { from_email: 'a@x.com', to_email: 'b@x.com', cc_email: '', date_sent: '2026-07-11T08:01:00Z', subject: 'Cached' };
    const { container, getByText } = render(EmailContent, { props: { tempEmail, emailRecord } });
    expect(dts(container)).toEqual(['From', 'To', 'Date', 'Subject']);
    expect(getByText('Cached')).toBeInTheDocument();
  });
});

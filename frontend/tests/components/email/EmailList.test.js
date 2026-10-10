import { describe, it, expect, beforeEach } from 'vitest';
import { render } from '@testing-library/svelte';
import { viewMode } from '@/stores/viewMode.js';
import EmailList from '@/components/email/EmailList.svelte';

const emails = [
  { email_record_id: 11, job: 7, job_number: 'JOB-7',
    temp_email: { date_sent: '2026-07-11T08:01:00Z', from_email: 'a@x.com', subject: 'Quote request', has_attachments: true } },
  { email_record_id: 12, job: null,
    temp_email: { date_sent: null, from_email: '', subject: '', has_attachments: false } },
];
const headersOf = (t) => Array.from(t.querySelectorAll('thead th')).map((th) => th.textContent.trim());
const ALL = ['Date', 'From', 'Subject', 'Job', 'Attachments'];

beforeEach(() => viewMode.set('lite'));

describe('EmailList — DataTable', () => {
  it('renders the same five columns in both densities with data-col', () => {
    const { container } = render(EmailList, { props: { emails } });
    const table = container.querySelector('table.data-table');
    expect(headersOf(table)).toEqual(ALL);
    const rows = table.querySelectorAll('tbody tr');
    expect(rows[0].querySelector('td[data-col="subject"] a')).toHaveAttribute('href', '#/email/11');
    expect(rows[0].querySelector('td[data-col="job"] a')).toHaveAttribute('href', '#/jobs/7');
    expect(rows[0].querySelector('td[data-col="attachments"]').textContent.trim()).toBe('Yes');
    expect(rows[1].querySelector('td[data-col="subject"] a').textContent.trim()).toBe('(no subject)');
    expect(rows[1].querySelector('td[data-col="job"]').textContent.trim()).toBe('None');
    viewMode.set('full');
    const { container: c2 } = render(EmailList, { props: { emails } });
    expect(headersOf(c2.querySelector('table.data-table'))).toEqual(ALL);
  });

  it('shows "No emails found." for an empty list', () => {
    const { getByText } = render(EmailList, { props: { emails: [] } });
    expect(getByText('No emails found.')).toBeInTheDocument();
  });
});

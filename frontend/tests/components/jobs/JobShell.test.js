import { describe, it, expect, vi } from 'vitest';
import { render } from '@testing-library/svelte';
import { createRawSnippet } from 'svelte';
vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn().mockResolvedValue({ results: [] }) },
  errorMessage: (e, f) => f }));
import JobShell from '@/components/jobs/JobShell.svelte';

const job = { job_id: 3, job_number: 'JOB-3', name: 'Widget', status: 'in_progress', description: 'D' };
const body = createRawSnippet(() => ({ render: () => '<p>PANEL BODY</p>' }));

describe('JobShell', () => {
  it('stacks header, rail, band, and the hosted panel', () => {
    const { getByText, container } = render(JobShell, { props: { job, current: 'shipments', children: body } });
    expect(getByText(/JOB #3/)).toBeInTheDocument();
    expect(container.querySelector('.job-nav-rail')).toBeInTheDocument();
    expect(container.querySelector('.context-band')).toBeInTheDocument();
    expect(getByText('PANEL BODY')).toBeInTheDocument();
  });

  it('showBand={false} omits the context band (overview keeps its midband)', () => {
    const { container } = render(JobShell, { props: { job, showBand: false, children: body } });
    expect(container.querySelector('.context-band')).toBeNull();
  });
});

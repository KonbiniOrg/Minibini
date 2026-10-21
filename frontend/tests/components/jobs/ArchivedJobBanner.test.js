import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import ArchivedJobBanner from '@/components/jobs/ArchivedJobBanner.svelte';

describe('ArchivedJobBanner', () => {
  it('states the job is a read-only historical import', () => {
    const { getByRole } = render(ArchivedJobBanner);
    const banner = getByRole('status');
    expect(banner.textContent).toContain('Archived:');
    expect(banner.textContent).toContain('this job was imported as a historical record and cannot be changed.');
  });
});

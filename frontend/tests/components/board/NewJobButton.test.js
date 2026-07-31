import { describe, it, expect, beforeEach } from 'vitest';
import { render } from '@testing-library/svelte';

import { user } from '@/stores/auth.js';
import NewJobButton from '@/components/board/NewJobButton.svelte';

beforeEach(() => {
  user.set({ username: 'rachel', permissions: ['can_manage_jobs'] });
});

describe('NewJobButton', () => {
  it('links to the create form', () => {
    const { getByRole } = render(NewJobButton);
    expect(getByRole('link', { name: 'New Job' })).toHaveAttribute('href', '#/jobs/new');
  });

  it('renders nothing without can_manage_jobs', () => {
    user.set({ username: 'sam', permissions: [] });
    const { queryByRole } = render(NewJobButton);
    expect(queryByRole('link', { name: 'New Job' })).toBeNull();
  });
});

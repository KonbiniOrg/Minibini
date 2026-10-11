import { describe, it, expect, beforeEach } from 'vitest';
import { render, waitFor } from '@testing-library/svelte';
import RedirectTo from '@/routes/RedirectTo.svelte';

beforeEach(() => { window.location.hash = '#/somewhere'; });

describe('RedirectTo', () => {
  it('replaces the hash with the target, substituting :params', async () => {
    render(RedirectTo, { props: { params: { id: '42' }, to: '/contacts/:id' } });
    await waitFor(() => expect(window.location.hash).toBe('#/contacts/42'));
  });

  it('works with no params', async () => {
    render(RedirectTo, { props: { to: '/contacts' } });
    await waitFor(() => expect(window.location.hash).toBe('#/contacts'));
  });
});

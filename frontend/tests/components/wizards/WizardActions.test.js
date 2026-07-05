import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { delete: vi.fn() },
  errorMessage: (e, fallback) =>
    e?.data?.detail || e?.message || fallback || 'Something went wrong.',
}));
vi.mock('svelte-spa-router', () => ({ push: vi.fn() }));

import { get } from 'svelte/store';
import { api } from '@/lib/api.js';
import { push } from 'svelte-spa-router';
import { overlayMessage, clearMessage } from '@/stores/messages.js';
import WizardActions from '@/components/wizards/WizardActions.svelte';

const PROPS = { apiBase: '/api/invoices/123', detailRoute: '/invoices/123' };

beforeEach(() => {
  api.delete.mockReset();
  push.mockReset();
  clearMessage();
});

describe('WizardActions', () => {
  it('navigates to the detail route on Done', async () => {
    const { getByRole } = render(WizardActions, { props: PROPS });
    await fireEvent.click(getByRole('button', { name: 'Done' }));
    await waitFor(() => expect(push).toHaveBeenCalledWith('/invoices/123'));
  });

  it('flushes pending edits (onDone) before navigating', async () => {
    const onDone = vi.fn().mockResolvedValue(undefined);
    const { getByRole } = render(WizardActions, { props: { ...PROPS, onDone } });
    await fireEvent.click(getByRole('button', { name: 'Done' }));
    await waitFor(() => expect(push).toHaveBeenCalledWith('/invoices/123'));
    expect(onDone).toHaveBeenCalled();
  });

  it('stays on the wizard and raises the overlay when a flush save fails', async () => {
    const onDone = vi.fn().mockRejectedValue(new Error('save failed'));
    const { getByRole } = render(WizardActions, { props: { ...PROPS, onDone } });
    await fireEvent.click(getByRole('button', { name: 'Done' }));
    await waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(push).not.toHaveBeenCalled();
    expect(get(overlayMessage)).toEqual({ kind: 'error', text: 'save failed' });
  });

  it('raises the overlay (no navigation) when discard fails', async () => {
    const err = Object.assign(new Error('Request failed'), {
      status: 400, data: { detail: 'Cannot discard.' },
    });
    api.delete.mockRejectedValue(err);
    const { getByRole } = render(WizardActions, { props: PROPS });
    await fireEvent.click(getByRole('button', { name: 'Discard draft' }));
    await waitFor(() =>
      expect(get(overlayMessage)).toEqual({ kind: 'error', text: 'Cannot discard.' }));
    expect(push).not.toHaveBeenCalled();
  });

  it('discards and returns home without prompting (draft is easily remade)', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm');
    api.delete.mockResolvedValue({});
    const { getByRole } = render(WizardActions, { props: PROPS });

    await fireEvent.click(getByRole('button', { name: 'Discard draft' }));

    expect(api.delete).toHaveBeenCalledWith('/api/invoices/123/?confirm=true');
    expect(push).toHaveBeenCalledWith('/');
    expect(confirmSpy).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });

  it('discards to a provided discardRoute when given', async () => {
    api.delete.mockResolvedValue({});
    const { getByRole } = render(WizardActions, {
      props: { ...PROPS, discardRoute: '/jobs/77' },
    });

    await fireEvent.click(getByRole('button', { name: 'Discard draft' }));

    expect(api.delete).toHaveBeenCalledWith('/api/invoices/123/?confirm=true');
    expect(push).toHaveBeenCalledWith('/jobs/77');
  });
});

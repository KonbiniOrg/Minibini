import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { delete: vi.fn() } }));
vi.mock('svelte-spa-router', () => ({ push: vi.fn() }));

import { api } from '@/lib/api.js';
import { push } from 'svelte-spa-router';
import WizardActions from '@/components/wizards/WizardActions.svelte';

const PROPS = { apiBase: '/api/invoices/123', detailRoute: '/invoices/123' };

beforeEach(() => {
  api.delete.mockReset();
  push.mockReset();
});

describe('WizardActions', () => {
  it('navigates to the detail route on Done', async () => {
    const { getByRole } = render(WizardActions, { props: PROPS });
    await fireEvent.click(getByRole('button', { name: 'Done' }));
    expect(push).toHaveBeenCalledWith('/invoices/123');
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
});

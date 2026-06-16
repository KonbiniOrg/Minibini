import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), patch: vi.fn() } }));

import { api } from '@/lib/api.js';
import MaterialMarkupSetting from '@/components/settings/MaterialMarkupSetting.svelte';

beforeEach(() => {
  api.get.mockReset();
  api.patch.mockReset();
  api.get.mockResolvedValue({ default_material_markup_percent: '25' });
  api.patch.mockResolvedValue({});
});

describe('MaterialMarkupSetting', () => {
  it('loads the current markup value', async () => {
    const { findByLabelText } = render(MaterialMarkupSetting);
    const input = await findByLabelText(/Default markup/);
    await vi.waitFor(() => expect(input.value).toBe('25'));
  });

  it('saves the markup via PATCH /api/settings/', async () => {
    const { findByLabelText, getByRole, findByText } = render(MaterialMarkupSetting);
    const input = await findByLabelText(/Default markup/);
    await vi.waitFor(() => expect(input.value).toBe('25'));
    await fireEvent.input(input, { target: { value: '40' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    await vi.waitFor(() => expect(api.patch).toHaveBeenCalledWith(
      '/api/settings/', { default_material_markup_percent: '40' }));
    await findByText('Markup saved.');
  });

  it('rejects a negative markup without calling the API', async () => {
    const { findByLabelText, getByRole, findByText } = render(MaterialMarkupSetting);
    const input = await findByLabelText(/Default markup/);
    await vi.waitFor(() => expect(input.value).toBe('25'));
    await fireEvent.input(input, { target: { value: '-5' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    await findByText(/non-negative/);
    expect(api.patch).not.toHaveBeenCalled();
  });

  it('defaults to 0 when the config is unset', async () => {
    api.get.mockResolvedValue({});
    const { findByLabelText } = render(MaterialMarkupSetting);
    const input = await findByLabelText(/Default markup/);
    await vi.waitFor(() => expect(input.value).toBe('0'));
  });
});

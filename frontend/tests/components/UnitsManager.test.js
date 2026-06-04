import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), patch: vi.fn() } }));

import { api } from '@/lib/api.js';
import UnitsManager from '@/components/UnitsManager.svelte';

beforeEach(() => {
  api.get.mockReset();
  api.patch.mockReset();
  api.get.mockResolvedValue(['none', 'kg', 'lb']);
  // saveUnits sets units = await api.patch(...); echo the saved list back.
  api.patch.mockImplementation((_url, body) => Promise.resolve(body));
});

describe('UnitsManager', () => {
  it('loads and renders the units', async () => {
    const { findByText } = render(UnitsManager);
    expect(await findByText('kg')).toBeInTheDocument();
  });

  it('adds a new unit and saves', async () => {
    const { findByText, getByPlaceholderText, getByRole } = render(UnitsManager);
    await findByText('kg');

    await fireEvent.input(getByPlaceholderText('New unit name'), { target: { value: 'box' } });
    await fireEvent.click(getByRole('button', { name: 'Add' }));

    expect(api.patch).toHaveBeenCalledWith('/api/settings/units/', ['none', 'kg', 'lb', 'box']);
  });

  it('rejects a duplicate without saving', async () => {
    const { findByText, getByPlaceholderText, getByRole, getByText } = render(UnitsManager);
    await findByText('kg');

    await fireEvent.input(getByPlaceholderText('New unit name'), { target: { value: 'kg' } });
    await fireEvent.click(getByRole('button', { name: 'Add' }));

    expect(getByText(/already exists/)).toBeInTheDocument();
    expect(api.patch).not.toHaveBeenCalled();
  });

  it('removes a unit and saves the survivors', async () => {
    const { findByText, getAllByRole } = render(UnitsManager);
    await findByText('kg');

    // Remove buttons exist for kg and lb only (not 'none').
    const removeButtons = getAllByRole('button', { name: 'Remove' });
    expect(removeButtons).toHaveLength(2);

    await fireEvent.click(removeButtons[0]); // kg
    expect(api.patch).toHaveBeenCalledWith('/api/settings/units/', ['none', 'lb']);
  });

  it('reorders a unit upward and saves', async () => {
    const { findByText, getByRole } = render(UnitsManager);
    await findByText('kg');

    // Only lb (index 2) shows an up-arrow (kg at index 1 cannot move above 'none').
    await fireEvent.click(getByRole('button', { name: '↑' }));
    expect(api.patch).toHaveBeenCalledWith('/api/settings/units/', ['none', 'lb', 'kg']);
  });
});

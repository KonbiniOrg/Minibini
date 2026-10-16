import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), patch: vi.fn() }, errorMessage: (e, fallback) => e?.message || fallback }));

import { api } from '@/lib/api.js';
import UnitsManager from '@/components/UnitsManager.svelte';
import { viewMode } from '@/stores/viewMode.js';

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

  it('offers no Remove button for none or hour', async () => {
    api.get.mockResolvedValue(['none', 'ea', 'hour']);
    const { findByText, getAllByRole } = render(UnitsManager);
    await findByText('ea');

    // Remove button exists for 'ea' only (not 'none' or 'hour').
    const removeButtons = getAllByRole('button', { name: 'Remove' });
    expect(removeButtons).toHaveLength(1);
  });
});

describe('UnitsManager — DataTable', () => {
  const headersOf = (t) => Array.from(t.querySelectorAll('thead th')).map((th) => th.textContent.trim());
  it('renders Unit / Order / (remove) in both densities with data-col and keeps special units undeletable', async () => {
    viewMode.set('lite');
    const { findByText, container } = render(UnitsManager);
    await findByText('kg');
    const table = container.querySelector('table.data-table');
    expect(headersOf(table)).toEqual(['Unit', 'Order', '']);
    const removeCells = table.querySelectorAll('td[data-col="remove"]');
    expect(removeCells[0].querySelector('button')).toBeNull(); // 'none' is special
    expect(removeCells[1].querySelector('button').textContent).toBe('Remove');
    viewMode.set('full');
    const { findByText: f2, container: c2 } = render(UnitsManager);
    await f2('kg');
    expect(headersOf(c2.querySelector('table.data-table'))).toEqual(['Unit', 'Order', '']);
  });
});

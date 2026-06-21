import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import SearchPicker from '@/components/SearchPicker.svelte';

beforeEach(() => { vi.useRealTimers(); });

describe('SearchPicker', () => {
  it('debounces, searches, and picks a row', async () => {
    const search = vi.fn().mockResolvedValue([{ id: 1, name: 'Acme' }]);
    const onPick = vi.fn();
    const { getByPlaceholderText, findByRole } = render(SearchPicker, {
      props: {
        search,
        resolveLabel: vi.fn().mockResolvedValue(null),
        rowLabel: (r) => r.name,
        onPick,
        placeholder: 'Search…',
      },
    });
    await fireEvent.input(getByPlaceholderText('Search…'), { target: { value: 'ac' } });
    await new Promise((r) => setTimeout(r, 300));
    expect(search).toHaveBeenCalledWith('ac');
    await fireEvent.click(await findByRole('button', { name: 'Acme' }));
    expect(onPick).toHaveBeenCalledWith({ id: 1, name: 'Acme' });
  });

  it('does not search a blank query', async () => {
    const search = vi.fn();
    const { getByPlaceholderText } = render(SearchPicker, {
      props: { search, resolveLabel: vi.fn(), placeholder: 'Search…' },
    });
    await fireEvent.input(getByPlaceholderText('Search…'), { target: { value: '  ' } });
    await new Promise((r) => setTimeout(r, 300));
    expect(search).not.toHaveBeenCalled();
  });

  it('resolves a label for a prefilled value', async () => {
    const resolveLabel = vi.fn().mockResolvedValue('Prefilled Co');
    const { findByText } = render(SearchPicker, {
      props: { value: 42, search: vi.fn(), resolveLabel, rowLabel: (r) => r.name },
    });
    expect(await findByText('Prefilled Co')).toBeInTheDocument();
    expect(resolveLabel).toHaveBeenCalledWith(42, null);
  });

  it('clears the selection', async () => {
    const onClear = vi.fn();
    const { getByRole, findByText } = render(SearchPicker, {
      props: {
        value: 42, search: vi.fn(),
        resolveLabel: vi.fn().mockResolvedValue('Prefilled Co'),
        rowLabel: (r) => r.name, onClear,
      },
    });
    await findByText('Prefilled Co');
    await fireEvent.click(getByRole('button', { name: 'Clear' }));
    expect(onClear).toHaveBeenCalled();
  });
});

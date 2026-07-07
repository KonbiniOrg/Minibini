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
    await fireEvent.mouseDown(await findByRole('button', { name: 'Acme' }));
    expect(onPick).toHaveBeenCalledWith({ id: 1, name: 'Acme' });
  });

  it('arrow keys walk the results and Enter picks the highlighted row', async () => {
    const rows = [{ id: 1, name: 'Acme' }, { id: 2, name: 'Bolt Co' }, { id: 3, name: 'Crate' }];
    const onPick = vi.fn();
    const { getByPlaceholderText, findByRole, container } = render(SearchPicker, {
      props: {
        search: vi.fn().mockResolvedValue(rows),
        resolveLabel: vi.fn().mockResolvedValue(null),
        rowLabel: (r) => r.name, onPick, placeholder: 'Search…',
      },
    });
    const input = getByPlaceholderText('Search…');
    await fireEvent.input(input, { target: { value: 'c' } });
    await new Promise((r) => setTimeout(r, 300));
    await findByRole('button', { name: 'Acme' });
    await fireEvent.keyDown(input, { key: 'ArrowDown' });
    await fireEvent.keyDown(input, { key: 'ArrowDown' });
    expect(container.querySelector('.sp-highlighted').textContent).toContain('Bolt Co');
    await fireEvent.keyDown(input, { key: 'ArrowUp' });
    expect(container.querySelector('.sp-highlighted').textContent).toContain('Acme');
    await fireEvent.keyDown(input, { key: 'Enter' });
    expect(onPick).toHaveBeenCalledWith(rows[0]);
  });

  it('Enter without a highlight does not pick (form keeps its meaning)', async () => {
    const onPick = vi.fn();
    const { getByPlaceholderText, findByRole } = render(SearchPicker, {
      props: {
        search: vi.fn().mockResolvedValue([{ id: 1, name: 'Acme' }]),
        resolveLabel: vi.fn().mockResolvedValue(null),
        rowLabel: (r) => r.name, onPick, placeholder: 'Search…',
      },
    });
    const input = getByPlaceholderText('Search…');
    await fireEvent.input(input, { target: { value: 'a' } });
    await new Promise((r) => setTimeout(r, 300));
    await findByRole('button', { name: 'Acme' });
    await fireEvent.keyDown(input, { key: 'Enter' });
    expect(onPick).not.toHaveBeenCalled();
  });

  it('first Escape closes only the dropdown and does not reach the window', async () => {
    const windowEsc = vi.fn();
    window.addEventListener('keydown', windowEsc);
    const { getByPlaceholderText, findByRole, queryByRole } = render(SearchPicker, {
      props: {
        search: vi.fn().mockResolvedValue([{ id: 1, name: 'Acme' }]),
        resolveLabel: vi.fn().mockResolvedValue(null),
        rowLabel: (r) => r.name, placeholder: 'Search…',
      },
    });
    const input = getByPlaceholderText('Search…');
    await fireEvent.input(input, { target: { value: 'a' } });
    await new Promise((r) => setTimeout(r, 300));
    await findByRole('button', { name: 'Acme' });
    await fireEvent.keyDown(input, { key: 'Escape' });
    expect(queryByRole('button', { name: 'Acme' })).toBeNull();  // dropdown closed
    expect(windowEsc).not.toHaveBeenCalled();                    // modal untouched
    window.removeEventListener('keydown', windowEsc);
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

  it('shows "showing N of M" hint when total exceeds results', async () => {
    const search = vi.fn().mockResolvedValue({ rows: [{ id: 1, name: 'A' }, { id: 2, name: 'B' }], total: 16 });
    const { getByPlaceholderText, findByText } = render(SearchPicker, {
      props: {
        search,
        resolveLabel: vi.fn().mockResolvedValue(null),
        rowLabel: (r) => r.name,
        placeholder: 'Search…',
      },
    });
    await fireEvent.input(getByPlaceholderText('Search…'), { target: { value: 'a' } });
    await new Promise((r) => setTimeout(r, 300));
    expect(await findByText(/showing 2 of 16/i)).toBeInTheDocument();
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

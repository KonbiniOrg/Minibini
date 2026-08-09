import { describe, it, expect, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import AtomChildRow from '@/components/docsurface/AtomChildRow.svelte';

const baseAtom = {
  kind: 'task',
  description: 'Sanding',
  qty_display: '2 hr',
  rate: 25,
  amount: 50,
};

function renderRow(props = {}) {
  return render(AtomChildRow, { props: { atom: baseAtom, ...props } });
}

describe('AtomChildRow', () => {
  it('renders a doc-atom-row tr with kind tag, description, qty/rate/amount', () => {
    const { container, getByText } = renderRow();
    expect(container.querySelector('tr.doc-atom-row')).not.toBeNull();
    getByText(/task/);
    getByText('Sanding');
    getByText('2 hr');
    getByText('$25.00');
    getByText('$50.00');
  });

  it('renders a mat kind tag for materials', () => {
    const { getByText } = renderRow({ atom: { ...baseAtom, kind: 'mat', description: 'Acrylic sheet' } });
    getByText(/mat/);
    getByText('Acrylic sheet');
  });

  it('renders colspanBefore empty leading cells ahead of the description', () => {
    const { container } = renderRow({ colspanBefore: 2 });
    const tds = container.querySelectorAll('tr.doc-atom-row td');
    expect(tds[0].textContent.trim()).toBe('');
    expect(tds[1].textContent.trim()).toBe('');
    expect(tds[2].textContent).toContain('Sanding');
  });

  it('renders no leading cells when colspanBefore is 0 (default)', () => {
    const { container } = renderRow();
    const tds = container.querySelectorAll('tr.doc-atom-row td');
    expect(tds[0].textContent).toContain('Sanding');
  });

  it('shows the note in small text when provided', () => {
    const { getByText } = renderRow({ note: 'inherited from line 1' });
    getByText(/inherited from line 1/);
  });

  it('renders no note text when note is empty (default)', () => {
    const { container } = renderRow();
    expect(container.textContent).not.toContain('inherited');
  });

  it('never renders a remove button when onRemove is not wired (A3)', () => {
    const { container } = renderRow();
    expect(container.querySelector('button')).toBeNull();
  });

  it('renders a Remove button that calls onRemove when wired', async () => {
    const onRemove = vi.fn();
    const { getByText } = renderRow({ onRemove });
    await fireEvent.click(getByText('Remove'));
    expect(onRemove).toHaveBeenCalledTimes(1);
  });
});

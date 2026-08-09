import { describe, it, expect, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import DocCustomerView from '@/components/docsurface/DocCustomerView.svelte';
import DocReorderView from '@/components/docsurface/DocReorderView.svelte';

const lines = [
  { line_id: 1, line_number: 1, description: 'Sanding', qty_display: '2 hr', price: 25, amount: 50 },
  { line_id: 2, line_number: 2, description: 'Acrylic sheet', qty_display: '3 ea', price: 10, amount: 30 },
  { line_id: 3, line_number: 3, description: 'Finishing', qty_display: '1 hr', price: 40, amount: 40 },
];

describe('DocCustomerView', () => {
  it('renders title, one row per line, and a grand total row', () => {
    const { getByText, container } = render(DocCustomerView, {
      props: { title: 'Estimate #123', lines, grandTotal: 120 },
    });
    getByText('Estimate #123');
    getByText('Sanding');
    getByText('2 hr');
    getByText('$25.00');
    getByText('$50.00');
    getByText('Acrylic sheet');
    getByText('Finishing');

    const grandRow = container.querySelector('tr.grand');
    expect(grandRow).not.toBeNull();
    expect(grandRow.textContent).toContain('$120.00');

    const table = container.querySelector('table.data-table');
    expect(table).not.toBeNull();
    expect(table.textContent).toContain('#');
    expect(table.textContent).toContain('Description');
    expect(table.textContent).toContain('Qty');
    expect(table.textContent).toContain('Price');
    expect(table.textContent).toContain('Amount');
  });

  it('renders no buttons at all', () => {
    const { container } = render(DocCustomerView, {
      props: { title: 'Estimate #123', lines, grandTotal: 120 },
    });
    expect(container.querySelectorAll('button').length).toBe(0);
  });

  it('renders no line rows when lines is empty (default)', () => {
    const { container } = render(DocCustomerView, { props: { title: 'Empty', grandTotal: 0 } });
    expect(container.querySelectorAll('tbody tr').length).toBe(0);
  });
});

describe('DocReorderView', () => {
  it('fires onReorder(line_id, "down") when a down arrow is clicked', async () => {
    const onReorder = vi.fn();
    const { getAllByText } = render(DocReorderView, {
      props: { title: 'Estimate #123', lines, grandTotal: 120, onReorder },
    });
    const downButtons = getAllByText('▼');
    await fireEvent.click(downButtons[0]);
    expect(onReorder).toHaveBeenCalledWith(1, 'down');
  });

  it('fires onReorder(line_id, "up") when an up arrow is clicked', async () => {
    const onReorder = vi.fn();
    const { getAllByText } = render(DocReorderView, {
      props: { title: 'Estimate #123', lines, grandTotal: 120, onReorder },
    });
    const upButtons = getAllByText('▲');
    await fireEvent.click(upButtons[1]);
    expect(onReorder).toHaveBeenCalledWith(2, 'up');
  });

  it('disables the first row\'s up arrow and the last row\'s down arrow', () => {
    const onReorder = vi.fn();
    const { getAllByText } = render(DocReorderView, {
      props: { title: 'Estimate #123', lines, grandTotal: 120, onReorder },
    });
    const upButtons = getAllByText('▲');
    const downButtons = getAllByText('▼');
    expect(upButtons[0].disabled).toBe(true);
    expect(downButtons[downButtons.length - 1].disabled).toBe(true);
    // middle/other arrows stay enabled
    expect(upButtons[1].disabled).toBe(false);
    expect(downButtons[0].disabled).toBe(false);
  });

  it('renders the same per-row cell text as DocCustomerView for identical input', () => {
    const customer = render(DocCustomerView, { props: { title: 'Doc', lines, grandTotal: 120 } });
    const reorder = render(DocReorderView, {
      props: { title: 'Doc', lines, grandTotal: 120, onReorder: vi.fn() },
    });

    const customerRows = customer.container.querySelectorAll('tbody tr');
    const reorderRows = reorder.container.querySelectorAll('tbody tr');
    expect(reorderRows.length).toBe(customerRows.length);

    customerRows.forEach((cRow, i) => {
      const rRow = reorderRows[i];
      const cCells = Array.from(cRow.querySelectorAll('td')).map((td) => td.textContent.trim());
      // Reorder view has one trailing arrows <td> beyond the shared cells.
      const rCells = Array.from(rRow.querySelectorAll('td'))
        .slice(0, cCells.length)
        .map((td) => td.textContent.trim());
      expect(rCells).toEqual(cCells);
    });
  });
});

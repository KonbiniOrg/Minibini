import { describe, it, expect, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import ReceiveItemsForm from '@/components/purchaseorders/ReceiveItemsForm.svelte';

function line(overrides) {
  return {
    line_item_id: 1, line_number: 1, description: 'Bolt',
    qty: 10, qty_received: 3, qty_cancelled: 0, ...overrides,
  };
}

describe('ReceiveItemsForm', () => {
  it('shows the all-received message when nothing is receivable', () => {
    const { getByText } = render(ReceiveItemsForm, {
      props: { lineItems: [line({ qty_received: 10 })], onSubmit: vi.fn(), onCancel: vi.fn() },
    });
    expect(getByText('All items have been received.')).toBeInTheDocument();
  });

  it('pre-fills the remaining quantity and submits it', async () => {
    const onSubmit = vi.fn();
    const { getByRole } = render(ReceiveItemsForm, {
      props: { lineItems: [line()], onSubmit, onCancel: vi.fn() },
    });
    // remaining = qty(10) - qty_received(3) = 7, pre-filled
    expect(getByRole('spinbutton').value).toBe('7');

    await fireEvent.click(getByRole('button', { name: 'Record Receipt' }));
    expect(onSubmit).toHaveBeenCalledWith([
      { line_item_id: 1, qty_received: 7, note: undefined },
    ]);
  });

  it('pre-fills remaining net of cancelled quantity', async () => {
    const onSubmit = vi.fn();
    const { getByRole, container } = render(ReceiveItemsForm, {
      props: { lineItems: [line({ qty_cancelled: 2 })], onSubmit, onCancel: vi.fn() },
    });
    // remaining = qty(10) - qty_received(3) - qty_cancelled(2) = 5
    expect(getByRole('spinbutton').value).toBe('5');
    // Remaining column (5th cell) shows the cancelled-adjusted value too
    const cells = container.querySelectorAll('tbody td');
    expect(cells[4].textContent.trim()).toBe('5');

    await fireEvent.click(getByRole('button', { name: 'Record Receipt' }));
    expect(onSubmit).toHaveBeenCalledWith([
      { line_item_id: 1, qty_received: 5, note: undefined },
    ]);
  });

  it('excludes a line zeroed out by the user', async () => {
    const onSubmit = vi.fn();
    const { getByRole } = render(ReceiveItemsForm, {
      props: { lineItems: [line()], onSubmit, onCancel: vi.fn() },
    });
    await fireEvent.input(getByRole('spinbutton'), { target: { value: '0' } });
    await fireEvent.click(getByRole('button', { name: 'Record Receipt' }));
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('excludes invoice_only lines from the receivable list', () => {
    // invoice_only lines (reconciliation-appended freight/etc.) were never
    // ordered/received — the server 400s if they're targeted via receive/.
    const { getByText, container } = render(ReceiveItemsForm, {
      props: {
        lineItems: [
          line({ line_item_id: 1, description: 'Bolt' }),
          line({ line_item_id: 2, description: 'Freight', invoice_only: true }),
        ],
        onSubmit: vi.fn(), onCancel: vi.fn(),
      },
    });
    expect(getByText('Bolt')).toBeInTheDocument();
    expect(container.textContent).not.toContain('Freight');
  });

  it('shows the all-received message when only an invoice_only line remains', () => {
    const { getByText } = render(ReceiveItemsForm, {
      props: {
        lineItems: [line({ description: 'Freight', invoice_only: true })],
        onSubmit: vi.fn(), onCancel: vi.fn(),
      },
    });
    expect(getByText('All items have been received.')).toBeInTheDocument();
  });

  it('cancels via onCancel', async () => {
    const onCancel = vi.fn();
    const { getByRole } = render(ReceiveItemsForm, {
      props: { lineItems: [line()], onSubmit: vi.fn(), onCancel },
    });
    await fireEvent.click(getByRole('button', { name: 'Cancel' }));
    expect(onCancel).toHaveBeenCalled();
  });
});

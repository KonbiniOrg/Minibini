import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, screen, waitFor } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn() },
}));

import { api } from '@/lib/api.js';
import AgreementAdjustmentsPanel from '@/components/invoices/AgreementAdjustmentsPanel.svelte';

const INVOICE_ID = 7;

const ADJUSTMENTS = [
  {
    adjustment_service_id: 10,
    description: 'Volume Discount 10%',
    percent: '-10.00',
    target_category_ids: [3, 4],
    already_added: false,
  },
  {
    adjustment_service_id: 20,
    description: 'Rush Fee 15%',
    percent: '15.00',
    target_category_ids: [],
    already_added: true,
  },
];

beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();
});

describe('AgreementAdjustmentsPanel', () => {
  it('renders nothing when the list is empty', async () => {
    api.get.mockResolvedValue({ adjustments: [] });
    const { container } = render(AgreementAdjustmentsPanel, {
      props: { invoiceId: INVOICE_ID },
    });
    // Wait for the async load to settle; nothing visible should be rendered.
    await waitFor(() => expect(api.get).toHaveBeenCalled());
    expect(container.querySelector('section')).toBeNull();
  });

  it('lists entries with description and percent', async () => {
    api.get.mockResolvedValue({ adjustments: ADJUSTMENTS });
    render(AgreementAdjustmentsPanel, { props: { invoiceId: INVOICE_ID } });

    expect(await screen.findByText(/Volume Discount 10%/)).toBeInTheDocument();
    expect(await screen.findByText(/Rush Fee 15%/)).toBeInTheDocument();
  });

  it('shows the percent value for each entry', async () => {
    api.get.mockResolvedValue({ adjustments: ADJUSTMENTS });
    render(AgreementAdjustmentsPanel, { props: { invoiceId: INVOICE_ID } });

    await screen.findByText(/Volume Discount 10%/);
    expect(screen.getByText(/-10\.00%/)).toBeInTheDocument();
    expect(screen.getByText(/15\.00%/)).toBeInTheDocument();
  });

  it('disables the Add button for already_added entries', async () => {
    api.get.mockResolvedValue({ adjustments: ADJUSTMENTS });
    render(AgreementAdjustmentsPanel, { props: { invoiceId: INVOICE_ID } });

    await screen.findByText(/Rush Fee 15%/);
    const buttons = screen.getAllByRole('button', { name: /add/i });
    // Rush Fee is already_added — its button should be disabled
    expect(buttons.some(b => b.disabled)).toBe(true);
  });

  it('available Add button is enabled', async () => {
    api.get.mockResolvedValue({ adjustments: ADJUSTMENTS });
    render(AgreementAdjustmentsPanel, { props: { invoiceId: INVOICE_ID } });

    await screen.findByText(/Volume Discount 10%/);
    const buttons = screen.getAllByRole('button', { name: /add/i });
    // At least one button is enabled
    expect(buttons.some(b => !b.disabled)).toBe(true);
  });

  it('clicking Add POSTs to adjustment-lines with correct body', async () => {
    api.get.mockResolvedValue({ adjustments: ADJUSTMENTS });
    api.post.mockResolvedValue({});

    render(AgreementAdjustmentsPanel, { props: { invoiceId: INVOICE_ID } });
    await screen.findByText(/Volume Discount 10%/);

    // Find the enabled Add button (for Volume Discount, which is not yet added)
    const buttons = screen.getAllByRole('button', { name: /add/i });
    const enabledButton = buttons.find(b => !b.disabled);
    await fireEvent.click(enabledButton);

    expect(api.post).toHaveBeenCalledWith(
      `/api/invoices/${INVOICE_ID}/adjustment-lines/`,
      { adjustment_service: 10, target_category_ids: [3, 4] },
    );
  });

  it('notifies the parent after Add so the wizard reloads its line items', async () => {
    api.get.mockResolvedValue({ adjustments: ADJUSTMENTS });
    api.post.mockResolvedValue({});
    const onLineItemAdded = vi.fn();
    render(AgreementAdjustmentsPanel, { props: { invoiceId: INVOICE_ID, onLineItemAdded } });
    await screen.findByText(/Rush Fee 15%/);
    const enabled = screen.getAllByRole('button', { name: /add/i }).find(b => !b.disabled);
    await fireEvent.click(enabled);
    await Promise.resolve();
    expect(onLineItemAdded).toHaveBeenCalled();
  });

  it('after Add, re-fetches so the entry flips to added (button becomes disabled)', async () => {
    // First GET returns with Volume Discount not yet added
    let callCount = 0;
    api.get.mockImplementation(() => {
      callCount += 1;
      if (callCount === 1) {
        return Promise.resolve({ adjustments: ADJUSTMENTS });
      }
      // Second call (after POST) — Volume Discount now also marked added
      return Promise.resolve({
        adjustments: [
          { ...ADJUSTMENTS[0], already_added: true },
          { ...ADJUSTMENTS[1], already_added: true },
        ],
      });
    });
    api.post.mockResolvedValue({});

    render(AgreementAdjustmentsPanel, { props: { invoiceId: INVOICE_ID } });
    await screen.findByText(/Volume Discount 10%/);

    const buttons = screen.getAllByRole('button', { name: /add/i });
    const enabledButton = buttons.find(b => !b.disabled);
    await fireEvent.click(enabledButton);

    // Wait for re-fetch and re-render
    await screen.findByText(/Volume Discount 10%/);
    const buttonsAfter = screen.getAllByRole('button', { name: /add/i });
    expect(buttonsAfter.every(b => b.disabled)).toBe(true);
  });
});

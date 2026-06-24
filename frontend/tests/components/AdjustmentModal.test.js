import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn() },
}));

import { api } from '@/lib/api.js';
import AdjustmentModal from '@/components/AdjustmentModal.svelte';

const SERVICES = [
  { service_price_id: 1, name: 'Rush', algorithm: 'percentage', rate: '15.00' },
  { service_price_id: 2, name: 'Discount', algorithm: 'percentage', rate: '-10.00' },
  { service_price_id: 3, name: 'Hourly', algorithm: 'elapsed_time', rate: '75.00' },
];
const CATEGORIES = [
  { id: 10, code: 'LAB', name: 'Labor', taxable: false },
  { id: 20, code: 'MAT', name: 'Materials', taxable: true },
];

beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();

  api.get.mockImplementation((url) => {
    if (url.includes('service-prices')) return Promise.resolve({ results: SERVICES });
    return Promise.resolve({ results: [] });
  });
  api.post.mockResolvedValue({ line_item_id: 99 });
});

describe('AdjustmentModal', () => {
  it('does not render when closed', () => {
    const { queryByRole } = render(AdjustmentModal, {
      props: {
        open: false,
        apiBase: '/api/estimates/7',
        categories: CATEGORIES,
        onSaved: vi.fn(),
        onClose: vi.fn(),
      },
    });
    expect(queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('fetches percentage services and shows them in the picker when open', async () => {
    const { findByRole, queryByText } = render(AdjustmentModal, {
      props: {
        open: true,
        apiBase: '/api/estimates/7',
        categories: CATEGORIES,
        onSaved: vi.fn(),
        onClose: vi.fn(),
      },
    });

    await findByRole('dialog');

    // percentage services appear (option text includes name), non-percentage do not
    expect(queryByText(/Rush/)).toBeInTheDocument();
    expect(queryByText(/Discount/)).toBeInTheDocument();
    expect(queryByText(/Hourly/)).not.toBeInTheDocument();
  });

  it('POSTs to adjustment-lines with selected service and no categories (all)', async () => {
    const onSaved = vi.fn();
    const { findByRole, findByLabelText, getByRole } = render(AdjustmentModal, {
      props: {
        open: true,
        apiBase: '/api/estimates/7',
        categories: CATEGORIES,
        onSaved,
        onClose: vi.fn(),
      },
    });

    await findByRole('dialog');
    const select = await findByLabelText(/service/i);
    await fireEvent.change(select, { target: { value: '1' } });
    await fireEvent.click(getByRole('button', { name: /add adjustment/i }));

    expect(api.post).toHaveBeenCalledWith('/api/estimates/7/adjustment-lines/', {
      adjustment_service: 1,
      target_category_ids: [],
    });
    expect(onSaved).toHaveBeenCalled();
  });

  it('POSTs with selected target categories', async () => {
    const onSaved = vi.fn();
    const { findByRole, findByLabelText, getByRole, getByText } = render(AdjustmentModal, {
      props: {
        open: true,
        apiBase: '/api/estimates/7',
        categories: CATEGORIES,
        onSaved,
        onClose: vi.fn(),
      },
    });

    await findByRole('dialog');

    const select = await findByLabelText(/service/i);
    await fireEvent.change(select, { target: { value: '1' } });

    // Select the Labor category checkbox
    const laborCheckbox = getByText('LAB - Labor').previousElementSibling ??
      getByText(/LAB.*Labor/);
    const checkbox = document.querySelector('input[type="checkbox"][value="10"]');
    if (checkbox) {
      await fireEvent.click(checkbox);
    }

    await fireEvent.click(getByRole('button', { name: /add adjustment/i }));

    expect(api.post).toHaveBeenCalledWith('/api/estimates/7/adjustment-lines/', {
      adjustment_service: 1,
      target_category_ids: [10],
    });
  });

  it('shows an error when no service is selected', async () => {
    const { findByRole, getByRole, findByText } = render(AdjustmentModal, {
      props: {
        open: true,
        apiBase: '/api/estimates/7',
        categories: CATEGORIES,
        onSaved: vi.fn(),
        onClose: vi.fn(),
      },
    });

    await findByRole('dialog');
    await fireEvent.click(getByRole('button', { name: /add adjustment/i }));

    expect(api.post).not.toHaveBeenCalled();
    expect(await findByText(/please choose a percentage service/i)).toBeInTheDocument();
  });

  it('calls onClose when Cancel is clicked', async () => {
    const onClose = vi.fn();
    const { findByRole, getByRole } = render(AdjustmentModal, {
      props: {
        open: true,
        apiBase: '/api/estimates/7',
        categories: CATEGORIES,
        onSaved: vi.fn(),
        onClose,
      },
    });

    await findByRole('dialog');
    await fireEvent.click(getByRole('button', { name: /cancel/i }));
    expect(onClose).toHaveBeenCalled();
  });
});

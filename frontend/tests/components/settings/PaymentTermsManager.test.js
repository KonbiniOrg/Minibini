import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  errorMessage: (e) => e?.message || 'error',
  fieldErrors: (errors, field) => {
    const v = errors?.[field];
    return Array.isArray(v) ? v : v ? [v] : [];
  },
}));
vi.mock('@/stores/messages.js', () => ({
  showError: vi.fn(), showSuccess: vi.fn(),
}));

import { api } from '@/lib/api.js';
import PaymentTermsManager from '@/components/settings/PaymentTermsManager.svelte';

const TERMS = [
  { term_id: 1, name: 'Net 30', days: 30, qbo_id: '3', business_count: 2 },
  { term_id: 2, name: 'Due on receipt', days: null, qbo_id: '', business_count: 0 },
];

beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();
  api.patch.mockReset();
  api.delete.mockReset();
  api.get.mockResolvedValue(TERMS);
});

afterEach(() => vi.restoreAllMocks());

describe('PaymentTermsManager', () => {
  it('lists terms with QBO badge and in-use counts', async () => {
    const { findByText } = render(PaymentTermsManager);
    expect(await findByText('Net 30')).toBeInTheDocument();
    expect(await findByText('QBO')).toBeInTheDocument();
    expect(await findByText('2 businesses')).toBeInTheDocument();
    expect(await findByText('Due on receipt')).toBeInTheDocument();
  });

  it('creates via the modal', async () => {
    api.post.mockResolvedValue({});
    const { findByText, findByPlaceholderText } = render(PaymentTermsManager);
    await fireEvent.click(await findByText('+ New terms'));
    const name = await findByPlaceholderText('Net 30');
    await fireEvent.input(name, { target: { value: 'Net 45' } });
    const days = await findByPlaceholderText('30');
    await fireEvent.input(days, { target: { value: '45' } });
    await fireEvent.click(await findByText('Save'));
    expect(api.post).toHaveBeenCalledWith('/api/payment-terms/',
      { name: 'Net 45', days: 45 });
  });

  it('renders a duplicate-name 400 under the name input', async () => {
    api.post.mockRejectedValue({
      status: 400,
      data: { name: ['Payment terms with this name already exist.'] },
    });
    const { findByText, findByPlaceholderText } = render(PaymentTermsManager);
    await fireEvent.click(await findByText('+ New terms'));
    const name = await findByPlaceholderText('Net 30');
    await fireEvent.input(name, { target: { value: 'Net 30' } });
    await fireEvent.click(await findByText('Save'));
    expect(await findByText('Payment terms with this name already exist.'))
      .toBeInTheDocument();
  });

  it('edits via the modal', async () => {
    api.patch.mockResolvedValue({});
    const { findAllByText, findByText, findByDisplayValue } =
      render(PaymentTermsManager);
    await fireEvent.click((await findAllByText('Edit'))[0]);
    expect(await findByDisplayValue('Net 30')).toBeInTheDocument();
    await fireEvent.click(await findByText('Save'));
    expect(api.patch).toHaveBeenCalledWith('/api/payment-terms/1/',
      { name: 'Net 30', days: 30 });
  });

  it('two-phase delete: impact then confirm=true', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    api.delete.mockResolvedValue(
      { confirm_required: true, impact: { businesses: 2 } });
    const { findAllByText } = render(PaymentTermsManager);
    await fireEvent.click((await findAllByText('Delete'))[0]);
    expect(window.confirm.mock.calls[0][0]).toMatch(/used by 2 businesses/);
    expect(api.delete).toHaveBeenCalledWith('/api/payment-terms/1/');
    expect(api.delete).toHaveBeenCalledWith('/api/payment-terms/1/?confirm=true');
  });

  it('declining the confirm skips the second delete', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false);
    api.delete.mockResolvedValue(
      { confirm_required: true, impact: { businesses: 0 } });
    const { findAllByText } = render(PaymentTermsManager);
    await fireEvent.click((await findAllByText('Delete'))[0]);
    expect(api.delete).toHaveBeenCalledTimes(1);
  });
});

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  errorMessage: (e, fallback) => e?.data?.detail || e?.message || fallback || 'Error',
}));

import { api } from '@/lib/api.js';
import ServiceItemManager from '@/components/ServiceItemManager.svelte';

const TMPL = { template_id: 1, template_name: 'Welding', rate_scheme: 1, is_active: true, default_active_modifiers: ['rush'], display_rate: '37.50' };
const FLAT_FEE_TMPL = { template_id: 2, template_name: 'Flat Weld', rate_scheme: 2, is_active: true, default_active_modifiers: [], display_rate: '150.00' };
const DELIVERY_TMPL = { template_id: 3, template_name: 'Delivery', rate_scheme: 3, is_active: true, default_active_modifiers: [{ amount: '50.00' }], display_rate: '50.00' };

const HOURLY_SCHEME = { rate_scheme_id: 1, name: 'Hourly', algorithm: 'elapsed_time', rate: '25', unit_label: 'hour', modifiers: [{ key: 'rush', label: 'Rush', percent: 50 }, { key: 'weekend', label: 'Weekend', percent: 25 }] };
const PERCENTAGE_SCHEME = { rate_scheme_id: 2, name: 'Quick Fix', algorithm: 'percentage', rate: '150', unit_label: 'none', modifiers: [] };
const REAL_FLAT_FEE_SCHEME = { rate_scheme_id: 3, name: 'Flat fee', algorithm: 'flat_fee', rate: '0.00', unit_label: 'fee', modifiers: [] };

beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();
  api.delete.mockReset();
  api.get.mockImplementation((url) => {
    if (url === '/api/service-items/') return Promise.resolve({ results: [TMPL, FLAT_FEE_TMPL, DELIVERY_TMPL] });
    if (url.startsWith('/api/rate-schemes/')) return Promise.resolve({ results: [HOURLY_SCHEME, PERCENTAGE_SCHEME, REAL_FLAT_FEE_SCHEME] });
    return Promise.resolve({ results: [] });
  });
  api.post.mockResolvedValue({});
  api.delete.mockResolvedValue({});
});

describe('ServiceItemManager', () => {
  it('loads and lists service items', async () => {
    const { findByText } = render(ServiceItemManager);
    expect(await findByText('Welding')).toBeInTheDocument();
  });

  it('lists the default-active modifiers with their rates', async () => {
    const { findByText, queryByText } = render(ServiceItemManager);
    expect(await findByText(/Rush \(\+50%\)/)).toBeInTheDocument();
    // 'weekend' exists on the scheme but is not default-active for the item.
    expect(queryByText(/Weekend/)).not.toBeInTheDocument();
  });

  it('shows "Rate Scheme" column header (not "Service")', async () => {
    const { findByRole } = render(ServiceItemManager);
    expect(await findByRole('columnheader', { name: 'Rate Scheme' })).toBeInTheDocument();
  });

  it('form labels the rate-scheme selector as "Rate Scheme"', async () => {
    const { findByRole, queryByLabelText } = render(ServiceItemManager);
    await fireEvent.click(await findByRole('button', { name: 'Add Service Item' }));
    expect(queryByLabelText(/Rate Scheme/)).toBeInTheDocument();
  });

  it('does not show an Amount input for a percentage rate scheme', async () => {
    const { findByRole, getByLabelText, queryByLabelText } = render(ServiceItemManager);
    await fireEvent.click(await findByRole('button', { name: 'Add Service Item' }));
    // Select the flat-fee rate scheme
    await fireEvent.change(getByLabelText(/Rate Scheme/), { target: { value: '2' } });
    // No flat fee price input should appear
    expect(queryByLabelText(/[Ff]lat fee/)).not.toBeInTheDocument();
  });

  it('saves a service item with active_modifiers as a list (not a dict)', async () => {
    const { findByRole, getByLabelText, getByRole } = render(ServiceItemManager);
    await fireEvent.click(await findByRole('button', { name: 'Add Service Item' }));
    await fireEvent.input(getByLabelText(/Name/), { target: { value: 'Painting' } });
    await fireEvent.change(getByLabelText(/Rate Scheme/), { target: { value: '2' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    expect(api.post).toHaveBeenCalledWith('/api/service-items/', expect.objectContaining({
      template_name: 'Painting',
      default_active_modifiers: expect.any(Array),
    }));
    // Ensure it is NOT a dict with flat_fee_price
    const call = api.post.mock.calls[0];
    expect(Array.isArray(call[1].default_active_modifiers)).toBe(true);
  });

  it('creates a service item', async () => {
    const { findByRole, getByLabelText, getByRole } = render(ServiceItemManager);
    await fireEvent.click(await findByRole('button', { name: 'Add Service Item' }));
    await fireEvent.input(getByLabelText(/Name/), { target: { value: 'Painting' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    expect(api.post).toHaveBeenCalledWith('/api/service-items/', expect.objectContaining({ template_name: 'Painting' }));
  });

  it('re-fetches the rate-scheme list when the form opens (stale-picker guard)', async () => {
    const { findByRole } = render(ServiceItemManager);
    await findByRole('button', { name: 'Add Service Item' });
    const schemeCallsAfterMount = api.get.mock.calls
      .filter(([url]) => url.startsWith('/api/rate-schemes/')).length;
    await fireEvent.click(await findByRole('button', { name: 'Add Service Item' }));
    const schemeCallsAfterOpen = api.get.mock.calls
      .filter(([url]) => url.startsWith('/api/rate-schemes/')).length;
    expect(schemeCallsAfterOpen).toBeGreaterThan(schemeCallsAfterMount);
  });

  it('deletes a service item after confirmation', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    const { findAllByRole } = render(ServiceItemManager);
    const deleteButtons = await findAllByRole('button', { name: 'Delete' });
    await fireEvent.click(deleteButtons[0]);
    expect(api.delete).toHaveBeenCalledWith('/api/service-items/1/');
    confirmSpy.mockRestore();
  });

  it('renders a field validation error under the offending input on save', async () => {
    api.post.mockRejectedValue({ status: 400, data: { template_name: ['This field is required.'] } });
    const { findByRole, getByRole, findByText } = render(ServiceItemManager);
    await fireEvent.click(await findByRole('button', { name: 'Add Service Item' }));
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    expect(await findByText('This field is required.')).toBeInTheDocument();
  });

  it('renders an operation error in the form footer on save', async () => {
    api.post.mockRejectedValue({ status: 400, data: { detail: 'Nope, not like that.' } });
    const { findByRole, getByLabelText, getByRole, findByText } = render(ServiceItemManager);
    await fireEvent.click(await findByRole('button', { name: 'Add Service Item' }));
    await fireEvent.input(getByLabelText(/Name/), { target: { value: 'Painting' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    const msg = await findByText('Nope, not like that.');
    expect(msg.closest('[role="alert"]')).not.toBeNull();
  });

  it('hides Add/Edit/Delete when canEdit is false', async () => {
    const { findByText, queryByRole } = render(ServiceItemManager, {
      props: { canEdit: false },
    });
    await findByText('Welding');
    // Table still renders (read-only), but no mutating controls.
    expect(queryByRole('button', { name: 'Add Service Item' })).toBeNull();
    expect(queryByRole('button', { name: 'Edit' })).toBeNull();
    expect(queryByRole('button', { name: 'Delete' })).toBeNull();
  });

  it('still shows the edit controls by default', async () => {
    const { findByRole } = render(ServiceItemManager);
    expect(await findByRole('button', { name: 'Add Service Item' })).toBeTruthy();
  });
});

describe('ServiceItemManager flat-fee amount field (2026-08-16)', () => {
  it('picking a flat_fee scheme shows an Amount field and no modifier text', async () => {
    const { findByRole, getByLabelText, queryByText } = render(ServiceItemManager);
    await fireEvent.click(await findByRole('button', { name: 'Add Service Item' }));
    await fireEvent.change(getByLabelText(/Rate Scheme/), { target: { value: '3' } });
    expect(getByLabelText(/Amount/)).toBeTruthy();
    expect(queryByText(/[Mm]odifier/)).toBeNull();
  });

  it('saving a flat-fee item POSTs the one-entry amount config', async () => {
    const { findByRole, getByLabelText, getByRole } = render(ServiceItemManager);
    await fireEvent.click(await findByRole('button', { name: 'Add Service Item' }));
    const nameInput = document.body.querySelector('input[type="text"]');
    await fireEvent.input(nameInput, { target: { value: 'Delivery' } });
    await fireEvent.change(getByLabelText(/Rate Scheme/), { target: { value: '3' } });
    await fireEvent.input(getByLabelText(/Amount/), { target: { value: '50.00' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    const body = api.post.mock.calls.find((c) => c[0] === '/api/service-items/')[1];
    expect(body.default_active_modifiers).toEqual([{ amount: '50.00' }]);
  });

  it('editing a flat-fee item prefills the Amount field from its config', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/api/service-items/') return Promise.resolve({ results: [
        { template_id: 9, template_name: 'Delivery', rate_scheme: 3, is_active: true,
          default_active_modifiers: [{ amount: '50.00' }] },
      ] });
      if (url.startsWith('/api/rate-schemes/')) return Promise.resolve({ results: [HOURLY_SCHEME, REAL_FLAT_FEE_SCHEME] });
      return Promise.resolve({ results: [] });
    });
    const { findByRole, getByLabelText } = render(ServiceItemManager);
    await fireEvent.click(await findByRole('button', { name: 'Edit' }));
    expect(getByLabelText(/Amount/).value).toBe('50.00');
  });
});

describe('ServiceItemManager list price notes (RM 2026-08-17)', () => {
  it('percent-style row: base rate, modifiers, effective rate per unit', async () => {
    const { findByText } = render(ServiceItemManager);
    // "Hourly at $25, Rush (+50%) — $37.50/hour" shape
    expect(await findByText(/at \$25.*Rush \(\+50%\).*\$37\.50\/hour/)).toBeInTheDocument();
  });

  it('flat-fee row shows its amount per unit', async () => {
    const { findByText } = render(ServiceItemManager);
    expect(await findByText(/\$50\.00\/fee/)).toBeInTheDocument();
  });

  it('percentage-scheme row shows no price note', async () => {
    const { findByText, queryByText } = render(ServiceItemManager);
    await findByText('Flat Weld');
    // The percentage scheme's display_rate must not render as a money note.
    expect(queryByText(/\$150\.00/)).toBeNull();
  });
});

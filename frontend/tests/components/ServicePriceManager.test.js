import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() } }));

import { api } from '@/lib/api.js';
import ServicePriceManager from '@/components/ServicePriceManager.svelte';

const SCHEME = { service_price_id: 1, name: 'Hourly', algorithm: 'elapsed_time', rate: '25', unit_label: 'hr', modifiers: [], reference_counts: {} };
const FLAT_FEE_SCHEME = { service_price_id: 2, name: 'Flat Weld', algorithm: 'flat_fee', rate: '150', unit_label: 'none', modifiers: [], reference_counts: {} };

beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();
  api.delete.mockReset();
  api.get.mockImplementation((url) => {
    if (url.startsWith('/api/service-prices/')) return Promise.resolve({ results: [SCHEME] });
    if (url === '/api/accounting-categories/') return Promise.resolve({ results: [{ id: 1, code: 'C1', name: 'Labor' }] });
    if (url === '/api/settings/units/') return Promise.resolve(['none', 'hr']);
    return Promise.resolve({ results: [] });
  });
  api.post.mockResolvedValue({});
  api.delete.mockResolvedValue({});
});

describe('ServicePriceManager', () => {
  it('loads and lists schemes', async () => {
    const { findByText } = render(ServicePriceManager);
    expect(await findByText('Hourly')).toBeInTheDocument();
  });

  it('shows "Services" as the section heading', async () => {
    const { findByRole } = render(ServicePriceManager);
    expect(await findByRole('heading', { name: 'Services' })).toBeInTheDocument();
  });

  it('has an "Add Service" button (not "Add Rate Scheme")', async () => {
    const { findByRole, queryByRole } = render(ServicePriceManager);
    expect(await findByRole('button', { name: 'Add Service' })).toBeInTheDocument();
    expect(queryByRole('button', { name: 'Add Rate Scheme' })).not.toBeInTheDocument();
  });

  it('creates a scheme with rate field for flat-fee algorithm', async () => {
    const { findByRole, getByLabelText, getByRole } = render(ServicePriceManager);
    await fireEvent.click(await findByRole('button', { name: 'Add Service' }));
    // Switch to flat-fee
    await fireEvent.change(getByLabelText(/Algorithm/), { target: { value: 'flat_fee' } });
    // Should have a Rate field (not a separate flat_fee_price)
    expect(getByLabelText(/Rate/)).toBeInTheDocument();
    await fireEvent.input(getByLabelText(/Name/), { target: { value: 'Quick Fix' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    expect(api.post).toHaveBeenCalledWith('/api/service-prices/', expect.objectContaining({ name: 'Quick Fix', algorithm: 'flat_fee' }));
  });

  it('creates a scheme', async () => {
    const { findByRole, getByLabelText, getByRole } = render(ServicePriceManager);
    await fireEvent.click(await findByRole('button', { name: 'Add Service' }));
    await fireEvent.input(getByLabelText(/Name/), { target: { value: 'Premium' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    expect(api.post).toHaveBeenCalledWith('/api/service-prices/', expect.objectContaining({ name: 'Premium' }));
  });

  it('deletes an unreferenced scheme after confirmation', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    const { findByRole } = render(ServicePriceManager);
    await fireEvent.click(await findByRole('button', { name: 'Delete' }));
    expect(api.delete).toHaveBeenCalledWith('/api/service-prices/1/');
    confirmSpy.mockRestore();
  });

  it('percentage algorithm: shows rate field (negative allowed), AC selector, and hides modifier editor', async () => {
    const { findByRole, getByLabelText, queryByText } = render(ServicePriceManager);
    await fireEvent.click(await findByRole('button', { name: 'Add Service' }));
    await fireEvent.change(getByLabelText(/Algorithm/), { target: { value: 'percentage' } });

    // Rate field is present
    const rateInput = getByLabelText(/Rate/);
    expect(rateInput).toBeInTheDocument();
    // Negative values allowed (min attribute not present or no constraint forcing positive)
    expect(rateInput.getAttribute('min')).toBeNull();

    // AC selector is present
    expect(getByLabelText(/Accounting Category/)).toBeInTheDocument();

    // Modifier editor is NOT rendered
    expect(queryByText('Add modifier')).not.toBeInTheDocument();
  });
});

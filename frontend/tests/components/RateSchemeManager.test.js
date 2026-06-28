import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() } }));

import { api } from '@/lib/api.js';
import RateSchemeManager from '@/components/RateSchemeManager.svelte';

const SCHEME = { rate_scheme_id: 1, name: 'Hourly', algorithm: 'elapsed_time', rate: '25', unit_label: 'hr', modifiers: [], reference_counts: {} };
const FLAT_FEE_SCHEME = { rate_scheme_id: 2, name: 'Flat Weld', algorithm: 'flat_fee', rate: '150', unit_label: 'none', modifiers: [], reference_counts: {} };

beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();
  api.delete.mockReset();
  api.get.mockImplementation((url) => {
    if (url.startsWith('/api/rate-schemes/')) return Promise.resolve({ results: [SCHEME] });
    if (url === '/api/accounting-categories/') return Promise.resolve({ results: [{ id: 1, code: 'C1', name: 'Labor' }] });
    if (url === '/api/settings/units/') return Promise.resolve(['none', 'hr']);
    return Promise.resolve({ results: [] });
  });
  api.post.mockResolvedValue({});
  api.delete.mockResolvedValue({});
});

describe('RateSchemeManager', () => {
  it('loads and lists schemes', async () => {
    const { findByText } = render(RateSchemeManager);
    expect(await findByText('Hourly')).toBeInTheDocument();
  });

  it('shows "Rate Schemes" as the section heading', async () => {
    const { findByRole } = render(RateSchemeManager);
    expect(await findByRole('heading', { name: 'Rate Schemes' })).toBeInTheDocument();
  });

  it('has an "Add Rate Scheme" button (not "Add Service")', async () => {
    const { findByRole, queryByRole } = render(RateSchemeManager);
    expect(await findByRole('button', { name: 'Add Rate Scheme' })).toBeInTheDocument();
    expect(queryByRole('button', { name: 'Add Service' })).not.toBeInTheDocument();
  });

  it('creates a scheme with rate field for flat-fee algorithm', async () => {
    const { findByRole, getByLabelText, getByRole } = render(RateSchemeManager);
    await fireEvent.click(await findByRole('button', { name: 'Add Rate Scheme' }));
    // Switch to flat-fee
    await fireEvent.change(getByLabelText(/Algorithm/), { target: { value: 'flat_fee' } });
    // Should have a Rate field (not a separate flat_fee_price)
    expect(getByLabelText(/Rate/)).toBeInTheDocument();
    await fireEvent.input(getByLabelText(/Name/), { target: { value: 'Quick Fix' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    expect(api.post).toHaveBeenCalledWith('/api/rate-schemes/', expect.objectContaining({ name: 'Quick Fix', algorithm: 'flat_fee' }));
  });

  it('creates a scheme', async () => {
    const { findByRole, getByLabelText, getByRole } = render(RateSchemeManager);
    await fireEvent.click(await findByRole('button', { name: 'Add Rate Scheme' }));
    await fireEvent.input(getByLabelText(/Name/), { target: { value: 'Premium' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    expect(api.post).toHaveBeenCalledWith('/api/rate-schemes/', expect.objectContaining({ name: 'Premium' }));
  });

  it('keeps the existing-schemes list visible while adding a new one', async () => {
    const { findByRole, getByText, queryByRole } = render(RateSchemeManager);
    // Existing scheme is listed before adding.
    expect(await findByRole('button', { name: 'Add Rate Scheme' })).toBeInTheDocument();
    expect(getByText('Hourly')).toBeInTheDocument();
    // Open the add form — the list must NOT be suppressed.
    await fireEvent.click(await findByRole('button', { name: 'Add Rate Scheme' }));
    expect(getByText('Hourly')).toBeInTheDocument();           // existing rows still shown
    expect(await findByRole('button', { name: 'Save' })).toBeInTheDocument(); // form is open
    // The Add Rate Scheme button is hidden while the form is open (no double-add).
    expect(queryByRole('button', { name: 'Add Rate Scheme' })).not.toBeInTheDocument();
  });

  it('deletes an unreferenced scheme after confirmation', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    const { findByRole } = render(RateSchemeManager);
    await fireEvent.click(await findByRole('button', { name: 'Delete' }));
    expect(api.delete).toHaveBeenCalledWith('/api/rate-schemes/1/');
    confirmSpy.mockRestore();
  });

  it('percentage algorithm: shows rate field (negative allowed), AC selector, and hides modifier editor', async () => {
    const { findByRole, getByLabelText, queryByText } = render(RateSchemeManager);
    await fireEvent.click(await findByRole('button', { name: 'Add Rate Scheme' }));
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

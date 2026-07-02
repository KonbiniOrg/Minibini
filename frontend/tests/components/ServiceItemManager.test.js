import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() } }));

import { api } from '@/lib/api.js';
import ServiceItemManager from '@/components/ServiceItemManager.svelte';

const TMPL = { template_id: 1, template_name: 'Welding', rate_scheme: 1, is_active: true, default_active_modifiers: [] };
const FLAT_FEE_TMPL = { template_id: 2, template_name: 'Flat Weld', rate_scheme: 2, is_active: true, default_active_modifiers: [] };

const HOURLY_SCHEME = { rate_scheme_id: 1, name: 'Hourly', algorithm: 'elapsed_time', rate: '25', unit_label: 'hr', modifiers: [] };
const FLAT_FEE_SCHEME = { rate_scheme_id: 2, name: 'Quick Fix', algorithm: 'flat_fee', rate: '150', unit_label: 'none', modifiers: [] };

beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();
  api.delete.mockReset();
  api.get.mockImplementation((url) => {
    if (url === '/api/service-items/') return Promise.resolve({ results: [TMPL, FLAT_FEE_TMPL] });
    if (url.startsWith('/api/rate-schemes/')) return Promise.resolve({ results: [HOURLY_SCHEME, FLAT_FEE_SCHEME] });
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

  it('shows "Rate Scheme" column header (not "Service")', async () => {
    const { findByRole } = render(ServiceItemManager);
    expect(await findByRole('columnheader', { name: 'Rate Scheme' })).toBeInTheDocument();
  });

  it('form labels the rate-scheme selector as "Rate Scheme"', async () => {
    const { findByRole, queryByLabelText } = render(ServiceItemManager);
    await fireEvent.click(await findByRole('button', { name: 'Add Service Item' }));
    expect(queryByLabelText(/Rate Scheme/)).toBeInTheDocument();
  });

  it('does not show a flat_fee_price input for a flat-fee rate scheme', async () => {
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

  it('deletes a service item after confirmation', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    const { findAllByRole } = render(ServiceItemManager);
    const deleteButtons = await findAllByRole('button', { name: 'Delete' });
    await fireEvent.click(deleteButtons[0]);
    expect(api.delete).toHaveBeenCalledWith('/api/service-items/1/');
    confirmSpy.mockRestore();
  });
});

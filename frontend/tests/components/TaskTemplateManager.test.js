import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() } }));

import { api } from '@/lib/api.js';
import TaskTemplateManager from '@/components/TaskTemplateManager.svelte';

const TMPL = { template_id: 1, template_name: 'Welding', service_price: 1, default_billable_qty: '', is_active: true, default_active_modifiers: [] };
const FLAT_FEE_TMPL = { template_id: 2, template_name: 'Flat Weld', service_price: 2, default_billable_qty: '', is_active: true, default_active_modifiers: [] };

const HOURLY_SCHEME = { service_price_id: 1, name: 'Hourly', algorithm: 'elapsed_time', rate: '25', unit_label: 'hr', modifiers: [] };
const FLAT_FEE_SCHEME = { service_price_id: 2, name: 'Quick Fix', algorithm: 'flat_fee', rate: '150', unit_label: 'none', modifiers: [] };

beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();
  api.delete.mockReset();
  api.get.mockImplementation((url) => {
    if (url === '/api/task-templates/') return Promise.resolve({ results: [TMPL, FLAT_FEE_TMPL] });
    if (url.startsWith('/api/service-prices/')) return Promise.resolve({ results: [HOURLY_SCHEME, FLAT_FEE_SCHEME] });
    return Promise.resolve({ results: [] });
  });
  api.post.mockResolvedValue({});
  api.delete.mockResolvedValue({});
});

describe('TaskTemplateManager', () => {
  it('loads and lists templates', async () => {
    const { findByText } = render(TaskTemplateManager);
    expect(await findByText('Welding')).toBeInTheDocument();
  });

  it('shows "Service" column header (not "Rate Scheme")', async () => {
    const { findByText, queryByText } = render(TaskTemplateManager);
    await findByText('Welding'); // wait for load
    expect(queryByText('Rate Scheme')).not.toBeInTheDocument();
  });

  it('form labels service selector as "Service" (not "Rate Scheme")', async () => {
    const { findByRole, queryByLabelText } = render(TaskTemplateManager);
    await fireEvent.click(await findByRole('button', { name: 'Add Template' }));
    // Should NOT have a "Rate Scheme" label
    expect(queryByLabelText(/Rate Scheme/)).not.toBeInTheDocument();
    // Should have a "Service" label
    expect(queryByLabelText(/Service/)).toBeInTheDocument();
  });

  it('does not show a flat_fee_price input for flat-fee service', async () => {
    const { findByRole, getByLabelText, queryByLabelText } = render(TaskTemplateManager);
    await fireEvent.click(await findByRole('button', { name: 'Add Template' }));
    // Select the flat-fee service
    await fireEvent.change(getByLabelText(/Service/), { target: { value: '2' } });
    // No flat fee price input should appear
    expect(queryByLabelText(/[Ff]lat fee/)).not.toBeInTheDocument();
  });

  it('saves flat-fee template with active_modifiers as a list (not a dict)', async () => {
    const { findByRole, getByLabelText, getByRole } = render(TaskTemplateManager);
    await fireEvent.click(await findByRole('button', { name: 'Add Template' }));
    await fireEvent.input(getByLabelText(/Name/), { target: { value: 'Painting' } });
    await fireEvent.change(getByLabelText(/Service/), { target: { value: '2' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    expect(api.post).toHaveBeenCalledWith('/api/task-templates/', expect.objectContaining({
      template_name: 'Painting',
      default_active_modifiers: expect.any(Array),
    }));
    // Ensure it is NOT a dict with flat_fee_price
    const call = api.post.mock.calls[0];
    expect(Array.isArray(call[1].default_active_modifiers)).toBe(true);
  });

  it('creates a template', async () => {
    const { findByRole, getByLabelText, getByRole } = render(TaskTemplateManager);
    await fireEvent.click(await findByRole('button', { name: 'Add Template' }));
    await fireEvent.input(getByLabelText(/Name/), { target: { value: 'Painting' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    expect(api.post).toHaveBeenCalledWith('/api/task-templates/', expect.objectContaining({ template_name: 'Painting' }));
  });

  it('deletes a template after confirmation', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    const { findAllByRole } = render(TaskTemplateManager);
    const deleteButtons = await findAllByRole('button', { name: 'Delete' });
    await fireEvent.click(deleteButtons[0]);
    expect(api.delete).toHaveBeenCalledWith('/api/task-templates/1/');
    confirmSpy.mockRestore();
  });
});

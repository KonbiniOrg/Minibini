import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() } }));

import { api } from '@/lib/api.js';
import RateSchemeManager from '@/components/RateSchemeManager.svelte';

const SCHEME = { rate_scheme_id: 1, name: 'Hourly', algorithm: 'elapsed_time', rate: '25', unit_label: 'hour', accounting_category: 1, modifiers: [], reference_counts: {} };

beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();
  api.delete.mockReset();
  api.get.mockImplementation((url) => {
    if (url.startsWith('/api/rate-schemes/')) return Promise.resolve({ results: [SCHEME] });
    if (url === '/api/accounting-categories/') return Promise.resolve({ results: [{ id: 1, code: 'C1', name: 'Labor' }] });
    if (url === '/api/settings/units/') return Promise.resolve(['none', 'hour']);
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

  it('shows the accounting category in the scheme row', async () => {
    const { findByText } = render(RateSchemeManager);
    expect(await findByText('C1 — Labor')).toBeInTheDocument();
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

  it('drops an untouched blank modifier row from the save payload', async () => {
    const { findByRole, getByLabelText, getByRole } = render(RateSchemeManager);
    await fireEvent.click(await findByRole('button', { name: 'Add Rate Scheme' }));
    await fireEvent.input(getByLabelText(/Name/), { target: { value: 'With blank mod' } });
    // Add a modifier row and leave it empty (label '', percent '').
    await fireEvent.click(getByRole('button', { name: /add modifier/i }));
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    expect(api.post).toHaveBeenCalledWith(
      '/api/rate-schemes/',
      expect.objectContaining({ modifiers: [] }),
    );
  });

  it('keeps a filled-in modifier row in the save payload', async () => {
    const { findByRole, getByLabelText, getByRole, getByPlaceholderText } = render(RateSchemeManager);
    await fireEvent.click(await findByRole('button', { name: 'Add Rate Scheme' }));
    await fireEvent.input(getByLabelText(/Name/), { target: { value: 'With real mod' } });
    await fireEvent.click(getByRole('button', { name: /add modifier/i }));
    await fireEvent.input(getByPlaceholderText('Label'), { target: { value: 'Rush' } });
    await fireEvent.input(getByPlaceholderText('%'), { target: { value: '50' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    expect(api.post).toHaveBeenCalledWith(
      '/api/rate-schemes/',
      expect.objectContaining({
        modifiers: [{ key: 'rush', label: 'Rush', percent: 50 }],
      }),
    );
  });

  it('percentage algorithm: shows rate field (negative allowed), AC selector, and hides modifier editor', async () => {
    const { findByRole, getByLabelText, queryByText } = render(RateSchemeManager);
    await fireEvent.click(await findByRole('button', { name: 'Add Rate Scheme' }));
    await fireEvent.change(getByLabelText(/Algorithm/), { target: { value: 'percentage' } });

    // Rate field is present. Anchored regex: the modal shell exposes an
    // aria-label ("New Rate Scheme") that a bare /Rate/ also matches.
    const rateInput = getByLabelText(/^Rate/);
    expect(rateInput).toBeInTheDocument();
    // Negative values allowed (min attribute not present or no constraint forcing positive)
    expect(rateInput.getAttribute('min')).toBeNull();

    // AC selector is present
    expect(getByLabelText(/Accounting Category/)).toBeInTheDocument();

    // Modifier editor is NOT rendered
    expect(queryByText('Add modifier')).not.toBeInTheDocument();
  });

  // 2026-07-30: the add/edit form moved from an inline <fieldset> in the page
  // flow into the shared Modal shell, like every other record create/edit
  // surface. Behaviour is unchanged — this covers the shell wiring.
  it('renders the add form inside the Modal shell, not inline in the page', async () => {
    const { findByRole, container } = render(RateSchemeManager);
    expect(container.querySelector('.modal')).toBeNull();   // closed by default
    await fireEvent.click(await findByRole('button', { name: 'Add Rate Scheme' }));
    const modal = container.querySelector('.modal');
    expect(modal).not.toBeNull();
    // The form fields live inside the shell.
    expect(modal.querySelector('input')).not.toBeNull();
    expect(modal.querySelector('select')).not.toBeNull();
    expect(await findByRole('button', { name: 'Save' })).toBeInTheDocument();
  });

  // Description was dropped from the form 2026-07-30; the model field is
  // slated to go too. Nothing should send or render it.
  it('has no Description field and never sends description', async () => {
    const { findByRole, getByLabelText, getByRole, queryByLabelText } = render(RateSchemeManager);
    await fireEvent.click(await findByRole('button', { name: 'Add Rate Scheme' }));
    expect(queryByLabelText(/Description/)).toBeNull();

    await fireEvent.input(getByLabelText(/Name/), { target: { value: 'NoDesc' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    const payload = api.post.mock.calls.find((c) => c[0] === '/api/rate-schemes/')[1];
    expect(payload).not.toHaveProperty('description');
  });

  it('Escape closes the form (the shell keyboard contract)', async () => {
    const { findByRole, container, queryByRole } = render(RateSchemeManager);
    await fireEvent.click(await findByRole('button', { name: 'Add Rate Scheme' }));
    expect(container.querySelector('.modal')).not.toBeNull();
    await fireEvent.keyDown(window, { key: 'Escape' });
    expect(container.querySelector('.modal')).toBeNull();
    expect(queryByRole('button', { name: 'Save' })).not.toBeInTheDocument();
  });

  it('Cancel closes the form and reopening starts clean', async () => {
    const { findByRole, getByLabelText, getByRole, container } = render(RateSchemeManager);
    await fireEvent.click(await findByRole('button', { name: 'Add Rate Scheme' }));
    await fireEvent.input(getByLabelText(/Name/), { target: { value: 'Scratch' } });
    await fireEvent.click(getByRole('button', { name: 'Cancel' }));
    expect(container.querySelector('.modal')).toBeNull();

    await fireEvent.click(await findByRole('button', { name: 'Add Rate Scheme' }));
    expect(getByLabelText(/Name/).value).toBe('');
  });

  it('the edit form opens in the modal too, prefilled', async () => {
    const { findByRole, getByLabelText, container } = render(RateSchemeManager);
    await fireEvent.click(await findByRole('button', { name: 'Edit' }));
    expect(container.querySelector('.modal')).not.toBeNull();
    expect(getByLabelText(/Name/).value).toBe('Hourly');
  });

  it('locks the unit label to a disabled "hour" input while algorithm is elapsed_time, and restores the select on switch', async () => {
    const { findByRole, getByLabelText, queryByRole } = render(RateSchemeManager);
    // Add starts on the default algorithm, elapsed_time.
    await fireEvent.click(await findByRole('button', { name: 'Add Rate Scheme' }));
    const unitField = getByLabelText(/Unit label/);
    expect(unitField.tagName).toBe('INPUT');
    expect(unitField).toBeDisabled();
    expect(unitField.value).toBe('hour');
    expect(queryByRole('combobox', { name: /Unit label/ })).not.toBeInTheDocument();

    await fireEvent.change(getByLabelText(/Algorithm/), { target: { value: 'entered_qty' } });
    const unitSelect = getByLabelText(/Unit label/);
    expect(unitSelect.tagName).toBe('SELECT');
    expect(unitSelect).not.toBeDisabled();
  });

  it('preview text is not naively pluralized ("hour", never "hours")', async () => {
    const { findByRole, getByLabelText, getByText } = render(RateSchemeManager);
    await fireEvent.click(await findByRole('button', { name: 'Add Rate Scheme' }));
    await fireEvent.input(getByLabelText(/^Rate/), { target: { value: '25' } });
    const preview = getByText(/^Preview:/).closest('p');
    expect(preview).toHaveTextContent('10 hour @ $25.00/hour = $250.00');
    expect(preview).not.toHaveTextContent(/hours/);
  });

  it('forces unit_label to hour on save for an elapsed_time scheme even though the control is locked', async () => {
    const { findByRole, getByLabelText, getByRole } = render(RateSchemeManager);
    await fireEvent.click(await findByRole('button', { name: 'Add Rate Scheme' }));
    await fireEvent.input(getByLabelText(/Name/), { target: { value: 'Milling' } });
    await fireEvent.input(getByLabelText(/^Rate/), { target: { value: '25' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    expect(api.post).toHaveBeenCalledWith(
      '/api/rate-schemes/',
      expect.objectContaining({ algorithm: 'elapsed_time', unit_label: 'hour' }),
    );
  });
});

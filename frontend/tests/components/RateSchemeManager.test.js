import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() } }));

import { api } from '@/lib/api.js';
import RateSchemeManager from '@/components/RateSchemeManager.svelte';

const SCHEME = { rate_scheme_id: 1, name: 'Hourly', algorithm: 'elapsed_time', rate: '25', unit_label: 'hour', accounting_category: 1, modifiers: [], reference_counts: {}, is_active: true };
const INACTIVE_SCHEME = { rate_scheme_id: 2, name: 'Retired Rate', algorithm: 'elapsed_time', rate: '10', unit_label: 'hour', accounting_category: 1, modifiers: [], reference_counts: {}, is_active: false };

function mockSettings(overrides = {}) {
  return { default_rate_scheme: '', ...overrides };
}

beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();
  api.patch.mockReset();
  api.delete.mockReset();
  api.get.mockImplementation((url) => {
    if (url.startsWith('/api/rate-schemes/')) return Promise.resolve({ results: [SCHEME] });
    if (url === '/api/accounting-categories/') return Promise.resolve({ results: [{ id: 1, code: 'C1', name: 'Labor' }] });
    if (url === '/api/settings/units/') return Promise.resolve(['none', 'hour']);
    if (url === '/api/settings/') return Promise.resolve(mockSettings());
    return Promise.resolve({ results: [] });
  });
  api.post.mockResolvedValue({});
  api.patch.mockResolvedValue({});
  api.delete.mockResolvedValue({});
});

describe('RateSchemeManager', () => {
  it('loads and lists schemes', async () => {
    const { findByRole } = render(RateSchemeManager);
    // 'Hourly' also appears as an option in the default-preset picker, so
    // scope to the table row (cell), not a bare text match.
    expect(await findByRole('cell', { name: 'Hourly' })).toBeInTheDocument();
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
    const { findByRole, getByRole, queryByRole } = render(RateSchemeManager);
    // Existing scheme is listed before adding. ('Hourly' also appears as a
    // default-preset picker option, so scope to the table row via 'cell'.)
    expect(await findByRole('button', { name: 'Add Rate Scheme' })).toBeInTheDocument();
    expect(getByRole('cell', { name: 'Hourly' })).toBeInTheDocument();
    // Open the add form — the list must NOT be suppressed.
    await fireEvent.click(await findByRole('button', { name: 'Add Rate Scheme' }));
    expect(getByRole('cell', { name: 'Hourly' })).toBeInTheDocument();  // existing rows still shown
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
    const unitField = getByLabelText(/^Unit$/);
    expect(unitField.tagName).toBe('INPUT');
    expect(unitField).toBeDisabled();
    expect(unitField.value).toBe('hour');
    expect(queryByRole('combobox', { name: /^Unit$/ })).not.toBeInTheDocument();

    await fireEvent.change(getByLabelText(/Algorithm/), { target: { value: 'entered_qty' } });
    const unitSelect = getByLabelText(/^Unit$/);
    expect(unitSelect.tagName).toBe('SELECT');
    expect(unitSelect).not.toBeDisabled();
  });

  it('editing an entered_qty scheme: flipping algorithm to elapsed_time and back restores the original unit (regression: display-only, must not clobber form state)', async () => {
    const enteredScheme = {
      rate_scheme_id: 9, name: 'Piecework', algorithm: 'entered_qty',
      rate: '5', unit_label: 'pc', accounting_category: 1, modifiers: [], reference_counts: {},
    };
    api.get.mockImplementation((url) => {
      if (url.startsWith('/api/rate-schemes/')) return Promise.resolve({ results: [enteredScheme] });
      if (url === '/api/accounting-categories/') return Promise.resolve({ results: [{ id: 1, code: 'C1', name: 'Labor' }] });
      if (url === '/api/settings/units/') return Promise.resolve(['none', 'hour', 'pc']);
      return Promise.resolve({ results: [] });
    });
    const { findByRole, getByLabelText } = render(RateSchemeManager);
    await fireEvent.click(await findByRole('button', { name: 'Edit' }));
    expect(getByLabelText(/^Unit$/).value).toBe('pc');

    await fireEvent.change(getByLabelText(/Algorithm/), { target: { value: 'elapsed_time' } });
    expect(getByLabelText(/^Unit$/).value).toBe('hour'); // locked display

    await fireEvent.change(getByLabelText(/Algorithm/), { target: { value: 'entered_qty' } });
    // The real fix under test: no reactive effect ever wrote 'hour' back
    // into form.unit_label, so the original value survives the round trip.
    expect(getByLabelText(/^Unit$/).value).toBe('pc');
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

  it('shows "Yes" in the Active column for an active scheme, and no supersession affordances anywhere', async () => {
    const { findByRole, queryByRole, queryByText } = render(RateSchemeManager);
    expect(await findByRole('cell', { name: 'Yes' })).toBeInTheDocument();
    expect(queryByRole('button', { name: /Create new version/ })).not.toBeInTheDocument();
    expect(queryByText(/superseded/i)).not.toBeInTheDocument();
    expect(queryByRole('checkbox', { name: /Show superseded/ })).not.toBeInTheDocument();
  });

  it('Edit and Delete remain available for a scheme with references (no longer hidden)', async () => {
    const referenced = { ...SCHEME, reference_counts: { task_count: 3, service_item_count: 1 } };
    api.get.mockImplementation((url) => {
      if (url.startsWith('/api/rate-schemes/')) return Promise.resolve({ results: [referenced] });
      if (url === '/api/accounting-categories/') return Promise.resolve({ results: [{ id: 1, code: 'C1', name: 'Labor' }] });
      if (url === '/api/settings/units/') return Promise.resolve(['none', 'hour']);
      if (url === '/api/settings/') return Promise.resolve(mockSettings());
      return Promise.resolve({ results: [] });
    });
    const { findByRole } = render(RateSchemeManager);
    expect(await findByRole('button', { name: 'Edit' })).toBeInTheDocument();
    expect(await findByRole('button', { name: 'Delete' })).toBeInTheDocument();
  });

  it('retires an active scheme with no confirm dialog, and refreshes the list afterward', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm');
    const { findByRole } = render(RateSchemeManager);
    const getCallsBefore = api.get.mock.calls.length;
    await fireEvent.click(await findByRole('button', { name: 'Retire' }));
    expect(api.post).toHaveBeenCalledWith('/api/rate-schemes/1/retire/');
    expect(confirmSpy).not.toHaveBeenCalled();
    expect(api.get.mock.calls.length).toBeGreaterThan(getCallsBefore); // list reloaded
    confirmSpy.mockRestore();
  });

  it('shows Reactivate (not Retire) for an inactive scheme once "Show inactive" reveals it, and reactivating calls the endpoint with no confirm dialog', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm');
    api.get.mockImplementation((url) => {
      if (url === '/api/rate-schemes/?include_inactive=true') return Promise.resolve({ results: [SCHEME, INACTIVE_SCHEME] });
      if (url.startsWith('/api/rate-schemes/')) return Promise.resolve({ results: [SCHEME] });
      if (url === '/api/accounting-categories/') return Promise.resolve({ results: [{ id: 1, code: 'C1', name: 'Labor' }] });
      if (url === '/api/settings/units/') return Promise.resolve(['none', 'hour']);
      if (url === '/api/settings/') return Promise.resolve(mockSettings());
      return Promise.resolve({ results: [] });
    });
    const { findByRole, findByText } = render(RateSchemeManager);
    await fireEvent.click(await findByRole('checkbox', { name: /Show inactive/ }));
    expect(await findByText('Retired Rate')).toBeInTheDocument();
    await fireEvent.click(await findByRole('button', { name: 'Reactivate' }));
    expect(api.post).toHaveBeenCalledWith('/api/rate-schemes/2/reactivate/');
    expect(confirmSpy).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });

  it('default preset picker renders the current default from settings', async () => {
    api.get.mockImplementation((url) => {
      if (url.startsWith('/api/rate-schemes/')) return Promise.resolve({ results: [SCHEME] });
      if (url === '/api/accounting-categories/') return Promise.resolve({ results: [{ id: 1, code: 'C1', name: 'Labor' }] });
      if (url === '/api/settings/units/') return Promise.resolve(['none', 'hour']);
      if (url === '/api/settings/') return Promise.resolve(mockSettings({ default_rate_scheme: '1' }));
      return Promise.resolve({ results: [] });
    });
    const { findByLabelText } = render(RateSchemeManager);
    const select = await findByLabelText('Default preset');
    expect(select.value).toBe('1');
  });

  it('default preset picker excludes inactive schemes even when "Show inactive" is checked', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/api/rate-schemes/?include_inactive=true') return Promise.resolve({ results: [SCHEME, INACTIVE_SCHEME] });
      if (url.startsWith('/api/rate-schemes/')) return Promise.resolve({ results: [SCHEME] });
      if (url === '/api/accounting-categories/') return Promise.resolve({ results: [{ id: 1, code: 'C1', name: 'Labor' }] });
      if (url === '/api/settings/units/') return Promise.resolve(['none', 'hour']);
      if (url === '/api/settings/') return Promise.resolve(mockSettings());
      return Promise.resolve({ results: [] });
    });
    const { findByRole, findByText, findByLabelText } = render(RateSchemeManager);
    await fireEvent.click(await findByRole('checkbox', { name: /Show inactive/ }));
    await findByText('Retired Rate'); // wait for the reload to land
    const select = await findByLabelText('Default preset');
    const optionLabels = Array.from(select.options).map((o) => o.textContent);
    expect(optionLabels).toContain('Hourly');
    expect(optionLabels).not.toContain('Retired Rate');
  });

  it('PATCHes settings with the new default when the picker selection changes', async () => {
    const { findByLabelText } = render(RateSchemeManager);
    const select = await findByLabelText('Default preset');
    await fireEvent.change(select, { target: { value: '1' } });
    expect(api.patch).toHaveBeenCalledWith('/api/settings/', { default_rate_scheme: '1' });
  });
});

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn() },
  errorMessage: (e) => e?.message || 'error',
}));
vi.mock('@/stores/setupStatus.js', () => ({
  refreshSetupStatus: vi.fn(),
  setupStatus: { subscribe: (fn) => { fn({ areas: null, last_pull_at: null }); return () => {}; } },
}));

import { api } from '@/lib/api.js';
import SchemesImportPanel from '@/components/qboimport/SchemesImportPanel.svelte';

const ROW = {
  qbo_item_id: '11', name: 'CNC Cutting', rate: '95.0',
  algorithm_default: 'entered_qty', unit_default: 'ea',
  category: null, price_group: '95.0', state: 'new',
};

beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();
});

function renderPanel(payload) {
  api.get.mockResolvedValue({ dismissed: false, fetched_at: 'x', ...payload });
  return render(SchemesImportPanel, { props: { unitsList: ['ea', 'hours'] } });
}

describe('SchemesImportPanel required-category indication', () => {
  it('shows the kAC dependency notice above the table when no categories exist', async () => {
    const { findByText, container } = renderPanel({
      rows: [ROW], category_options: [],
    });
    const note = await findByText(/no accounting categories exist yet/i);
    expect(note).toBeInTheDocument();
    // Notice renders before the table, not as a footnote after it.
    const panel = container.querySelector('.qbo-panel');
    const table = panel.querySelector('table');
    expect(note.closest('.dep-note').compareDocumentPosition(table)
           & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('marks a checked row with a blank category as missing', async () => {
    const { container, findByText } = renderPanel({
      rows: [ROW], category_options: [],
    });
    await findByText('CNC Cutting');
    const select = container.querySelector('select.missing');
    expect(select).not.toBeNull();
    // null category must map to the '— required —' option, not an
    // empty-looking select with nothing selected at all.
    expect(select.selectedIndex).toBe(0);
    expect(select.options[0].textContent).toMatch(/required/);
  });

  it('does not mark rows whose category resolved', async () => {
    const { container, findByText } = renderPanel({
      rows: [{ ...ROW, category: 5 }],
      category_options: [{ pk: 5, name: 'Service' }],
    });
    await findByText('CNC Cutting');
    expect(container.querySelector('select.missing')).toBeNull();
    expect(container.querySelector('.dep-note')).toBeNull();
  });
});

describe('SchemesImportPanel elapsed_time unit pinning', () => {
  it('pins and disables the row unit select to hour when its algorithm switches to elapsed time', async () => {
    const { container, findByText } = renderPanel({
      rows: [ROW], category_options: [{ pk: 5, name: 'Service' }],
    });
    await findByText('CNC Cutting');
    const row = container.querySelector('tbody tr');
    const [algoSelect, unitSelect] = row.querySelectorAll('select');

    // Starting state: entered_qty default, unit select enabled.
    expect(unitSelect).not.toBeDisabled();

    await fireEvent.change(algoSelect, { target: { value: 'elapsed_time' } });

    expect(unitSelect.value).toBe('hour');
    expect(unitSelect).toBeDisabled();
  });

  it('re-enables the unit select when switched back off elapsed_time', async () => {
    const { container, findByText } = renderPanel({
      rows: [ROW], category_options: [{ pk: 5, name: 'Service' }],
    });
    await findByText('CNC Cutting');
    const row = container.querySelector('tbody tr');
    const [algoSelect, unitSelect] = row.querySelectorAll('select');

    await fireEvent.change(algoSelect, { target: { value: 'elapsed_time' } });
    expect(unitSelect).toBeDisabled();

    await fireEvent.change(algoSelect, { target: { value: 'entered_qty' } });
    expect(unitSelect).not.toBeDisabled();
  });
});

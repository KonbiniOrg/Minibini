import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn() },
  errorMessage: (e) => e?.message || 'error',
}));
vi.mock('@/stores/setupStatus.js', () => ({
  refreshSetupStatus: vi.fn(),
  setupStatus: { subscribe: (fn) => { fn({ areas: null, last_pull_at: null }); return () => {}; } },
}));

import { api } from '@/lib/api.js';
import CatalogImportPanel from '@/components/qboimport/CatalogImportPanel.svelte';

const SERVICE = {
  qbo_id: '11', kind: 'service', name: 'CNC Cutting', description: '',
  rate: '95.0', rate_scheme_default: null, state: 'new',
};
const INVENTORY = {
  qbo_id: '12', kind: 'inventory', code_suggestion: 'Baltic Birch',
  description: '4x8', selling_price: '85.0', purchase_price: '52.5',
  category: null, state: 'new',
};

beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();
});

function renderPanel(payload) {
  api.get.mockResolvedValue({ dismissed: false, fetched_at: 'x', ...payload });
  return render(CatalogImportPanel, {});
}

describe('CatalogImportPanel required-binding indication', () => {
  it('shows dependency notices when schemes and categories are absent', async () => {
    const { findByText } = renderPanel({
      rows: [SERVICE, INVENTORY], category_options: [], scheme_options: [],
    });
    expect(await findByText(/no rate schemes exist yet/i)).toBeInTheDocument();
    expect(await findByText(/no accounting categories exist yet/i)).toBeInTheDocument();
  });

  it('marks unresolved scheme and category selects as missing', async () => {
    const { container, findByText } = renderPanel({
      rows: [SERVICE, INVENTORY], category_options: [], scheme_options: [],
    });
    await findByText('CNC Cutting');
    expect(container.querySelectorAll('select.missing').length).toBe(2);
  });

  it('does not mark resolved rows or changed services', async () => {
    const { container, findByText } = renderPanel({
      rows: [
        { ...SERVICE, state: 'changed' },
        { ...INVENTORY, category: 7 },
      ],
      category_options: [{ pk: 7, name: 'Material' }],
      scheme_options: [{ pk: 3, name: 'CNC' }],
    });
    await findByText('CNC Cutting');
    expect(container.querySelector('select.missing')).toBeNull();
    expect(container.querySelector('.dep-note')).toBeNull();
  });
});

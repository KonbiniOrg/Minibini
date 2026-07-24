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
import InventoryImportPanel from '@/components/qboimport/InventoryImportPanel.svelte';

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
  return render(InventoryImportPanel, {});
}

describe('InventoryImportPanel', () => {
  it('shows the category dependency notice when none exist', async () => {
    const { findByText } = renderPanel({
      rows: [INVENTORY], category_options: [],
    });
    expect(await findByText(/no accounting categories exist yet/i)).toBeInTheDocument();
  });

  it('marks an unresolved category select as missing', async () => {
    const { container, findByText } = renderPanel({
      rows: [INVENTORY], category_options: [],
    });
    await findByText('$85.0');
    const select = container.querySelector('select.missing');
    expect(select).not.toBeNull();
    expect(select.selectedIndex).toBe(0);
  });

  it('renders no select on imported rows and no notice when resolved', async () => {
    const { container, findByText } = renderPanel({
      rows: [{ ...INVENTORY, category: 7, state: 'imported' },
             { ...INVENTORY, qbo_id: '13', category: 7 }],
      category_options: [{ pk: 7, name: 'Material' }],
    });
    await findByText('Baltic Birch');
    expect(container.querySelectorAll('tbody select').length).toBe(1);
    expect(container.querySelector('select.missing')).toBeNull();
    expect(container.querySelector('.dep-note')).toBeNull();
  });
});

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
import ServiceItemsImportPanel from '@/components/qboimport/ServiceItemsImportPanel.svelte';

const SERVICE = {
  qbo_id: '11', kind: 'service', name: 'CNC Cutting', description: '',
  rate: '95.0', rate_scheme_default: null, state: 'new',
};

beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();
});

function renderPanel(payload) {
  api.get.mockResolvedValue({ dismissed: false, fetched_at: 'x', ...payload });
  return render(ServiceItemsImportPanel, {});
}

describe('ServiceItemsImportPanel', () => {
  it('shows the scheme dependency notice when none exist', async () => {
    const { findByText } = renderPanel({
      rows: [SERVICE], scheme_options: [],
    });
    expect(await findByText(/no rate schemes exist yet/i)).toBeInTheDocument();
  });

  it('marks an unresolved scheme select as missing', async () => {
    const { container, findByText } = renderPanel({
      rows: [SERVICE], scheme_options: [],
    });
    await findByText('CNC Cutting');
    const select = container.querySelector('select.missing');
    expect(select).not.toBeNull();
    expect(select.selectedIndex).toBe(0);
  });

  it('renders no select on changed rows and no notice when resolved', async () => {
    const { container, findByText } = renderPanel({
      rows: [{ ...SERVICE, state: 'changed' },
             { ...SERVICE, qbo_id: '15', name: 'Finishing',
               rate: '80.0', rate_scheme_default: 3 }],
      scheme_options: [{ pk: 3, name: 'CNC' }],
    });
    await findByText('Finishing');
    expect(container.querySelectorAll('tbody select').length).toBe(1);
    expect(container.querySelector('select.missing')).toBeNull();
    expect(container.querySelector('.dep-note')).toBeNull();
  });
});

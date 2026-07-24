// Smoke tests: each wrapper renders its rows and builds the right commit
// payload shape.
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
import CategoriesImportPanel from '@/components/qboimport/CategoriesImportPanel.svelte';
import ContactsImportPanel from '@/components/qboimport/ContactsImportPanel.svelte';
import TermsImportPanel from '@/components/qboimport/TermsImportPanel.svelte';

beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();
  api.post.mockResolvedValue({});
});

describe('CategoriesImportPanel', () => {
  it('renders candidates and commits edited payloads', async () => {
    api.get.mockResolvedValue({
      dismissed: false, fetched_at: 'x',
      expense_accounts: [{ qbo_id: '5000', name: 'COGS' }],
      rows: [{
        income_account: { qbo_id: '4000', name: 'Service Income' },
        member_count: 2,
        suggested: { name: 'Service Income', code: 'SI', taxable: true },
        fallback_item_options: [{ qbo_id: '11', name: 'CNC Cutting' }],
        fallback_item_default: '11',
        expense_account_default: '',
        state: 'new',
      }],
    });
    const { findByText, findByDisplayValue } = render(CategoriesImportPanel);
    expect(await findByText('Category suggestions from QuickBooks')).toBeInTheDocument();
    expect(await findByDisplayValue('Service Income')).toBeInTheDocument();
    await fireEvent.click(await findByText('Apply selected'));
    expect(api.post).toHaveBeenCalledWith('/api/qbo/import/commit/categories/', {
      rows: [{ name: 'Service Income', code: 'SI', taxable: true,
               qbo_item_id: '11', qbo_expense_account_id: '' }],
    });
  });
});

describe('ContactsImportPanel', () => {
  it('splits rows into customer/vendor payload lists (terms have their own panel)', async () => {
    api.get.mockResolvedValue({
      dismissed: false, fetched_at: 'x', missing_term_refs: false,
      rows: [
        { kind: 'customer', qbo_id: '71', display_name: 'Acme Corp',
          company_name: 'Acme Corp', email: 'jo@acme.com', state: 'changed' },
        { kind: 'vendor', qbo_id: '81', display_name: 'Moore Newton',
          company_name: 'Moore Newton', email: '', state: 'new',
          merge_hint: false },
      ],
    });
    const { findByText, queryByText } = render(ContactsImportPanel);
    expect(await findByText('Customers')).toBeInTheDocument();
    expect(await findByText('Vendors')).toBeInTheDocument();
    expect(queryByText('Payment terms')).toBeNull();
    await fireEvent.click(await findByText('Apply selected'));
    const payload = api.post.mock.calls.find(
      (c) => c[0] === '/api/qbo/import/commit/contacts/')[1];
    expect(payload.terms).toBeUndefined();
    expect(payload.customers[0].action).toBe('update');
    expect(payload.vendors[0].action).toBe('create');
  });

  it('reports skipped rows after a partial commit', async () => {
    api.get.mockResolvedValue({
      dismissed: false, fetched_at: 'x', missing_term_refs: false,
      rows: [
        { kind: 'customer', qbo_id: '71', display_name: 'Blah Company',
          company_name: 'Blah Company', email: 'x@blah.com', state: 'new' },
        { kind: 'customer', qbo_id: '72', display_name: 'Bulb Company',
          company_name: 'Bulb Company', email: 'x@blah.com', state: 'new' },
      ],
    });
    api.post.mockResolvedValue({
      customers: { created: 1, updated: 0, skipped: [
        { name: 'Bulb Company',
          reason: 'duplicate email with Blah Company' }] },
      vendors: { created: 0, updated: 0, skipped: [] },
    });
    const { findByText } = render(ContactsImportPanel);
    await fireEvent.click(await findByText('Apply selected'));
    expect(await findByText("1 contact couldn't be imported:"))
      .toBeInTheDocument();
    expect(await findByText('Bulb Company: duplicate email with Blah Company'))
      .toBeInTheDocument();
  });

  it('warns when customers reference unimported terms', async () => {
    api.get.mockResolvedValue({
      dismissed: false, fetched_at: 'x', missing_term_refs: true,
      rows: [{ kind: 'customer', qbo_id: '71', display_name: 'Acme Corp',
               company_name: 'Acme Corp', email: '', state: 'new' }],
    });
    const { findByText } = render(ContactsImportPanel);
    expect(await findByText(/import terms on Settings/i)).toBeInTheDocument();
  });
});

describe('TermsImportPanel', () => {
  it('renders term rows and commits with actions', async () => {
    api.get.mockResolvedValue({
      dismissed: false, fetched_at: 'x',
      rows: [
        { kind: 'term', qbo_id: '3', name: 'Net 30', due_days: 30, state: 'new' },
        { kind: 'term', qbo_id: '4', name: 'Net 60', due_days: 60, state: 'changed' },
      ],
    });
    const { findByText } = render(TermsImportPanel);
    expect(await findByText('Payment terms from QuickBooks')).toBeInTheDocument();
    expect(await findByText('Net 30')).toBeInTheDocument();
    await fireEvent.click(await findByText('Apply selected'));
    const payload = api.post.mock.calls.find(
      (c) => c[0] === '/api/qbo/import/commit/terms/')[1];
    expect(payload.rows.map((r) => r.action)).toEqual(['create', 'update']);
  });
});


describe('pull-button → panel reload wiring', () => {
  it('AccountingCategories keys its panel on pullEpoch (remount on pull)', async () => {
    // Wiring is identical across the four embeds; assert the pattern once
    // at the source level so a regression can't silently drop the {#key}.
    const fs = await import('fs');
    for (const path of [
      'src/components/settings/AccountingCategories.svelte',
      'src/components/RateSchemeManager.svelte',
      'src/routes/catalog/CatalogInventoryPage.svelte',
      'src/routes/contacts/ContactListPage.svelte',
    ]) {
      const src = fs.readFileSync(new URL('../../../' + path, import.meta.url), 'utf8');
      expect(src, path).toContain('onPulled={() => pullEpoch++}');
      expect(src, path).toContain('{#key pullEpoch}');
    }
  });
});

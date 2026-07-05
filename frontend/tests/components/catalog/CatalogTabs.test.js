import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import CatalogTabs from '@/components/CatalogTabs.svelte';

describe('CatalogTabs', () => {
  it('renders the three tab links with their routes', () => {
    const { getByRole } = render(CatalogTabs);
    expect(getByRole('link', { name: 'Inventory' }).getAttribute('href'))
      .toContain('/catalog');
    expect(getByRole('link', { name: 'Service Items' }).getAttribute('href'))
      .toContain('/catalog/service-items');
    expect(getByRole('link', { name: 'Earmarks' }).getAttribute('href'))
      .toContain('/catalog/earmarks');
  });

  it('renders the area heading', () => {
    const { getByRole } = render(CatalogTabs);
    expect(getByRole('heading', { name: 'Catalog' })).toBeTruthy();
  });
});

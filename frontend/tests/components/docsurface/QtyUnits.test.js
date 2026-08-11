import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import QtyUnits from '@/components/docsurface/QtyUnits.svelte';

describe('QtyUnits', () => {
  it('stacks units beneath the qty in muted small text', () => {
    const { container } = render(QtyUnits, { props: { qty: '2.00', units: 'hour' } });
    expect(container.textContent).toContain('2.00');
    const under = container.querySelector('small.qty-units-under');
    expect(under).toBeTruthy();
    expect(under.textContent).toBe('hour');
  });

  it("omits units entirely when units is 'none'", () => {
    const { container } = render(QtyUnits, { props: { qty: '2.00', units: 'none' } });
    expect(container.textContent.trim()).toBe('2.00');
    expect(container.querySelector('.qty-units-under')).toBeNull();
  });

  it('omits units when units is empty/null', () => {
    const { container } = render(QtyUnits, { props: { qty: '5', units: '' } });
    expect(container.querySelector('.qty-units-under')).toBeNull();
    const { container: c2 } = render(QtyUnits, { props: { qty: '5', units: null } });
    expect(c2.querySelector('.qty-units-under')).toBeNull();
  });

  it("renders '-' for a missing qty (mirrors formatQtyUnits)", () => {
    for (const qty of [null, undefined, '']) {
      const { container } = render(QtyUnits, { props: { qty, units: 'ea' } });
      expect(container.textContent.trim()).toBe('-');
    }
  });
});

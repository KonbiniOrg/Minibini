import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import QtyUnits from '@/components/docsurface/QtyUnits.svelte';

describe('QtyUnits', () => {
  it('renders qty and units inline (wraps naturally when squeezed — no forced line break)', () => {
    const { container } = render(QtyUnits, { props: { qty: '2.00', units: 'hour' } });
    expect(container.textContent.trim()).toBe('2.00 hour');
    expect(container.querySelector('br')).toBeNull();
  });

  it("omits units entirely when units is 'none'", () => {
    const { container } = render(QtyUnits, { props: { qty: '2.00', units: 'none' } });
    expect(container.textContent.trim()).toBe('2.00');
  });

  it('omits units when units is empty/null', () => {
    const { container } = render(QtyUnits, { props: { qty: '5', units: '' } });
    expect(container.textContent.trim()).toBe('5');
    const { container: c2 } = render(QtyUnits, { props: { qty: '5', units: null } });
    expect(c2.textContent.trim()).toBe('5');
  });

  it("renders '-' for a missing qty (mirrors formatQtyUnits)", () => {
    for (const qty of [null, undefined, '']) {
      const { container } = render(QtyUnits, { props: { qty, units: 'ea' } });
      expect(container.textContent.trim()).toBe('-');
    }
  });
});

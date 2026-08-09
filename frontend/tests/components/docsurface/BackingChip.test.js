import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import BackingChip from '@/components/docsurface/BackingChip.svelte';

describe('BackingChip', () => {
  it('renders nothing when backing is null', () => {
    const { container } = render(BackingChip, {
      props: { backing: null },
    });
    expect(container.querySelector('.backing-chip')).toBeNull();
  });

  it('renders nothing when backing is undefined', () => {
    const { container } = render(BackingChip, {
      props: { backing: undefined },
    });
    expect(container.querySelector('.backing-chip')).toBeNull();
  });

  it('renders "estimate" for backing="estimate"', () => {
    const { getByText } = render(BackingChip, {
      props: { backing: 'estimate' },
    });
    getByText('estimate');
  });

  it('renders "actuals" for backing="actuals" when not synced', () => {
    const { getByText } = render(BackingChip, {
      props: { backing: 'actuals', syncedWithEstimate: false },
    });
    getByText('actuals');
  });

  it('renders "actuals = estimate ✓" with synced class when backing="actuals" and syncedWithEstimate=true', () => {
    const { container, getByText } = render(BackingChip, {
      props: { backing: 'actuals', syncedWithEstimate: true },
    });
    getByText('actuals = estimate ✓');
    const chip = container.querySelector('.backing-chip');
    expect(chip.classList.contains('synced')).toBe(true);
  });

  it('renders "edited" for backing="edited"', () => {
    const { getByText } = render(BackingChip, {
      props: { backing: 'edited' },
    });
    getByText('edited');
  });

  it('renders "deposit" for backing="deposit"', () => {
    const { getByText } = render(BackingChip, {
      props: { backing: 'deposit' },
    });
    getByText('deposit');
  });

  it('renders "deposit credit" for backing="deposit_credit"', () => {
    const { getByText } = render(BackingChip, {
      props: { backing: 'deposit_credit' },
    });
    getByText('deposit credit');
  });

  it('renders "planned work" for backing="planned_work"', () => {
    const { getByText } = render(BackingChip, {
      props: { backing: 'planned_work' },
    });
    getByText('planned work');
  });

  it('renders "planned materials" for backing="planned_materials"', () => {
    const { getByText } = render(BackingChip, {
      props: { backing: 'planned_materials' },
    });
    getByText('planned materials');
  });

  it('renders "from catalog" for backing="from_catalog"', () => {
    const { getByText } = render(BackingChip, {
      props: { backing: 'from_catalog' },
    });
    getByText('from catalog');
  });

  it('renders "hand line" for backing="hand"', () => {
    const { getByText } = render(BackingChip, {
      props: { backing: 'hand' },
    });
    getByText('hand line');
  });

  it('renders "adjustment" for backing="adjustment"', () => {
    const { getByText } = render(BackingChip, {
      props: { backing: 'adjustment' },
    });
    getByText('adjustment');
  });

  it('applies correct CSS class for actuals', () => {
    const { container } = render(BackingChip, {
      props: { backing: 'actuals' },
    });
    const chip = container.querySelector('.backing-chip');
    expect(chip.classList.contains('actuals')).toBe(true);
  });

  it('applies correct CSS class for planned_work', () => {
    const { container } = render(BackingChip, {
      props: { backing: 'planned_work' },
    });
    const chip = container.querySelector('.backing-chip');
    expect(chip.classList.contains('planned')).toBe(true);
  });

  it('applies correct CSS class for planned_materials', () => {
    const { container } = render(BackingChip, {
      props: { backing: 'planned_materials' },
    });
    const chip = container.querySelector('.backing-chip');
    expect(chip.classList.contains('planned')).toBe(true);
  });

  it('applies correct CSS class for from_catalog', () => {
    const { container } = render(BackingChip, {
      props: { backing: 'from_catalog' },
    });
    const chip = container.querySelector('.backing-chip');
    expect(chip.classList.contains('catalog')).toBe(true);
  });

  it('applies correct CSS class for deposit', () => {
    const { container } = render(BackingChip, {
      props: { backing: 'deposit' },
    });
    const chip = container.querySelector('.backing-chip');
    expect(chip.classList.contains('deposit')).toBe(true);
  });

  it('applies correct CSS class for edited', () => {
    const { container } = render(BackingChip, {
      props: { backing: 'edited' },
    });
    const chip = container.querySelector('.backing-chip');
    expect(chip.classList.contains('edited')).toBe(true);
  });

  it('applies no accent class for estimate, hand, adjustment, deposit_credit', () => {
    ['estimate', 'hand', 'adjustment', 'deposit_credit'].forEach((backing) => {
      const { container } = render(BackingChip, {
        props: { backing },
      });
      const chip = container.querySelector('.backing-chip');
      expect(chip.classList.contains('actuals')).toBe(false);
      expect(chip.classList.contains('planned')).toBe(false);
      expect(chip.classList.contains('catalog')).toBe(false);
      expect(chip.classList.contains('deposit')).toBe(false);
      expect(chip.classList.contains('edited')).toBe(false);
    });
  });
});

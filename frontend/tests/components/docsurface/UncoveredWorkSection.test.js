import { describe, it, expect, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import UncoveredWorkSection from '@/components/docsurface/UncoveredWorkSection.svelte';
import UncoveredWorkSectionHarness from './_UncoveredWorkSectionHarness.svelte';

const rows = [
  { id: 1, kind: 'task', description: 'Cut parts', qty_display: '3 hr', rate: 25, amount: 75 },
  { id: 2, kind: 'mat', description: 'Acrylic sheet', qty_display: '2 ea', rate: 10, amount: 20 },
  {
    id: 3, kind: 'task', description: 'Finish pass', qty_display: '1 hr', rate: 25, amount: 25,
    selectable: false, unselectableNote: 'billable when complete',
  },
];

describe('UncoveredWorkSection', () => {
  it('renders title, subtitle, and each row', () => {
    const { getByText } = render(UncoveredWorkSection, {
      props: { title: 'Uncovered work', subtitle: 'From completed tasks', rows },
    });
    getByText('Uncovered work');
    getByText('From completed tasks');
    getByText('Cut parts');
    getByText('Acrylic sheet');
    getByText('Finish pass');
  });

  it('renders no subtitle paragraph when subtitle is empty (default)', () => {
    const { container } = render(UncoveredWorkSection, {
      props: { title: 'Uncovered work', rows: [] },
    });
    expect(container.querySelector('p')).toBeNull();
  });

  it('shows emptyText when rows is empty', () => {
    const { getByText } = render(UncoveredWorkSection, {
      props: { title: 'Uncovered work', rows: [], emptyText: 'Nothing uncovered yet.' },
    });
    getByText('Nothing uncovered yet.');
  });

  it('dims unselectable rows: disabled checkbox and rendered unselectableNote', () => {
    const { getByText, container } = render(UncoveredWorkSection, {
      props: { title: 'x', rows },
    });
    getByText(/billable when complete/);
    const checkboxes = container.querySelectorAll('input[type="checkbox"]');
    expect(checkboxes).toHaveLength(3);
    expect(checkboxes[2].disabled).toBe(true);
    expect(checkboxes[0].disabled).toBe(false);
  });

  it('never renders a direct button when onDirect is not wired (A3)', () => {
    const { container } = render(UncoveredWorkSection, { props: { title: 'x', rows } });
    expect(container.querySelector('button')).toBeNull();
  });

  it('renders a direct button per selectable row when onDirect is wired, using directLabel', () => {
    const onDirect = vi.fn();
    const { getAllByText, queryAllByText } = render(UncoveredWorkSection, {
      props: { title: 'x', rows, onDirect, directLabel: 'Bill separately' },
    });
    // only the two selectable rows get a direct button; the unselectable
    // row does not.
    expect(getAllByText('Bill separately')).toHaveLength(2);
    expect(queryAllByText('Bill as its own line')).toHaveLength(0);
  });

  it('defaults directLabel to "Bill as its own line"', () => {
    const onDirect = vi.fn();
    const { getAllByText } = render(UncoveredWorkSection, {
      props: { title: 'x', rows, onDirect },
    });
    expect(getAllByText('Bill as its own line')).toHaveLength(2);
  });

  it('calls onDirect with the row id when its direct button is clicked', async () => {
    const onDirect = vi.fn();
    const { getAllByText } = render(UncoveredWorkSection, {
      props: { title: 'x', rows, onDirect },
    });
    await fireEvent.click(getAllByText('Bill as its own line')[0]);
    expect(onDirect).toHaveBeenCalledWith(1);
  });

  it('renders the optional chip as a backing-chip span', () => {
    const { container } = render(UncoveredWorkSection, {
      props: {
        title: 'x',
        rows: [{ ...rows[0], chip: { label: 'from catalog', cls: 'catalog' } }],
      },
    });
    const chip = container.querySelector('.backing-chip');
    expect(chip).not.toBeNull();
    expect(chip.textContent).toBe('from catalog');
    expect(chip.classList.contains('catalog')).toBe(true);
  });

  it('hides a row\'s direct button once that row is selected', async () => {
    const onDirect = vi.fn();
    const { container, getAllByText, queryAllByText } = render(UncoveredWorkSection, {
      props: { title: 'x', rows, onDirect },
    });
    expect(getAllByText('Bill as its own line')).toHaveLength(2);
    const checkboxes = container.querySelectorAll('input[type="checkbox"]');
    await fireEvent.click(checkboxes[0]);
    expect(queryAllByText('Bill as its own line')).toHaveLength(1);
  });

  it('binds checked selections into the selected array (two-way)', async () => {
    const { getByTestId, container } = render(UncoveredWorkSectionHarness, {
      props: { rows },
    });
    expect(getByTestId('selected').textContent).toBe('[]');
    const checkboxes = container.querySelectorAll('input[type="checkbox"]');
    await fireEvent.click(checkboxes[0]);
    expect(getByTestId('selected').textContent).toBe('[1]');
    await fireEvent.click(checkboxes[1]);
    expect(getByTestId('selected').textContent).toBe('[1,2]');
    await fireEvent.click(checkboxes[0]);
    expect(getByTestId('selected').textContent).toBe('[2]');
  });
});

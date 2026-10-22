// SortableList (issue #513): the reusable drag-and-drop list behind every
// reorderable list. The drop → new-order step is lib/dragOrder.js (tested
// there); dnd-kit's pointer/keyboard gestures are covered end to end by
// e2e/specs/job-overview/task-drag-reorder.spec.js.
import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import Harness from './_SortableListHarness.svelte';

const items = [{ id: 1, name: 'A' }, { id: 2, name: 'B' }, { id: 3, name: 'C' }];

describe('SortableList', () => {
  it('renders every item through the snippet, in order, with its index', () => {
    const { container } = render(Harness, { props: { items } });
    const lis = Array.from(container.querySelectorAll('li'));
    expect(lis.map((li) => li.dataset.id)).toEqual(['1', '2', '3']);
    expect(lis.map((li) => li.dataset.index)).toEqual(['0', '1', '2']);
  });

  it('hands each item a drag handle ref when enabled', () => {
    const { getAllByRole } = render(Harness, { props: { items } });
    expect(getAllByRole('button', { name: /^Drag / })).toHaveLength(3);
  });

  it('hands no drag handle when disabled', () => {
    const { queryByRole } = render(Harness, { props: { items, disabled: true } });
    expect(queryByRole('button', { name: /^Drag / })).toBeNull();
  });

  it('follows new items from the caller', async () => {
    const { container, rerender } = render(Harness, { props: { items } });
    await rerender({ items: [items[2], items[0], items[1]] });
    const ids = Array.from(container.querySelectorAll('li')).map((li) => li.dataset.id);
    expect(ids).toEqual(['3', '1', '2']);
  });
});

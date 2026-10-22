import { describe, it, expect } from 'vitest';
import { nextOrder } from '@/lib/dragOrder.js';

// nextOrder turns a drag-end event into the list's new id order, or null
// when the drop changes nothing (issue #513: drag-and-drop row reorder).

const ev = (sourceId, targetId, extra = {}) => ({
  operation: { source: { id: sourceId, ...extra }, target: { id: targetId }, canceled: false },
});

describe('nextOrder', () => {
  it('moves an item several places at once', () => {
    expect(nextOrder([1, 2, 3, 4], ev(4, 1))).toEqual([4, 1, 2, 3]);
    expect(nextOrder([1, 2, 3, 4], ev(1, 3))).toEqual([2, 3, 1, 4]);
  });

  it('follows the projected sortable index when the library supplies one', () => {
    expect(nextOrder([1, 2, 3, 4], ev(1, 2, { index: 3 }))).toEqual([2, 3, 4, 1]);
  });

  it('returns null when dropped where it started', () => {
    expect(nextOrder([1, 2, 3], ev(2, 2))).toBeNull();
  });

  it('returns null for a cancelled drag or a drop outside the list', () => {
    expect(nextOrder([1, 2, 3], {
      operation: { source: { id: 1 }, target: { id: 3 }, canceled: true },
    })).toBeNull();
    expect(nextOrder([1, 2, 3], { operation: { source: { id: 1 }, target: null } })).toBeNull();
  });

  it('does not mutate the ids it was given', () => {
    const ids = [1, 2, 3];
    nextOrder(ids, ev(3, 1));
    expect(ids).toEqual([1, 2, 3]);
  });
});

// Drag-and-drop row reorder (issue #513): turn a dnd-kit drag-end event into
// the list's new id order. Returns null when the drop changes nothing
// (cancelled, dropped outside the list, or back where it started), so the
// caller only saves a real move.
import { move } from '@dnd-kit/helpers';

export function nextOrder(ids, event) {
  const next = move([...ids], event);
  if (next.length !== ids.length || next.every((id, i) => id === ids[i])) return null;
  return next;
}

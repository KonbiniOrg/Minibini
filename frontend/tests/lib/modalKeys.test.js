import { describe, it, expect, vi, afterEach } from 'vitest';
import { modalKeys } from '@/lib/modalKeys.js';

// modalKeys is a Svelte action: it attaches a window keydown listener and
// returns { update, destroy }. We attach it to a real node and dispatch
// bubbling keydown events so e.target reflects the focused element.
function attach(opts) {
  const node = document.createElement('div');
  document.body.appendChild(node);
  return modalKeys(node, opts);
}

function dispatchEnterFrom(el) {
  el.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
}

afterEach(() => {
  document.body.innerHTML = '';
});

describe('modalKeys', () => {
  it('calls onCancel on Escape', () => {
    const onCancel = vi.fn();
    const action = attach({ onCancel });
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    expect(onCancel).toHaveBeenCalledTimes(1);
    action.destroy();
  });

  it('calls onSave on Enter from an ordinary element', () => {
    const onSave = vi.fn();
    const action = attach({ onSave });
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));
    expect(onSave).toHaveBeenCalledTimes(1);
    action.destroy();
  });

  it('ignores Enter inside a textarea', () => {
    const onSave = vi.fn();
    const action = attach({ onSave });
    const ta = document.createElement('textarea');
    document.body.appendChild(ta);
    dispatchEnterFrom(ta);
    expect(onSave).not.toHaveBeenCalled();
    action.destroy();
  });

  it('ignores Enter on a button', () => {
    const onSave = vi.fn();
    const action = attach({ onSave });
    const btn = document.createElement('button');
    document.body.appendChild(btn);
    dispatchEnterFrom(btn);
    expect(onSave).not.toHaveBeenCalled();
    action.destroy();
  });

  it('leaves Enter alone when onSave is omitted', () => {
    const onCancel = vi.fn();
    const action = attach({ onCancel });
    expect(() =>
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' })),
    ).not.toThrow();
    action.destroy();
  });

  it('removes its listener on destroy', () => {
    const onCancel = vi.fn();
    const action = attach({ onCancel });
    action.destroy();
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    expect(onCancel).not.toHaveBeenCalled();
  });
});

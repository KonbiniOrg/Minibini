import { describe, it, expect, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import { createRawSnippet } from 'svelte';
import Modal from '@/components/Modal.svelte';

const content = createRawSnippet(() => ({
  render: () => '<p>modal body</p>',
}));

describe('Modal shell', () => {
  it('renders nothing when closed', () => {
    const { queryByText } = render(Modal, {
      props: { open: false, children: content },
    });
    expect(queryByText('modal body')).toBeNull();
  });

  it('renders its children when open', () => {
    const { getByText } = render(Modal, {
      props: { open: true, children: content },
    });
    expect(getByText('modal body')).toBeInTheDocument();
  });

  it('Escape fires onCancel', async () => {
    const onCancel = vi.fn();
    render(Modal, { props: { open: true, onCancel, children: content } });
    await fireEvent.keyDown(window, { key: 'Escape' });
    expect(onCancel).toHaveBeenCalled();
  });

  it('Enter fires onSave when provided', async () => {
    const onSave = vi.fn();
    render(Modal, { props: { open: true, onSave, children: content } });
    await fireEvent.keyDown(window, { key: 'Enter' });
    expect(onSave).toHaveBeenCalled();
  });

  it('suppresses Enter while busy (the shell owns the busy-guard)', async () => {
    const onSave = vi.fn();
    render(Modal, { props: { open: true, onSave, busy: true, children: content } });
    await fireEvent.keyDown(window, { key: 'Enter' });
    expect(onSave).not.toHaveBeenCalled();
  });

  it('drags via the grab bar and resets when reopened', async () => {
    const { container, rerender } = render(Modal, {
      props: { open: true, children: content },
    });
    const bar = container.querySelector('.grab-bar');
    const box = container.querySelector('.modal');
    await fireEvent.pointerDown(bar, { clientX: 10, clientY: 10 });
    await fireEvent.pointerMove(bar, { clientX: 60, clientY: 40 });
    await fireEvent.pointerUp(bar);
    expect(box.style.transform).toBe('translate(50px, 30px)');
    // Reopen: position resets so a modal never inherits its predecessor's spot.
    await rerender({ open: false, children: content });
    await rerender({ open: true, children: content });
    expect(container.querySelector('.modal').style.transform).toBe('translate(0px, 0px)');
  });

  it('applies the maxWidth knob', () => {
    const { container } = render(Modal, {
      props: { open: true, maxWidth: '420px', children: content },
    });
    expect(container.querySelector('.modal').style.maxWidth).toBe('420px');
  });
});

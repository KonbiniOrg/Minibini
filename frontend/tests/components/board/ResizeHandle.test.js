import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import ResizeHandle from '@/components/board/ResizeHandle.svelte';

afterEach(() => {
  document.body.style.cursor = '';
  document.body.style.userSelect = '';
});

describe('ResizeHandle', () => {
  it('reports incremental deltas while dragging (vertical → clientX)', async () => {
    const onResize = vi.fn();
    const { getByRole } = render(ResizeHandle, { props: { direction: 'vertical', onResize } });

    await fireEvent.mouseDown(getByRole('separator'), { clientX: 100 });
    expect(document.body.style.cursor).toBe('col-resize');

    await fireEvent.mouseMove(window, { clientX: 130 });
    expect(onResize).toHaveBeenLastCalledWith(30);

    await fireEvent.mouseMove(window, { clientX: 140 });
    expect(onResize).toHaveBeenLastCalledWith(10); // relative to the new start

    await fireEvent.mouseUp(window);
    expect(document.body.style.cursor).toBe('');

    onResize.mockClear();
    await fireEvent.mouseMove(window, { clientX: 300 });
    expect(onResize).not.toHaveBeenCalled(); // listener removed on mouseup
  });

  it('uses clientY for a horizontal handle', async () => {
    const onResize = vi.fn();
    const { getByRole } = render(ResizeHandle, { props: { direction: 'horizontal', onResize } });

    await fireEvent.mouseDown(getByRole('separator'), { clientY: 50 });
    expect(document.body.style.cursor).toBe('row-resize');
    await fireEvent.mouseMove(window, { clientY: 80 });
    expect(onResize).toHaveBeenLastCalledWith(30);
    await fireEvent.mouseUp(window);
  });
});

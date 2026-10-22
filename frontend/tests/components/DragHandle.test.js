import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import DragHandle from '@/components/DragHandle.svelte';

// The row drag handle (issue #513): a button whose accessible name says what
// it moves.

describe('DragHandle', () => {
  it('is a button named for the row it moves', () => {
    const { getByRole } = render(DragHandle, { label: 'Drag to reorder Cut' });
    expect(getByRole('button', { name: 'Drag to reorder Cut' })).toHaveAttribute('type', 'button');
  });

  it('falls back to a generic name', () => {
    const { getByRole } = render(DragHandle);
    expect(getByRole('button', { name: 'Drag to reorder' })).toBeInTheDocument();
  });
});

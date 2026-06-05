import { describe, it, expect, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import CollapsedTab from '@/components/board/CollapsedTab.svelte';

describe('CollapsedTab', () => {
  it('fires onclick when clicked', async () => {
    const onclick = vi.fn();
    const { getByRole } = render(CollapsedTab, {
      props: { label: 'Pipeline', theme: 'pipeline', onclick },
    });
    await fireEvent.click(getByRole('button'));
    expect(onclick).toHaveBeenCalled();
  });

  it('fires onclick on Enter', async () => {
    const onclick = vi.fn();
    const { getByRole } = render(CollapsedTab, {
      props: { label: 'Pipeline', theme: 'pipeline', onclick },
    });
    await fireEvent.keyDown(getByRole('button'), { key: 'Enter' });
    expect(onclick).toHaveBeenCalled();
  });

  it('shows the count when one is given (including zero)', () => {
    const { getByText } = render(CollapsedTab, {
      props: { label: 'Closed', theme: 'closed', count: 0 },
    });
    expect(getByText('0')).toBeInTheDocument();
  });
});

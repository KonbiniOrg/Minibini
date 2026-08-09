import { describe, it, expect, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import NewLineFromSelectedRow from '@/components/docsurface/NewLineFromSelectedRow.svelte';

describe('NewLineFromSelectedRow', () => {
  it('renders nothing when visible is false (default)', () => {
    const { container } = render(NewLineFromSelectedRow, {
      props: { onCreate: () => {} },
    });
    expect(container.querySelector('tr')).toBeNull();
  });

  it('renders the doc-newline placeholder row with cta text when visible', () => {
    const { container, getByText } = render(NewLineFromSelectedRow, {
      props: { visible: true, nextNumber: '6', onCreate: () => {} },
    });
    expect(container.querySelector('tr.doc-newline')).not.toBeNull();
    getByText(/New line from selected/);
    getByText(/6/);
  });

  it('calls onCreate when Create line is clicked', async () => {
    const onCreate = vi.fn();
    const { getByText } = render(NewLineFromSelectedRow, {
      props: { visible: true, onCreate },
    });
    await fireEvent.click(getByText('Create line'));
    expect(onCreate).toHaveBeenCalledTimes(1);
  });
});

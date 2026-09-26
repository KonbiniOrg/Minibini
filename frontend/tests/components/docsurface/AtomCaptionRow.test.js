import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import AtomCaptionRow from '@/components/docsurface/AtomCaptionRow.svelte';

function renderCaption(props = {}) {
  return render(AtomCaptionRow, { props });
}

describe('AtomCaptionRow', () => {
  it('renders nothing when the line has no sources', () => {
    const { container } = renderCaption({ sources: [] });
    expect(container.querySelector('tr.doc-atom-caption')).toBeNull();
  });

  it('labels a single-kind group with the kind noun, singular and plural', () => {
    const one = renderCaption({ sources: [{ source_type: 'task' }] });
    one.getByText('based on 1 task:');

    const many = renderCaption({
      sources: [{ source_type: 'material' }, { source_type: 'material' }],
    });
    many.getByText('based on 2 materials:');
  });

  it('falls back to "items" for mixed or unknown kinds', () => {
    const mixed = renderCaption({
      sources: [{ source_type: 'task' }, { source_type: 'expense' }],
    });
    mixed.getByText('based on 2 items:');

    const unknown = renderCaption({ sources: [{ source_type: 'widget' }] });
    unknown.getByText('based on 1 item:');
  });

  it('pads colspanBefore empty cells and spans the caption cell', () => {
    const { container } = renderCaption({
      sources: [{ source_type: 'task' }],
      colspanBefore: 1,
      colspan: 6,
    });
    const cells = container.querySelectorAll('tr.doc-atom-caption td');
    expect(cells).toHaveLength(2);
    expect(cells[0].textContent).toBe('');
    expect(cells[1].getAttribute('colspan')).toBe('6');
  });
});

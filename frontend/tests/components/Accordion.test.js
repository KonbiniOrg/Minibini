import { describe, it, expect } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import AccordionHarness from './_AccordionHarness.svelte';

// Accordion's open/closed state is reflected by an `open` CSS class on the
// content panel (the children are always in the DOM; CSS shows/hides them), so
// we assert on that class rather than on presence/absence of the child markup.
function panel(container) {
  return container.querySelector('.accordion-content');
}

describe('Accordion', () => {
  it('is closed by default', () => {
    const { container } = render(AccordionHarness);
    expect(panel(container)).not.toHaveClass('open');
  });

  it('honors an initial open=true prop', () => {
    const { container } = render(AccordionHarness, { props: { open: true } });
    expect(panel(container)).toHaveClass('open');
  });

  it('toggles open then closed on header click', async () => {
    const { container, getByRole } = render(AccordionHarness);
    const header = getByRole('button');

    await fireEvent.click(header);
    expect(panel(container)).toHaveClass('open');

    await fireEvent.click(header);
    expect(panel(container)).not.toHaveClass('open');
  });

  it('opens on Enter key', async () => {
    const { container, getByRole } = render(AccordionHarness);
    await fireEvent.keyDown(getByRole('button'), { key: 'Enter' });
    expect(panel(container)).toHaveClass('open');
  });
});

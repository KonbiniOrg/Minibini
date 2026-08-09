import { describe, it, expect } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import DocModeBar from '@/components/docsurface/DocModeBar.svelte';

describe('DocModeBar', () => {
  it('renders three buttons with default modes', () => {
    const { container } = render(DocModeBar, {
      props: { mode: 'edit', onMode: () => {} },
    });
    const buttons = container.querySelectorAll('button');
    expect(buttons).toHaveLength(3);
    expect(buttons[0].textContent.trim()).toBe('Edit');
    expect(buttons[1].textContent.trim()).toBe('Customer');
    expect(buttons[2].textContent.trim()).toBe('Reorder');
  });

  it('labels the band "Views"', () => {
    const { getByText } = render(DocModeBar, {
      props: { mode: 'edit', onMode: () => {} },
    });
    expect(getByText('Views')).toBeInTheDocument();
  });

  it('sets aria-pressed="true" on active button', () => {
    const { container } = render(DocModeBar, {
      props: { mode: 'customer', onMode: () => {} },
    });
    const buttons = container.querySelectorAll('button');
    expect(buttons[0].getAttribute('aria-pressed')).toBe('false');
    expect(buttons[1].getAttribute('aria-pressed')).toBe('true');
    expect(buttons[2].getAttribute('aria-pressed')).toBe('false');
  });

  it('fires onMode callback when button clicked', async () => {
    let lastMode = null;
    const onMode = (m) => { lastMode = m; };
    const { container } = render(DocModeBar, {
      props: { mode: 'edit', onMode },
    });
    const buttons = container.querySelectorAll('button');
    await fireEvent.click(buttons[1]); // click 'customer' button
    expect(lastMode).toBe('customer');
  });

  it('respects custom modes and labels', () => {
    const { container } = render(DocModeBar, {
      props: {
        mode: 'alpha',
        onMode: () => {},
        modes: ['alpha', 'beta'],
        labels: { alpha: 'Alpha Label', beta: 'Beta Label' },
      },
    });
    const buttons = container.querySelectorAll('button');
    expect(buttons).toHaveLength(2);
    expect(buttons[0].textContent.trim()).toBe('Alpha Label');
    expect(buttons[1].textContent.trim()).toBe('Beta Label');
    expect(buttons[0].getAttribute('aria-pressed')).toBe('true');
  });
});

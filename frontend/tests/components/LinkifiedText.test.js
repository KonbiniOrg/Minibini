import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import LinkifiedText from '@/components/LinkifiedText.svelte';

describe('LinkifiedText', () => {
  it('renders a url as an anchor with the full href', () => {
    const { getByRole } = render(LinkifiedText, {
      props: { text: 'see https://example.com/x now' },
    });
    const link = getByRole('link');
    expect(link).toHaveAttribute('href', 'https://example.com/x');
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveTextContent('example.com/x');
  });

  it('keeps the surrounding plain text', () => {
    const { container } = render(LinkifiedText, {
      props: { text: 'see https://example.com/x now' },
    });
    expect(container).toHaveTextContent('see');
    expect(container).toHaveTextContent('now');
  });

  it('renders plain text with no anchor when there is no url', () => {
    const { container } = render(LinkifiedText, {
      props: { text: 'just some words' },
    });
    expect(container.querySelector('a')).toBeNull();
    expect(container).toHaveTextContent('just some words');
  });
});

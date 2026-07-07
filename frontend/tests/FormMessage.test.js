import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import FormMessage from '@/components/FormMessage.svelte';

describe('FormMessage', () => {
  it('renders an error with role=alert', () => {
    const { getByRole } = render(FormMessage, { props: { error: 'Job is on hold.' } });
    expect(getByRole('alert').textContent).toContain('Job is on hold.');
  });

  it('renders success when there is no error', () => {
    const { getByText, container } = render(FormMessage, { props: { success: 'Saved.' } });
    getByText('Saved.');
    expect(container.querySelector('.error')).toBeNull();
  });

  it('error wins when both are set (stale success must not linger)', () => {
    const { getByRole, queryByText } = render(FormMessage, {
      props: { error: 'Nope.', success: 'Saved.' },
    });
    expect(getByRole('alert').textContent).toContain('Nope.');
    expect(queryByText('Saved.')).toBeNull();
  });

  it('renders nothing when idle', () => {
    const { container } = render(FormMessage, {});
    expect(container.querySelector('.form-message')).toBeNull();
  });
});

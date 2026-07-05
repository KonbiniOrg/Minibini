import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import FieldError from '@/components/FieldError.svelte';

describe('FieldError', () => {
  it('renders every message for its field', () => {
    const { getByText } = render(FieldError, {
      props: { errors: { rate: ['Must be positive.', 'Too precise.'] }, field: 'rate' },
    });
    getByText('Must be positive.');
    getByText('Too precise.');
  });

  it('renders nothing when its field is absent from the bag', () => {
    const { container } = render(FieldError, {
      props: { errors: { other: ['x'] }, field: 'rate' },
    });
    expect(container.querySelector('.field-error')).toBeNull();
  });

  it('tolerates a bare-string value (not wrapped in an array)', () => {
    const { getByText } = render(FieldError, {
      props: { errors: { rate: 'Must be positive.' }, field: 'rate' },
    });
    getByText('Must be positive.');
  });
});

import { describe, it, expect } from 'vitest';
import { render, fireEvent, within } from '@testing-library/svelte';
import Harness from './_PhoneListEditorHarness.svelte';

describe('PhoneListEditor', () => {
  it('renders one row per entry, marks the first as primary, adds and removes rows', async () => {
    const { container, getByRole, queryByText } = render(Harness, {
      props: { phones: [{ number: '555-0100', label: 'cell' }, { number: '555-0200', label: 'work' }] },
    });
    const rows = () => container.querySelectorAll('.phone-row');
    expect(rows()).toHaveLength(2);
    expect(within(rows()[0]).getByText('primary')).toBeInTheDocument();
    expect(within(rows()[1]).queryByText('primary')).toBeNull();
    await fireEvent.click(getByRole('button', { name: 'Add phone' }));
    expect(rows()).toHaveLength(3);
    await fireEvent.click(within(rows()[2]).getByRole('button', { name: 'Remove phone 3' }));
    expect(rows()).toHaveLength(2);
    expect(queryByText('No phone numbers')).toBeNull();
  });

  it('move up promotes a row to primary and the bound list reorders', async () => {
    const { container } = render(Harness, {
      props: { phones: [{ number: '1', label: 'a' }, { number: '2', label: 'b' }] },
    });
    const rows = () => container.querySelectorAll('.phone-row');
    expect(within(rows()[0]).queryByRole('button', { name: /Move phone 1 up/ })).toBeNull();
    await fireEvent.click(within(rows()[1]).getByRole('button', { name: 'Move phone 2 up' }));
    expect(within(rows()[0]).getByDisplayValue('2')).toBeInTheDocument();
    expect(container.querySelector('[data-testid="bound"]').textContent).toBe('2,1');
  });

  it('shows the phones field error under the editor and an empty hint when the list is empty', () => {
    const { getByText } = render(Harness, { props: { phones: [], errors: { phones: ['Phone entry 1 needs a number.'] } } });
    expect(getByText('Phone entry 1 needs a number.')).toBeInTheDocument();
    expect(getByText('No phone numbers')).toBeInTheDocument();
  });
});

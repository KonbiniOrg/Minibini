import { describe, it, expect } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import WizardSourcePool from '@/components/estimates/WizardSourcePool.svelte';

const ATOM = {
  type: 'task', id: 1, description: 'Cut', qty: 2, rate: '25.00', amount: '50.00',
  units: 'none', state: 'available',
};

describe('estimates/WizardSourcePool', () => {
  it('shows an empty message when there are no atoms', () => {
    const { getByText } = render(WizardSourcePool, { props: { sourcePool: { atoms: [] } } });
    expect(getByText('No atoms on this worksheet.')).toBeInTheDocument();
  });

  it('reflects an already-selected atom as checked', () => {
    const { getByRole } = render(WizardSourcePool, {
      props: { sourcePool: { atoms: [ATOM] }, selectedAtoms: [{ type: 'task', id: 1 }] },
    });
    expect(getByRole('checkbox')).toBeChecked();
  });

  it('toggles an atom on and off', async () => {
    const { getByRole } = render(WizardSourcePool, {
      props: { sourcePool: { atoms: [ATOM] } },
    });
    const checkbox = getByRole('checkbox');
    expect(checkbox).not.toBeChecked();

    await fireEvent.click(checkbox);
    expect(checkbox).toBeChecked();

    await fireEvent.click(checkbox);
    expect(checkbox).not.toBeChecked();
  });
});

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

  it('renders a fee type atom as selectable', () => {
    // The source pool now returns atoms with type task/material/fee.
    // Fee atoms must appear in the list and be selectable.
    const feeAtom = {
      type: 'fee', id: 7, description: 'Setup Fee', qty: 1, rate: '100.00',
      amount: '100.00', units: 'none', state: 'available',
    };
    const { getByText, getByRole } = render(WizardSourcePool, {
      props: { sourcePool: { atoms: [feeAtom] }, selectedAtoms: [] },
    });
    expect(getByText(/Setup Fee/)).toBeInTheDocument();
    expect(getByRole('checkbox')).not.toBeChecked();
  });

  it('renders task, material, and fee atoms together', () => {
    // Confirms the flat atom list handles all three types.
    const atoms = [
      { type: 'task', id: 1, description: 'Cut (Hourly)', qty: 2, rate: '25.00', amount: '50.00', units: 'hr', state: 'available' },
      { type: 'material', id: 2, description: 'Steel rod', qty: 3, rate: '5.00', amount: '15.00', units: 'in', state: 'available' },
      { type: 'fee', id: 3, description: 'Setup Fee', qty: 1, rate: '100.00', amount: '100.00', units: 'none', state: 'available' },
    ];
    const { getByText } = render(WizardSourcePool, {
      props: { sourcePool: { atoms }, selectedAtoms: [] },
    });
    expect(getByText(/Cut \(Hourly\)/)).toBeInTheDocument();
    expect(getByText(/Steel rod/)).toBeInTheDocument();
    expect(getByText(/Setup Fee/)).toBeInTheDocument();
  });
});

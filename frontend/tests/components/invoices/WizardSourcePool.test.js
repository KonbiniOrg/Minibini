import { describe, it, expect } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import WizardSourcePool from '@/components/invoices/WizardSourcePool.svelte';

const AVAILABLE_ATOM = {
  type: 'task', id: 5, description: 'Weld', qty: 1, rate: '10.00', amount: '10.00',
  units: 'none', state: 'available',
};

describe('invoices/WizardSourcePool', () => {
  it('shows a message when there is no source data', () => {
    const { getByText } = render(WizardSourcePool, { props: { sourcePool: null } });
    expect(getByText('No source data.')).toBeInTheDocument();
  });

  it('marks a task with no billable atoms', () => {
    const { getByText } = render(WizardSourcePool, {
      props: { sourcePool: { tasks: [{ task_id: 1, name: 'Idle', has_billable_atoms: false, atoms: [] }] } },
    });
    expect(getByText('Idle (no billable items)')).toBeInTheDocument();
  });

  it('toggles a billable atom under a task', async () => {
    const { getByRole } = render(WizardSourcePool, {
      props: {
        sourcePool: {
          tasks: [{ task_id: 1, name: 'Assembly', has_billable_atoms: true, atoms: [AVAILABLE_ATOM] }],
        },
      },
    });
    const checkbox = getByRole('checkbox');
    expect(checkbox).not.toBeChecked();
    await fireEvent.click(checkbox);
    expect(checkbox).toBeChecked();
  });

  it('renders both the materials and expenses groups (no key collision)', () => {
    const { getByText } = render(WizardSourcePool, {
      props: {
        sourcePool: {
          tasks: [
            { task_id: null, name: 'Materials (no task)', has_billable_atoms: true,
              atoms: [{ type: 'material', id: 1, description: 'Steel', qty: 1, rate: '5.00',
                        amount: '5.00', units: 'none', state: 'available' }] },
            { task_id: null, name: 'Expenses', has_billable_atoms: true,
              atoms: [{ type: 'expense', id: 9, description: 'FedEx shipping', qty: 1,
                        rate: '40.00', amount: '40.00', units: 'none', state: 'available' }] },
          ],
        },
      },
    });
    expect(getByText('Materials (no task)')).toBeInTheDocument();
    expect(getByText('Expenses')).toBeInTheDocument();
    expect(getByText(/FedEx shipping/)).toBeInTheDocument();
  });

  it('toggles an expense atom', async () => {
    const { getByRole } = render(WizardSourcePool, {
      props: {
        sourcePool: {
          tasks: [{ task_id: null, name: 'Expenses', has_billable_atoms: true,
            atoms: [{ type: 'expense', id: 9, description: 'FedEx', qty: 1, rate: '40.00',
                      amount: '40.00', units: 'none', state: 'available' }] }],
        },
      },
    });
    const checkbox = getByRole('checkbox');
    await fireEvent.click(checkbox);
    expect(checkbox).toBeChecked();
  });

  it('shows a non-selectable reason label for a not_billable task atom (task_incomplete)', () => {
    const { getByText, container } = render(WizardSourcePool, {
      props: {
        sourcePool: {
          tasks: [{
            task_id: 1, name: 'Cut', has_billable_atoms: true,
            atoms: [{ type: 'task', id: 1, description: 'Cut (Hourly)',
                      qty: 0, rate: '0.00', amount: '0.00', units: 'none',
                      state: 'not_billable', not_billable_reason: 'task_incomplete' }],
          }],
        },
      },
    });
    expect(getByText(/not complete/i)).toBeTruthy();
    const checkbox = container.querySelector('input[type="checkbox"]');
    expect(checkbox === null || checkbox.disabled).toBe(true);
  });

  it('shows a non-selectable reason label for a not_billable material atom (material_unconsumed)', () => {
    const { getByText, container } = render(WizardSourcePool, {
      props: {
        sourcePool: {
          tasks: [{
            task_id: 2, name: 'Prep', has_billable_atoms: true,
            atoms: [{ type: 'material', id: 7, description: 'Steel rod',
                      qty: 0, rate: '0.00', amount: '0.00', units: 'none',
                      state: 'not_billable', not_billable_reason: 'material_unconsumed' }],
          }],
        },
      },
    });
    expect(getByText(/not consumed/i)).toBeTruthy();
    const checkbox = container.querySelector('input[type="checkbox"]');
    expect(checkbox === null || checkbox.disabled).toBe(true);
  });

  it('renders fee atoms in a Fees group', () => {
    // Job-level fees appear as a separate group in the invoice wizard pool.
    const { getByText } = render(WizardSourcePool, {
      props: {
        sourcePool: {
          tasks: [
            { task_id: null, name: 'Fees', has_billable_atoms: true,
              atoms: [{ type: 'fee', id: 3, description: 'Setup Fee', qty: 1, rate: '100.00',
                        amount: '100.00', units: 'none', state: 'available' }] },
          ],
        },
      },
    });
    expect(getByText('Fees')).toBeInTheDocument();
    expect(getByText(/Setup Fee/)).toBeInTheDocument();
  });

  it('renders fee atoms as selectable checkboxes', async () => {
    const { getByRole } = render(WizardSourcePool, {
      props: {
        sourcePool: {
          tasks: [
            { task_id: null, name: 'Fees', has_billable_atoms: true,
              atoms: [{ type: 'fee', id: 4, description: 'Rush Fee', qty: 1, rate: '50.00',
                        amount: '50.00', units: 'none', state: 'available' }] },
          ],
        },
      },
    });
    const checkbox = getByRole('checkbox');
    expect(checkbox).not.toBeChecked();
    await fireEvent.click(checkbox);
    expect(checkbox).toBeChecked();
  });
});

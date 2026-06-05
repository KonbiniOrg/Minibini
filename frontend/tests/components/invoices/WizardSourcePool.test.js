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
});

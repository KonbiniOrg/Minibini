import { describe, it, expect, vi } from 'vitest';
import { render } from '@testing-library/svelte';
import WizardAtomRow from '@/components/wizards/WizardAtomRow.svelte';

function atom(overrides = {}) {
  return {
    type: 'task', id: 1, description: 'Milling (Std Hourly)',
    qty: '2', rate: '45.00', units: 'hour', amount: '90.00',
    state: 'available', sub_info: '',
    ...overrides,
  };
}

describe('WizardAtomRow struck-from-agreement flag', () => {
  it('badges an atom an accepted CO struck while its work remains live', () => {
    const { getByText } = render(WizardAtomRow, {
      props: { atom: atom({ struck_from_agreement: true }), onToggle: vi.fn() },
    });
    expect(getByText(/struck from agreement/)).toBeInTheDocument();
  });

  it('shows no struck badge by default', () => {
    const { queryByText } = render(WizardAtomRow, {
      props: { atom: atom(), onToggle: vi.fn() },
    });
    expect(queryByText(/struck from agreement/)).toBeNull();
  });
});

describe('WizardAtomRow cancelled-task flag (C3)', () => {
  it('badges a cancelled task so the biller chooses consciously', () => {
    const { getByText } = render(WizardAtomRow, {
      props: { atom: atom({ task_cancelled: true }), onToggle: vi.fn() },
    });
    expect(getByText(/cancelled — work done/)).toBeInTheDocument();
  });

  it('shows no cancelled badge on a normal complete task', () => {
    const { queryByText } = render(WizardAtomRow, {
      props: { atom: atom(), onToggle: vi.fn() },
    });
    expect(queryByText(/cancelled — work done/)).toBeNull();
  });

  it('still renders the not-billable row for incomplete tasks', () => {
    const { getByText } = render(WizardAtomRow, {
      props: {
        atom: atom({ state: 'not_billable', not_billable_reason: 'task_incomplete' }),
        onToggle: vi.fn(),
      },
    });
    expect(getByText(/task not complete/)).toBeInTheDocument();
  });
});

describe('WizardAtomRow deposit credit atoms', () => {
  function depositAtom(overrides = {}) {
    return {
      type: 'deposit', id: 5,
      description: 'Deposit credit — INV-1042',
      sub_info: '',
      qty: '1', rate: '-5000.00', units: 'none',
      amount: '-5000.00', state: 'available',
      ...overrides,
    };
  }

  it('labels deposit atoms and shows the credit amount', () => {
    const { getByText } = render(WizardAtomRow, {
      props: { atom: depositAtom(), selected: false, onToggle: vi.fn() },
    });
    expect(getByText('[deposit]')).toBeInTheDocument();
    expect(getByText(/credit/i)).toBeInTheDocument();
    expect(getByText(/\$5,000\.00/)).toBeInTheDocument();
  });

  it('renders the credit detail (not qty × rate) for a claimed deposit atom', () => {
    const { getByText } = render(WizardAtomRow, {
      props: {
        atom: depositAtom({
          state: 'claimed_by_other',
          claiming_invoice_id: 7,
          claiming_invoice_number: 'INV-1050',
        }),
        onToggle: vi.fn(),
      },
    });
    expect(getByText(/\$5,000\.00 credit/)).toBeInTheDocument();
    expect(getByText(/INV-1050/)).toBeInTheDocument();
  });
});

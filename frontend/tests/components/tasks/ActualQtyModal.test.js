import { describe, it, expect, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import ActualQtyModal from '@/components/tasks/ActualQtyModal.svelte';

describe('ActualQtyModal — complete (settle-up) mode', () => {
  it('shows the running total with units and asks for more', () => {
    const { getByText } = render(ActualQtyModal, {
      props: { mode: 'complete', unitLabel: 'pcs', currentQty: '14.00',
               onSubmit: vi.fn(), onClose: vi.fn() },
    });
    expect(getByText(/Entered so far/)).toBeInTheDocument();
    expect(getByText(/14.00 pcs/)).toBeInTheDocument();
    expect(getByText(/Any more to add\?/)).toBeInTheDocument();
  });

  it('empty input submits a zero increment when the total is positive', async () => {
    const onSubmit = vi.fn();
    const { getByRole } = render(ActualQtyModal, {
      props: { mode: 'complete', unitLabel: 'pcs', currentQty: '3',
               onSubmit, onClose: vi.fn() },
    });
    await fireEvent.click(getByRole('button', { name: 'Complete task' }));
    expect(onSubmit).toHaveBeenCalledWith(0, { completesTask: true });
  });

  it('shows the live final total as the user types', async () => {
    const { getByRole, getByText } = render(ActualQtyModal, {
      props: { mode: 'complete', unitLabel: 'pcs', currentQty: '9',
               onSubmit: vi.fn(), onClose: vi.fn() },
    });
    await fireEvent.input(getByRole('spinbutton'), { target: { value: '5' } });
    expect(getByText(/Final quantity: 14 pcs/)).toBeInTheDocument();
  });

  it('accepts a negative correction while the final stays positive', async () => {
    const onSubmit = vi.fn();
    const { getByRole } = render(ActualQtyModal, {
      props: { mode: 'complete', unitLabel: 'pcs', currentQty: '9',
               onSubmit, onClose: vi.fn() },
    });
    await fireEvent.input(getByRole('spinbutton'), { target: { value: '-2' } });
    await fireEvent.click(getByRole('button', { name: 'Complete task' }));
    expect(onSubmit).toHaveBeenCalledWith(-2, { completesTask: true });
  });

  it('blocks submit when the final total would not be positive', async () => {
    const onSubmit = vi.fn();
    const { getByRole, getByText } = render(ActualQtyModal, {
      props: { mode: 'complete', unitLabel: 'pcs', currentQty: '3',
               onSubmit, onClose: vi.fn() },
    });
    await fireEvent.input(getByRole('spinbutton'), { target: { value: '-3' } });
    await fireEvent.click(getByRole('button', { name: 'Complete task' }));
    expect(getByText(/must be greater than 0/)).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('blocks empty submit when nothing is on record', async () => {
    const onSubmit = vi.fn();
    const { getByRole, getByText } = render(ActualQtyModal, {
      props: { mode: 'complete', unitLabel: 'pcs', currentQty: null,
               onSubmit, onClose: vi.fn() },
    });
    await fireEvent.click(getByRole('button', { name: 'Complete task' }));
    expect(getByText(/must be greater than 0/)).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });
});

describe('ActualQtyModal — session mode', () => {
  it('asks for the session count with units and submits it', async () => {
    const onSubmit = vi.fn();
    const { getByRole } = render(ActualQtyModal, {
      props: { mode: 'session', unitLabel: 'pcs',
               onSubmit, onClose: vi.fn() },
    });
    expect(getByRole('heading', { name: 'Quantity this session' })).toBeInTheDocument();
    await fireEvent.input(getByRole('spinbutton'), { target: { value: '5' } });
    await fireEvent.click(getByRole('button', { name: 'Add' }));
    expect(onSubmit).toHaveBeenCalledWith(5, { completesTask: false });
  });

  it('rejects a typed non-positive session count', async () => {
    const onSubmit = vi.fn();
    const { getByRole, getByText } = render(ActualQtyModal, {
      props: { mode: 'session', unitLabel: 'pcs',
               onSubmit, onClose: vi.fn() },
    });
    await fireEvent.input(getByRole('spinbutton'), { target: { value: '0' } });
    await fireEvent.click(getByRole('button', { name: 'Add' }));
    expect(getByText(/greater than 0/)).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('empty submit is an explicit skip in every session context', async () => {
    // Settle-first everywhere: the gesture (stop / switch / clock-out /
    // cancel) is still pending while this modal is up, so Cancel aborts
    // the gesture and empty-submit means "no entry, proceed".
    const onSubmit = vi.fn();
    const { getByRole } = render(ActualQtyModal, {
      props: { mode: 'session', unitLabel: 'pcs',
               onSubmit, onClose: vi.fn() },
    });
    await fireEvent.click(getByRole('button', { name: 'Add' }));
    expect(onSubmit).toHaveBeenCalledWith(null, { completesTask: false });
  });

  it('checkbox switches submit to Add & complete and allows empty input', async () => {
    const onSubmit = vi.fn();
    const { getByRole } = render(ActualQtyModal, {
      props: { mode: 'session', unitLabel: 'pcs', currentQty: '9',
               allowComplete: true, onSubmit, onClose: vi.fn() },
    });
    await fireEvent.click(getByRole('checkbox'));
    await fireEvent.click(getByRole('button', { name: 'Add & complete' }));
    expect(onSubmit).toHaveBeenCalledWith(null, { completesTask: true });
  });

  it('checkbox shows the predicted final total', async () => {
    const { getByRole, getByText } = render(ActualQtyModal, {
      props: { mode: 'session', unitLabel: 'pcs', currentQty: '9',
               allowComplete: true, onSubmit: vi.fn(), onClose: vi.fn() },
    });
    await fireEvent.click(getByRole('checkbox'));
    await fireEvent.input(getByRole('spinbutton'), { target: { value: '5' } });
    expect(getByText(/Final quantity: 14 pcs/)).toBeInTheDocument();
  });

  it('renders the final-total line below the buttons so ticking the checkbox never moves them', async () => {
    const { getByRole, getByText, container } = render(ActualQtyModal, {
      props: { mode: 'session', unitLabel: 'pcs', currentQty: '9',
               allowComplete: true, onSubmit: vi.fn(), onClose: vi.fn() },
    });
    await fireEvent.click(getByRole('checkbox'));
    const totalLine = getByText(/Final quantity/);
    const buttons = container.querySelector('.buttons');
    // The total line must FOLLOW the button row in the DOM — anything
    // inserted above the buttons shifts the click target mid-reach.
    expect(
      buttons.compareDocumentPosition(totalLine) & Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
  });

  it('checkbox blocks completion when the final total would not be positive', async () => {
    const onSubmit = vi.fn();
    const { getByRole, getByText } = render(ActualQtyModal, {
      props: { mode: 'session', unitLabel: 'pcs', currentQty: null,
               allowComplete: true, onSubmit, onClose: vi.fn() },
    });
    await fireEvent.click(getByRole('checkbox'));
    await fireEvent.click(getByRole('button', { name: 'Add & complete' }));
    expect(getByText(/must be greater than 0/)).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('shows the running total when one is on record', () => {
    const { getByText } = render(ActualQtyModal, {
      props: { mode: 'session', unitLabel: 'pcs', currentQty: '6.00',
               onSubmit: vi.fn(), onClose: vi.fn() },
    });
    expect(getByText(/Entered so far/)).toBeInTheDocument();
    expect(getByText(/6.00 pcs/)).toBeInTheDocument();
  });

  it('omits the running-total line when nothing is recorded yet', () => {
    const { queryByText } = render(ActualQtyModal, {
      props: { mode: 'session', unitLabel: 'pcs', currentQty: null,
               onSubmit: vi.fn(), onClose: vi.fn() },
    });
    expect(queryByText(/Entered so far/)).toBeNull();
  });

  it('names the prior task in the switch/clock-out context', () => {
    const { getByText } = render(ActualQtyModal, {
      props: { mode: 'session', unitLabel: 'pcs', priorTaskName: 'Cut panels',
               onSubmit: vi.fn(), onClose: vi.fn() },
    });
    expect(getByText(/Cut panels/)).toBeInTheDocument();
  });

  it('prior-task context allows empty submit as an explicit skip', async () => {
    const onSubmit = vi.fn();
    const { getByRole } = render(ActualQtyModal, {
      props: { mode: 'session', unitLabel: 'pcs', priorTaskName: 'Cut panels',
               onSubmit, onClose: vi.fn() },
    });
    await fireEvent.click(getByRole('button', { name: 'Add' }));
    expect(onSubmit).toHaveBeenCalledWith(null, { completesTask: false });
  });

  it('cancels via onClose', async () => {
    const onClose = vi.fn();
    const { getByRole } = render(ActualQtyModal, {
      props: { mode: 'session', unitLabel: 'pcs',
               onSubmit: vi.fn(), onClose },
    });
    await fireEvent.click(getByRole('button', { name: 'Cancel' }));
    expect(onClose).toHaveBeenCalled();
  });

  it('renders a server error so a failed submit keeps the typed value visible', () => {
    const { getByText } = render(ActualQtyModal, {
      props: { mode: 'session', unitLabel: 'pcs',
               serverError: 'Cannot complete: unconsumed materials.',
               onSubmit: vi.fn(), onClose: vi.fn() },
    });
    expect(getByText(/unconsumed materials/)).toBeInTheDocument();
  });
});

import { describe, it, expect, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import ActualQtyModal from '@/components/tasks/ActualQtyModal.svelte';

describe('ActualQtyModal', () => {
  it('submits a positive quantity as a number', async () => {
    const onSubmit = vi.fn();
    const { getByRole } = render(ActualQtyModal, { props: { onSubmit, onClose: vi.fn() } });

    await fireEvent.input(getByRole('spinbutton'), { target: { value: '5' } });
    await fireEvent.click(getByRole('button', { name: 'Complete task' }));

    expect(onSubmit).toHaveBeenCalledWith(5);
  });

  it('rejects a non-positive quantity with an error and no submit', async () => {
    const onSubmit = vi.fn();
    const { getByRole, getByText } = render(ActualQtyModal, { props: { onSubmit, onClose: vi.fn() } });

    await fireEvent.click(getByRole('button', { name: 'Complete task' }));

    expect(getByText('Enter a quantity greater than 0.')).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('cancels via onClose', async () => {
    const onClose = vi.fn();
    const { getByRole } = render(ActualQtyModal, { props: { onSubmit: vi.fn(), onClose } });
    await fireEvent.click(getByRole('button', { name: 'Cancel' }));
    expect(onClose).toHaveBeenCalled();
  });
});

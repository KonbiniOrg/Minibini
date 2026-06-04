import { describe, it, expect, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import WorkerTimePromptModal from '@/components/board/WorkerTimePromptModal.svelte';

const PLACEHOLDER = 'e.g. 1:30 or 1.5';

describe('WorkerTimePromptModal', () => {
  it('renders nothing when closed', () => {
    const { queryByPlaceholderText } = render(WorkerTimePromptModal, {
      props: { open: false },
    });
    expect(queryByPlaceholderText(PLACEHOLDER)).toBeNull();
  });

  it('submits a parsed ISO duration for a valid entry', async () => {
    const onSubmit = vi.fn();
    const { getByPlaceholderText, getByRole } = render(WorkerTimePromptModal, {
      props: { open: true, onSubmit, onCancel: vi.fn() },
    });
    await fireEvent.input(getByPlaceholderText(PLACEHOLDER), { target: { value: '1:30' } });
    await fireEvent.click(getByRole('button', { name: 'Assign' }));
    expect(onSubmit).toHaveBeenCalledWith('PT1H30M');
  });

  it('errors on an empty entry', async () => {
    const onSubmit = vi.fn();
    const { getByRole, getByText } = render(WorkerTimePromptModal, {
      props: { open: true, onSubmit, onCancel: vi.fn() },
    });
    await fireEvent.click(getByRole('button', { name: 'Assign' }));
    expect(getByText(/Enter an estimated duration/)).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('errors on an unparseable entry', async () => {
    const onSubmit = vi.fn();
    const { getByPlaceholderText, getByRole, getByText } = render(WorkerTimePromptModal, {
      props: { open: true, onSubmit, onCancel: vi.fn() },
    });
    await fireEvent.input(getByPlaceholderText(PLACEHOLDER), { target: { value: 'abc' } });
    await fireEvent.click(getByRole('button', { name: 'Assign' }));
    expect(getByText(/Use HH:MM/)).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('errors on a zero duration', async () => {
    const onSubmit = vi.fn();
    const { getByPlaceholderText, getByRole, getByText } = render(WorkerTimePromptModal, {
      props: { open: true, onSubmit, onCancel: vi.fn() },
    });
    await fireEvent.input(getByPlaceholderText(PLACEHOLDER), { target: { value: '0' } });
    await fireEvent.click(getByRole('button', { name: 'Assign' }));
    expect(getByText(/greater than zero/)).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('cancels via onCancel', async () => {
    const onCancel = vi.fn();
    const { getByRole } = render(WorkerTimePromptModal, {
      props: { open: true, onSubmit: vi.fn(), onCancel },
    });
    await fireEvent.click(getByRole('button', { name: 'Cancel' }));
    expect(onCancel).toHaveBeenCalled();
  });
});

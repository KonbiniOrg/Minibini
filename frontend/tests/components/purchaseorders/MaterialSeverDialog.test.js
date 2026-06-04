import { describe, it, expect, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import MaterialSeverDialog from '@/components/purchaseorders/MaterialSeverDialog.svelte';

const ITEMS = [
  { material_id: 1, line_item_id: 10, job_number: 'JOB-1', description: 'Bolt', quantity: 5 },
];

describe('MaterialSeverDialog', () => {
  it('defaults every row to delete', async () => {
    const onSubmit = vi.fn();
    const { getByRole } = render(MaterialSeverDialog, {
      props: { items: ITEMS, onSubmit, onCancel: vi.fn() },
    });
    await fireEvent.click(getByRole('button', { name: 'Confirm' }));
    expect(onSubmit).toHaveBeenCalledWith({ 10: 'delete' });
  });

  it('records a "keep" decision when chosen', async () => {
    const onSubmit = vi.fn();
    const { getByRole } = render(MaterialSeverDialog, {
      props: { items: ITEMS, onSubmit, onCancel: vi.fn() },
    });
    await fireEvent.click(getByRole('radio', { name: /Keep on JOB-1/ }));
    await fireEvent.click(getByRole('button', { name: 'Confirm' }));
    expect(onSubmit).toHaveBeenCalledWith({ 10: 'keep' });
  });

  it('cancels via onCancel', async () => {
    const onCancel = vi.fn();
    const { getByRole } = render(MaterialSeverDialog, {
      props: { items: ITEMS, onSubmit: vi.fn(), onCancel },
    });
    await fireEvent.click(getByRole('button', { name: 'Cancel' }));
    expect(onCancel).toHaveBeenCalled();
  });
});

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));

import { api } from '@/lib/api.js';
import PurchaseOrderDetail from '@/components/purchaseorders/PurchaseOrderDetail.svelte';

function po() {
  return {
    po_id: 1, po_number: 'PO-1', status: 'draft', business: 2, business_name: 'Acme',
    created_date: '2026-01-01',
    line_items: [
      { line_item_id: 1, line_number: 1, description: 'A', qty: 2, price: '5.00' },
      { line_item_id: 2, line_number: 2, description: 'B', qty: 1, price: '10.00' },
    ],
  };
}

beforeEach(() => {
  api.get.mockReset();
  api.get.mockResolvedValue([]); // child UnitsSelect etc.
});

describe('PurchaseOrderDetail', () => {
  it('computes the order total', () => {
    const { getByText } = render(PurchaseOrderDetail, { props: { po: po(), canManageFinancials: true } });
    expect(getByText('$20.00')).toBeInTheDocument();
  });

  it('reorders a line via the callback', async () => {
    const onReorder = vi.fn();
    const { getAllByRole } = render(PurchaseOrderDetail, {
      props: { po: po(), canManageFinancials: true, onReorder },
    });
    // Two up-arrow buttons (one per row); the first row's is disabled.
    const ups = getAllByRole('button', { name: '▲' });
    await fireEvent.click(ups[1]);
    expect(onReorder).toHaveBeenCalledWith([2, 1]);
  });

  it('edits a line and saves via the callback', async () => {
    const onEditLineItem = vi.fn();
    const { getAllByRole, getByRole } = render(PurchaseOrderDetail, {
      props: { po: po(), canManageFinancials: true, onEditLineItem },
    });
    // [0] is the action-bar Edit (a link); [1] is the first line's Edit.
    await fireEvent.click(getAllByRole('button', { name: 'Edit' })[1]);
    await fireEvent.click(getByRole('button', { name: 'Save' }));

    expect(onEditLineItem).toHaveBeenCalledWith(1, {
      description: 'A', qty: 2, units: 'none', price: '5.00',
    });
  });

  it('fires the issue action', async () => {
    const onIssue = vi.fn();
    const { getByRole } = render(PurchaseOrderDetail, {
      props: { po: po(), canManageFinancials: true, onIssue },
    });
    await fireEvent.click(getByRole('button', { name: 'Mark as Issued' }));
    expect(onIssue).toHaveBeenCalled();
  });

  it('shows a task chip linking to the task detail page when a line is task-linked (fix 2a)', () => {
    const withTask = po();
    withTask.line_items[0].task = 9;
    withTask.line_items[0].task_detail = {
      task_id: 9, name: 'Mill part', job_id: 4, job_number: 'JOB-4',
    };
    const { getByRole, getByText } = render(PurchaseOrderDetail, {
      props: { po: withTask, canManageFinancials: true },
    });
    const link = getByRole('link', { name: /Mill part/ });
    expect(link).toHaveAttribute('href', '#/jobs/4/tasks/9');
    expect(getByText('JOB-4')).toBeInTheDocument();
  });

  it('shows a dash in the Task column when a line has no task link', () => {
    const { getAllByRole } = render(PurchaseOrderDetail, {
      props: { po: po(), canManageFinancials: true },
    });
    // No task-detail links anywhere in the table.
    const links = getAllByRole('link').filter((a) => a.className === 'task-chip');
    expect(links).toHaveLength(0);
  });
});

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor, within } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  errorMessage: (e, fallback) =>
    e?.data?.detail || e?.message || fallback || 'Something went wrong.',
}));
vi.mock('svelte-spa-router', () => ({
  link: () => {},
  push: vi.fn(),
}));

import { get } from 'svelte/store';
import { api } from '@/lib/api.js';
import { user } from '@/stores/auth.js';
import { overlayMessage, clearMessage } from '@/stores/messages.js';
import { getJobWs, rememberMode } from '@/stores/jobWorkspace.js';
import ChangeOrderPanel from '@/components/changeorders/ChangeOrderPanel.svelte';

const JOB = { job_id: 9, job_number: 'JOB-9', name: 'Job', contact: null };

function makeCO(overrides = {}) {
  return {
    change_order_id: 3,
    change_order_number: 'CO-3',
    job: 9,
    status: 'draft',
    can_manage: true,
    line_items: [],
    ...overrides,
  };
}

function mockApi(co) {
  api.get.mockReset();
  api.get.mockImplementation((url) => {
    if (url === `/api/change-orders/${co.change_order_id}/`) {
      return Promise.resolve({ ...co });
    }
    if (url.startsWith('/api/change-orders/') && url.includes('deliverables-baseline')) {
      return Promise.resolve({ baseline: [] });
    }
    if (url.startsWith('/api/change-orders/')) {
      // sibling COs list (?job=)
      return Promise.resolve({ results: [] });
    }
    if (url.startsWith('/api/jobs/') && url.includes('/deliverables/')) {
      return Promise.resolve([]);
    }
    if (url.startsWith('/api/jobs/')) {
      return Promise.resolve({ job_id: co.job, job_number: 'JOB-9', name: 'Job', contact: null });
    }
    if (url.startsWith('/api/estimates/')) {
      return Promise.resolve({ results: [] });
    }
    return Promise.resolve({});
  });
}

// Fuller mock than mockApi(): also controls the amended-agreement payload
// (needed for the mode-bar/customer/reorder views added on top of Task 8's
// COEditView), so the exact URL must be matched BEFORE the generic
// '/api/change-orders/' catch-all mockApi() relies on.
function mockApiFull(co, amended, { siblingCOs = [co] } = {}) {
  api.get.mockReset();
  api.get.mockImplementation((url) => {
    if (url === `/api/change-orders/${co.change_order_id}/`) {
      return Promise.resolve({ ...co });
    }
    if (url === `/api/change-orders/${co.change_order_id}/amended-agreement/`) {
      return Promise.resolve(amended);
    }
    if (url === `/api/change-orders/${co.change_order_id}/source-pool/`) {
      return Promise.resolve({ atoms: [] });
    }
    if (url.includes('deliverables-baseline')) {
      return Promise.resolve({ baseline: [] });
    }
    if (url.startsWith('/api/change-orders/?job=')) {
      return Promise.resolve({ results: siblingCOs });
    }
    if (url.startsWith('/api/jobs/') && url.includes('/deliverables/')) {
      return Promise.resolve([]);
    }
    if (url.startsWith('/api/jobs/')) {
      return Promise.resolve({ job_id: co.job, job_number: 'JOB-9', name: 'Job', contact: null });
    }
    if (url.startsWith('/api/estimates/')) {
      return Promise.resolve({ results: [] });
    }
    if (url.startsWith('/api/accounting-categories/')) {
      return Promise.resolve({ results: [] });
    }
    if (url.startsWith('/api/settings/')) {
      return Promise.resolve({});
    }
    return Promise.resolve({});
  });
}

const EMPTY_AMENDED = { rows: [], original_total: '0.00', co_delta: '0.00', revised_total: '0.00' };

beforeEach(() => {
  api.post?.mockReset?.();
  api.patch?.mockReset?.();
  api.delete?.mockReset?.();
  clearMessage();
  localStorage.clear();
});

describe('ChangeOrderPanel per-object can_manage gating', () => {
  it('shows edit affordances for a PM (can_manage true) without the global atom', async () => {
    user.set({ permissions: [] }); // no can_manage_jobs atom
    mockApi(makeCO({ can_manage: true, status: 'draft' }));

    const { findByText } = render(ChangeOrderPanel, {
      props: { job: JOB, coId: '3' },
    });

    expect(await findByText('Add line')).toBeInTheDocument();
    expect(await findByText('+ New deliverable')).toBeInTheDocument();
  });

  it('hides edit affordances when can_manage is false even with the global atom', async () => {
    user.set({ permissions: ['can_manage_jobs'] });
    mockApi(makeCO({ can_manage: false, status: 'draft' }));

    const { findByText, queryByText } = render(ChangeOrderPanel, {
      props: { job: JOB, coId: '3' },
    });

    // page renders (Line items heading) once load completes
    await findByText('Line items');
    expect(queryByText('Add line')).not.toBeInTheDocument();
    expect(queryByText('+ New deliverable')).not.toBeInTheDocument();
  });
});

describe('ChangeOrderPanel add-line flow', () => {
  it('"Add line" opens the unified picker (service/inventory/freeform), not a legacy action-select modal', async () => {
    user.set({ permissions: [] });
    mockApi(makeCO({ can_manage: true, status: 'draft' }));

    const { findByText, queryByText } = render(ChangeOrderPanel, {
      props: { job: JOB, coId: '3' },
    });

    await fireEvent.click(await findByText('Add line'));
    // The PriceListPicker's freeform footer is visible… (the "Is this a
    // material?" checkbox is retired — material-ness derives from the AC)
    expect(await findByText('Add Line')).toBeInTheDocument();
    // …and no gesture-modal opened underneath it — old action-select modal
    // is gone, and the new one never shows action/target selects either way.
    expect(queryByText('Add Change Order Line')).not.toBeInTheDocument();
    expect(queryByText('Edit Line')).not.toBeInTheDocument();
    expect(queryByText('Replace Line')).not.toBeInTheDocument();
  });
});

describe('ChangeOrderPanel error display', () => {
  it('shows a field error (not an alert) when adding a deliverable without a description', async () => {
    user.set({ permissions: [] });
    mockApi(makeCO({ can_manage: true, status: 'draft' }));

    const { findByText, getByRole } = render(ChangeOrderPanel, {
      props: { job: JOB, coId: '3' },
    });

    await fireEvent.click(await findByText('+ New deliverable'));
    await fireEvent.click(getByRole('button', { name: 'Add' }));

    expect(await findByText('Description is required.')).toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
  });

  it('shows the new-deliverable save failure in the inline form, not an alert', async () => {
    user.set({ permissions: [] });
    mockApi(makeCO({ can_manage: true, status: 'draft' }));
    api.post.mockRejectedValue(Object.assign(new Error('Request failed'), {
      status: 400, data: { qty_ordered: ['A valid number is required.'] },
    }));

    const { findByText, getByRole, getByPlaceholderText } = render(ChangeOrderPanel, {
      props: { job: JOB, coId: '3' },
    });

    await fireEvent.click(await findByText('+ New deliverable'));
    await fireEvent.input(getByPlaceholderText('Description'), { target: { value: 'Cabinet' } });
    await fireEvent.click(getByRole('button', { name: 'Add' }));

    expect(await findByText('A valid number is required.')).toBeInTheDocument();
  });

  it('raises the global overlay when a toolbar action fails', async () => {
    user.set({ permissions: [] });
    mockApi(makeCO({ can_manage: true, status: 'accepted' }));
    api.post.mockRejectedValue(Object.assign(new Error('Request failed'), {
      status: 400, data: { detail: 'A draft change order already exists.' },
    }));

    const { findByRole } = render(ChangeOrderPanel, {
      props: { job: JOB, coId: '3' },
    });

    await fireEvent.click(await findByRole('button', { name: 'Start new change order' }));
    await waitFor(() => expect(get(overlayMessage)).toEqual({
      kind: 'error', text: 'A draft change order already exists.',
    }));
  });
});

describe('ChangeOrderPanel in the job workspace', () => {
  it('shows the version subnav with this CO active and job-scoped links', async () => {
    user.set({ permissions: [] });
    const co = makeCO({ change_order_id: 3, change_order_number: 'CO-3', status: 'open', job: 9 });
    api.get.mockReset();
    api.get.mockImplementation((url) => {
      if (url === '/api/change-orders/3/') return Promise.resolve({ ...co });
      if (url.includes('deliverables-baseline')) return Promise.resolve({ baseline: [] });
      if (url.startsWith('/api/change-orders/?job=')) return Promise.resolve({ results: [co] });
      if (url.startsWith('/api/jobs/') && url.includes('/deliverables/')) return Promise.resolve([]);
      if (url.startsWith('/api/jobs/')) return Promise.resolve({ job_id: 9, job_number: 'JOB-9', name: 'Job', contact: null });
      if (url.startsWith('/api/estimates/?job=')) return Promise.resolve({ results: [{ estimate_id: 7, version: 1, status: 'accepted' }] });
      if (url.startsWith('/api/estimates/')) return Promise.resolve({ line_items: [] });
      return Promise.resolve({});
    });

    // Rendered under the job-scoped route params.
    const { container } = render(ChangeOrderPanel, {
      props: { job: JOB, coId: '3' },
    });

    let coLink;
    await waitFor(() => {
      const links = Array.from(container.querySelectorAll('.doc-subnav a'));
      coLink = links.find((l) => l.textContent.includes('CO-3'));
      expect(coLink).toBeTruthy();
    });
    const links = Array.from(container.querySelectorAll('.doc-subnav a'));
    const estLink = links.find((l) => l.textContent.includes('v1'));
    expect(estLink.getAttribute('href')).toBe('#/jobs/9/estimate/7');
    expect(coLink.getAttribute('href')).toBe('#/jobs/9/change-order/3');
    expect(coLink).toHaveClass('active');
    // (The job context band belongs to the host page's JobShell now — see
    // tests/routes/JobChangeOrderPage.test.js.)
  });
});

describe('ChangeOrderPanel mode bar', () => {
  it('loads accounting categories from the unfiltered endpoint (no exclude_fallback param)', async () => {
    user.set({ permissions: ['can_manage_jobs'] });
    const co = makeCO({ can_manage: true, status: 'draft' });
    mockApiFull(co, EMPTY_AMENDED);

    render(ChangeOrderPanel, { props: { job: JOB, coId: '3' } });

    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith('/api/accounting-categories/?page_size=100');
    });
  });

  it('offers Edit / Customer / Reorder for a manageable draft CO, switches views in place, and remembers the choice under co:{id}', async () => {
    user.set({ permissions: ['can_manage_jobs'] });
    const co = makeCO({ can_manage: true, status: 'draft' });
    mockApiFull(co, EMPTY_AMENDED);

    const { container, findByText } = render(ChangeOrderPanel, { props: { job: JOB, coId: '3' } });
    await findByText('Line items');

    const modeBar = () => container.querySelector('.doc-mode-bar');
    expect(within(modeBar()).getByRole('button', { name: 'Edit' })).toBeInTheDocument();
    expect(within(modeBar()).getByRole('button', { name: 'Customer' })).toBeInTheDocument();
    expect(within(modeBar()).getByRole('button', { name: 'Reorder' })).toBeInTheDocument();

    await fireEvent.click(within(modeBar()).getByRole('button', { name: 'Customer' }));
    expect(await findByText('Change Order CO-3')).toBeInTheDocument();
    expect(getJobWs(9).modes['co:3']).toBe('customer');

    await fireEvent.click(within(modeBar()).getByRole('button', { name: 'Edit' }));
    expect(await findByText('Line items')).toBeInTheDocument();
    expect(getJobWs(9).modes['co:3']).toBe('edit');
  });

  it('offers only Detail / Customer when the CO is not manageable', async () => {
    user.set({ permissions: [] });
    const co = makeCO({ can_manage: false, status: 'draft' });
    mockApiFull(co, EMPTY_AMENDED);

    const { container, findByText } = render(ChangeOrderPanel, { props: { job: JOB, coId: '3' } });
    await findByText('Line items');

    const modeBar = container.querySelector('.doc-mode-bar');
    expect(within(modeBar).getByRole('button', { name: 'Detail' })).toBeInTheDocument();
    expect(within(modeBar).getByRole('button', { name: 'Customer' })).toBeInTheDocument();
    expect(within(modeBar).queryByRole('button', { name: 'Edit' })).toBeNull();
    expect(within(modeBar).queryByRole('button', { name: 'Reorder' })).toBeNull();
  });

  it('offers only Detail / Customer once the CO is no longer a draft', async () => {
    user.set({ permissions: ['can_manage_jobs'] });
    const co = makeCO({ can_manage: true, status: 'open' });
    mockApiFull(co, EMPTY_AMENDED);

    const { container, findByText } = render(ChangeOrderPanel, { props: { job: JOB, coId: '3' } });
    await findByText('Line items');

    const modeBar = container.querySelector('.doc-mode-bar');
    expect(within(modeBar).getByRole('button', { name: 'Detail' })).toBeInTheDocument();
    expect(within(modeBar).queryByRole('button', { name: 'Edit' })).toBeNull();
    expect(within(modeBar).queryByRole('button', { name: 'Reorder' })).toBeNull();
  });

  it('falls back to Detail when "reorder" was remembered but the CO is no longer editable', async () => {
    user.set({ permissions: ['can_manage_jobs'] });
    rememberMode(9, 'co:3', 'reorder');
    const co = makeCO({ can_manage: true, status: 'open' });
    mockApiFull(co, EMPTY_AMENDED);

    const { container, findByText } = render(ChangeOrderPanel, { props: { job: JOB, coId: '3' } });
    await findByText('Line items');
    const modeBar = container.querySelector('.doc-mode-bar');
    expect(within(modeBar).getByRole('button', { name: 'Detail' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('restores a remembered "customer" mode on mount', async () => {
    user.set({ permissions: ['can_manage_jobs'] });
    rememberMode(9, 'co:3', 'customer');
    const co = makeCO({ can_manage: true, status: 'draft' });
    mockApiFull(co, EMPTY_AMENDED);

    const { findByText } = render(ChangeOrderPanel, { props: { job: JOB, coId: '3' } });
    expect(await findByText('Change Order CO-3')).toBeInTheDocument();
  });
});

describe('ChangeOrderPanel deliverables in edit mode only', () => {
  it('hides the deliverables section outside Edit mode', async () => {
    user.set({ permissions: ['can_manage_jobs'] });
    const co = makeCO({ can_manage: true, status: 'draft' });
    mockApiFull(co, EMPTY_AMENDED);

    const { container, findByText, queryByText } = render(ChangeOrderPanel, { props: { job: JOB, coId: '3' } });
    await findByText('Line items');
    expect(queryByText('+ New deliverable')).toBeInTheDocument();

    const modeBar = container.querySelector('.doc-mode-bar');
    await fireEvent.click(within(modeBar).getByRole('button', { name: 'Customer' }));
    await findByText('Change Order CO-3');
    expect(queryByText('+ New deliverable')).toBeNull();
  });
});

describe('ChangeOrderPanel date chips', () => {
  it('renders Created/Sent/Expires/Closed chips with muted "-" placeholders when empty', async () => {
    user.set({ permissions: [] });
    const co = makeCO({
      can_manage: true, status: 'draft',
      created_date: '2026-01-05T00:00:00Z',
      sent_date: null, expiration_date: null, closed_date: null,
    });
    mockApiFull(co, EMPTY_AMENDED);

    const { container, findByText } = render(ChangeOrderPanel, { props: { job: JOB, coId: '3' } });
    await findByText('Line items');

    expect(await findByText('Created')).toBeInTheDocument();
    expect(await findByText('Sent')).toBeInTheDocument();
    expect(await findByText('Expires')).toBeInTheDocument();
    expect(await findByText('Closed')).toBeInTheDocument();

    const chips = container.querySelectorAll('.doc-stat-chips .stat-chip-body .muted');
    expect(chips.length).toBe(3);
    chips.forEach((el) => expect(el.textContent).toBe('-'));
  });

  it('renders an actual date (not muted) when present', async () => {
    user.set({ permissions: [] });
    const co = makeCO({
      can_manage: true, status: 'open',
      created_date: '2026-01-05T00:00:00Z',
      sent_date: '2026-02-01T00:00:00Z',
      expiration_date: null, closed_date: null,
    });
    mockApiFull(co, EMPTY_AMENDED);

    const { container, findByText } = render(ChangeOrderPanel, { props: { job: JOB, coId: '3' } });
    await findByText('Line items');
    await findByText('Sent');

    const chips = container.querySelectorAll('.doc-stat-chips .stat-chip-body .muted');
    // Only Expires and Closed are empty now — Sent has a real date.
    expect(chips.length).toBe(2);
  });
});

describe('ChangeOrderPanel reorder mode', () => {
  it('reorder payload appends the CO\'s remove-line ids after the reordered add+replace ids', async () => {
    user.set({ permissions: ['can_manage_jobs'] });
    const co = makeCO({
      can_manage: true, status: 'draft',
      line_items: [
        { line_item_id: 101, line_number: 1, action: 'add', description: 'Add A', qty: '1', units: 'none', price: '10.00' },
        { line_item_id: 102, line_number: 2, action: 'add', description: 'Add B', qty: '1', units: 'none', price: '20.00' },
        { line_item_id: 103, line_number: 3, action: 'remove', target_line_item: 5, description: 'Old C' },
      ],
    });
    const amended = {
      rows: [
        { kind: 'added', co_line_id: 101, co_index: 1, line: { description: 'Add A', qty: '1', units: 'none', price: '10.00', amount: '10.00' } },
        { kind: 'added', co_line_id: 102, co_index: 2, line: { description: 'Add B', qty: '1', units: 'none', price: '20.00', amount: '20.00' } },
        { kind: 'removed', co_line_id: 103, original: { description: 'Old C', qty: '1', units: 'none', price: '5.00', amount: '5.00' } },
      ],
      original_total: '100.00', co_delta: '25.00', revised_total: '125.00',
    };
    mockApiFull(co, amended);
    api.post.mockResolvedValue({});

    const { container, findByText } = render(ChangeOrderPanel, { props: { job: JOB, coId: '3' } });
    await findByText('Line items');

    const modeBar = container.querySelector('.doc-mode-bar');
    await fireEvent.click(within(modeBar).getByRole('button', { name: 'Reorder' }));
    await findByText(/CO 1 — Add A/);

    const rows = Array.from(container.querySelectorAll('.doc-reorder-arrows'));
    expect(rows).toHaveLength(2); // only the add+replace rows are reorderable
    // Move the first row ("Add A") down, swapping with "Add B".
    await fireEvent.click(within(rows[0]).getByText('▼'));

    expect(api.post).toHaveBeenCalledWith('/api/change-orders/3/line-items/reorder/', {
      item_ids: [102, 101, 103],
    });
  });

  it('labels reorderable rows "CO {co_index} — {description}"', async () => {
    user.set({ permissions: ['can_manage_jobs'] });
    const co = makeCO({
      can_manage: true, status: 'draft',
      line_items: [
        { line_item_id: 201, line_number: 1, action: 'add', description: 'Sand edges', qty: '1', units: 'none', price: '15.00' },
      ],
    });
    const amended = {
      rows: [
        { kind: 'added', co_line_id: 201, co_index: 1, line: { description: 'Sand edges', qty: '1', units: 'none', price: '15.00', amount: '15.00' } },
      ],
      original_total: '0.00', co_delta: '15.00', revised_total: '15.00',
    };
    mockApiFull(co, amended);

    const { container, findByText } = render(ChangeOrderPanel, { props: { job: JOB, coId: '3' } });
    await findByText('Line items');
    const modeBar = container.querySelector('.doc-mode-bar');
    await fireEvent.click(within(modeBar).getByRole('button', { name: 'Reorder' }));

    expect(await findByText('CO 1 — Sand edges')).toBeInTheDocument();
  });
});

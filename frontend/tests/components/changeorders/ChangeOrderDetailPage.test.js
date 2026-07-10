import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';

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
import ChangeOrderDetailPage from '@/routes/change-orders/ChangeOrderDetailPage.svelte';

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

beforeEach(() => {
  api.post?.mockReset?.();
  api.patch?.mockReset?.();
  api.delete?.mockReset?.();
  clearMessage();
});

describe('ChangeOrderDetailPage per-object can_manage gating', () => {
  it('shows edit affordances for a PM (can_manage true) without the global atom', async () => {
    user.set({ permissions: [] }); // no can_manage_jobs atom
    mockApi(makeCO({ can_manage: true, status: 'draft' }));

    const { findByText } = render(ChangeOrderDetailPage, {
      props: { params: { id: '3' } },
    });

    expect(await findByText('+ New line')).toBeInTheDocument();
    expect(await findByText('+ New deliverable')).toBeInTheDocument();
  });

  it('hides edit affordances when can_manage is false even with the global atom', async () => {
    user.set({ permissions: ['can_manage_jobs'] });
    mockApi(makeCO({ can_manage: false, status: 'draft' }));

    const { findByText, queryByText } = render(ChangeOrderDetailPage, {
      props: { params: { id: '3' } },
    });

    // page renders (Line items heading) once load completes
    await findByText('Line items');
    expect(queryByText('+ New line')).not.toBeInTheDocument();
    expect(queryByText('+ New deliverable')).not.toBeInTheDocument();
  });
});

describe('ChangeOrderDetailPage add-line flow', () => {
  it('"+ New line" opens the unified picker (service/inventory/freeform), not the CO modal', async () => {
    user.set({ permissions: [] });
    mockApi(makeCO({ can_manage: true, status: 'draft' }));

    const { findByText, queryByText } = render(ChangeOrderDetailPage, {
      props: { params: { id: '3' } },
    });

    await fireEvent.click(await findByText('+ New line'));
    // The PriceListPicker's freeform footer is visible…
    expect(await findByText('Is this a material?')).toBeInTheDocument();
    // …and the legacy action-select modal did not open.
    expect(queryByText('Add Change Order Line')).not.toBeInTheDocument();
  });
});

describe('ChangeOrderDetailPage error display', () => {
  it('shows a field error (not an alert) when adding a deliverable without a description', async () => {
    user.set({ permissions: [] });
    mockApi(makeCO({ can_manage: true, status: 'draft' }));

    const { findByText, getByRole } = render(ChangeOrderDetailPage, {
      props: { params: { id: '3' } },
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

    const { findByText, getByRole, getByPlaceholderText } = render(ChangeOrderDetailPage, {
      props: { params: { id: '3' } },
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

    const { findByRole } = render(ChangeOrderDetailPage, {
      props: { params: { id: '3' } },
    });

    await fireEvent.click(await findByRole('button', { name: 'Start new change order' }));
    await waitFor(() => expect(get(overlayMessage)).toEqual({
      kind: 'error', text: 'A draft change order already exists.',
    }));
  });
});

describe('ChangeOrderDetailPage in the job workspace', () => {
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
    const { container } = render(ChangeOrderDetailPage, {
      props: { params: { jobId: '9', coId: '3' } },
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
    // The hidable job context band is present too.
    expect(container.querySelector('.context-band')).not.toBeNull();
  });
});

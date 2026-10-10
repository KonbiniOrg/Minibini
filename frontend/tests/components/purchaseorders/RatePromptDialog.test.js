import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), patch: vi.fn() },
  errorMessage: (e, fallback) => e?.data?.detail || e?.message || fallback || 'Something went wrong.',
}));
import { api } from '@/lib/api.js';
import RatePromptDialog from '@/components/purchaseorders/RatePromptDialog.svelte';
import { viewMode } from '@/stores/viewMode.js';

function prompts(overrides = {}) {
  return [
    { task_id: 10, task_name: 'Outsourced work', current_rate: '100.00', suggested_rate: '132.00',
      has_active_modifiers: false, ...overrides },
  ];
}

beforeEach(() => {
  api.get.mockReset();
  api.patch.mockReset();
});

describe('RatePromptDialog', () => {
  it('shows current and suggested rate formatted as money', () => {
    const { getByText } = render(RatePromptDialog, { props: { prompts: prompts(), onClose: vi.fn() } });
    expect(getByText('$100.00')).toBeInTheDocument();
    expect(getByText('$132.00')).toBeInTheDocument();
  });

  it('accept fetches the task, then PATCHes its rate via the job-scoped task endpoint', async () => {
    api.get.mockResolvedValue({ task_id: 10, job: { id: 5, job_number: 'JOB-5' } });
    api.patch.mockResolvedValue({});
    const { getByRole, findByText: find } = render(RatePromptDialog, { props: { prompts: prompts(), onClose: vi.fn() } });
    await fireEvent.click(getByRole('button', { name: 'Accept' }));

    await find('Updated.');
    expect(api.get).toHaveBeenCalledWith('/api/tasks/10/');
    expect(api.patch).toHaveBeenCalledWith('/api/jobs/5/tasks/10/', { rate: '132.00' });
  });

  it('decline dismisses the row without calling the api', async () => {
    const { getByRole, findByText: find } = render(RatePromptDialog, { props: { prompts: prompts(), onClose: vi.fn() } });
    await fireEvent.click(getByRole('button', { name: 'Decline' }));
    await find('Declined.');
    expect(api.get).not.toHaveBeenCalled();
    expect(api.patch).not.toHaveBeenCalled();
  });

  it('shows a per-row error on PATCH failure without crashing other rows', async () => {
    api.get.mockResolvedValue({ task_id: 10, job: { id: 5 } });
    api.patch.mockRejectedValue(Object.assign(new Error('Forbidden'), {
      status: 403, data: { detail: 'You do not have permission to perform this action.' },
    }));
    const { getByRole, findByText: find } = render(RatePromptDialog, { props: { prompts: prompts(), onClose: vi.fn() } });
    await fireEvent.click(getByRole('button', { name: 'Accept' }));
    expect(await find('You do not have permission to perform this action.')).toBeInTheDocument();
  });

  it('calls onClose from the Close button', async () => {
    const onClose = vi.fn();
    const { getByRole } = render(RatePromptDialog, { props: { prompts: prompts(), onClose } });
    await fireEvent.click(getByRole('button', { name: 'Close' }));
    expect(onClose).toHaveBeenCalled();
  });
});

describe('RatePromptDialog — markup_applied note', () => {
  it('shows a note when markupApplied is false (suggestion equals vendor cost)', () => {
    const { getByText } = render(RatePromptDialog, {
      props: { prompts: prompts(), markupApplied: false, onClose: vi.fn() },
    });
    expect(getByText(/no markup configured/i)).toBeInTheDocument();
  });

  it('omits the note when markupApplied is true', () => {
    const { queryByText } = render(RatePromptDialog, {
      props: { prompts: prompts(), markupApplied: true, onClose: vi.fn() },
    });
    expect(queryByText(/no markup configured/i)).toBeNull();
  });

  it('omits the note when markupApplied is not passed (defaults true)', () => {
    const { queryByText } = render(RatePromptDialog, {
      props: { prompts: prompts(), onClose: vi.fn() },
    });
    expect(queryByText(/no markup configured/i)).toBeNull();
  });
});

describe('RatePromptDialog — has_active_modifiers note (outsourced-work port re-shape)', () => {
  // current_rate here is the task's EFFECTIVE rate (compute_rate_prompts
  // reads task.effective_rate(), not the raw stored rate — a re-shape from
  // fees). When active modifiers are layered on top of that accepted rate,
  // say so per-row, so the PM doesn't read "Current Rate" as the whole story.
  it('shows a per-row note when a prompt has active modifiers', () => {
    const { getByText } = render(RatePromptDialog, {
      props: { prompts: prompts({ has_active_modifiers: true }), onClose: vi.fn() },
    });
    expect(getByText(/modifiers apply on top of the accepted rate/i)).toBeInTheDocument();
  });

  it('omits the note when a prompt has no active modifiers', () => {
    const { queryByText } = render(RatePromptDialog, {
      props: { prompts: prompts({ has_active_modifiers: false }), onClose: vi.fn() },
    });
    expect(queryByText(/modifiers apply on top of the accepted rate/i)).toBeNull();
  });

  it('omits the note when has_active_modifiers is not present on the prompt', () => {
    const { queryByText } = render(RatePromptDialog, {
      props: {
        prompts: [{ task_id: 10, task_name: 'Outsourced work', current_rate: '100.00', suggested_rate: '132.00' }],
        onClose: vi.fn(),
      },
    });
    expect(queryByText(/modifiers apply on top of the accepted rate/i)).toBeNull();
  });
});

describe('RatePromptDialog — wire-format decimals (compute_rate_prompts values reach the client as JSON numbers)', () => {
  // apps/api/purchasing/views.py hands compute_rate_prompts' dict straight to
  // Response(); these Decimal values are NOT run through a serializer
  // DecimalField, so DRF's JSON encoder falls back to its bare-Decimal case
  // (rest_framework/utils/encoders.py: `float(obj)`) and they arrive on the
  // wire as ordinary JSON numbers, not strings. At 2 decimal places that
  // number round-trips exactly (e.g. 99.90 survives float encode/decode
  // losslessly), so there's no precision hazard here. The dialog never
  // inspects or converts the type either way — `accept()` PATCHes back
  // exactly the value it received (`rate: prompt.suggested_rate`) — so this
  // suite fixes the prompt values as strings only as a convenient, type-
  // agnostic way to prove that pass-through-without-coercion behavior;
  // production payloads are numbers, and the component works identically
  // either way.
  it('renders a suggested_rate with trailing zeros intact', () => {
    const { getByText } = render(RatePromptDialog, {
      props: { prompts: prompts({ current_rate: '45.00', suggested_rate: '99.90' }), onClose: vi.fn() },
    });
    expect(getByText('$45.00')).toBeInTheDocument();
    expect(getByText('$99.90')).toBeInTheDocument();
  });

  it('PATCHes back exactly the suggested_rate value it received, uncoerced', async () => {
    api.get.mockResolvedValue({ task_id: 10, job: { id: 5 } });
    api.patch.mockResolvedValue({});
    const { getByRole } = render(RatePromptDialog, {
      props: { prompts: prompts({ suggested_rate: '99.90' }), onClose: vi.fn() },
    });
    await fireEvent.click(getByRole('button', { name: 'Accept' }));

    await vi.waitFor(() => expect(api.patch).toHaveBeenCalled());
    const [, body] = api.patch.mock.calls[0];
    expect(body.rate).toBe('99.90');
    expect(typeof body.rate).toBe('string');
  });
});

describe('RatePromptDialog — DataTable', () => {
  const headersOf = (t) => Array.from(t.querySelectorAll('thead th')).map((th) => th.textContent.trim());
  const ALL = ['Task', 'Current Rate', 'Suggested Rate', 'Decision'];
  it('renders the four columns in both densities with right-aligned rates and data-col', () => {
    viewMode.set('lite');
    const { container } = render(RatePromptDialog, { props: { prompts: prompts(), onClose: vi.fn() } });
    const table = container.querySelector('table.data-table');
    expect(headersOf(table)).toEqual(ALL);
    expect(table.querySelector('td[data-col="current"]').getAttribute('style')).toMatch(/text-align:\s*right/);
    expect(table.querySelectorAll('td[data-col="decision"] button')).toHaveLength(2);
    viewMode.set('full');
    const { container: c2 } = render(RatePromptDialog, { props: { prompts: prompts(), onClose: vi.fn() } });
    expect(headersOf(c2.querySelector('table.data-table'))).toEqual(ALL);
  });
});

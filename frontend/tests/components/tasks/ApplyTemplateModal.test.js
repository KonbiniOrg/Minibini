import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn() },
  errorMessage: (e, fallback) => e?.data?.detail || e?.message || fallback || 'Something went wrong.',
}));

import { api } from '@/lib/api.js';
import ApplyTemplateModal from '@/components/tasks/ApplyTemplateModal.svelte';

const FLAT_TEMPLATE = { template_id: 1, template_name: 'Flat kit', is_product_structure: false };
const STRUCTURE_TEMPLATE = { template_id: 2, template_name: 'Widget structure', is_product_structure: true };

function mockApi(templates = [FLAT_TEMPLATE, STRUCTURE_TEMPLATE]) {
  api.get.mockReset();
  api.post.mockReset();
  api.get.mockImplementation((url) => {
    if (url.startsWith('/api/work-templates/')) return Promise.resolve(templates);
    return Promise.resolve([]);
  });
  api.post.mockResolvedValue({ job_id: 5 });
}

beforeEach(() => {
  mockApi();
});

describe('ApplyTemplateModal — quantity input gating', () => {
  it('shows no Quantity field until a template is chosen', async () => {
    const { findByLabelText, queryByLabelText } = render(ApplyTemplateModal, {
      props: { open: true, jobId: 5 },
    });
    await findByLabelText(/Template/);
    expect(queryByLabelText(/Quantity/)).not.toBeInTheDocument();
  });

  it('does not show Quantity when a flat (non-product-structure) template is chosen', async () => {
    const { findByLabelText, queryByLabelText } = render(ApplyTemplateModal, {
      props: { open: true, jobId: 5 },
    });
    const select = await findByLabelText(/Template/);
    await fireEvent.change(select, { target: { value: String(FLAT_TEMPLATE.template_id) } });
    expect(queryByLabelText(/Quantity/)).not.toBeInTheDocument();
  });

  it('shows a required Quantity field when a product-structure template is chosen', async () => {
    const { findByLabelText } = render(ApplyTemplateModal, { props: { open: true, jobId: 5 } });
    const select = await findByLabelText(/Template/);
    await fireEvent.change(select, { target: { value: String(STRUCTURE_TEMPLATE.template_id) } });
    expect(await findByLabelText(/Quantity/)).toBeInTheDocument();
  });
});

describe('ApplyTemplateModal — submit payload', () => {
  it('sends only template_id for a flat template', async () => {
    const onSaved = vi.fn();
    const { findByLabelText, getByRole } = render(ApplyTemplateModal, {
      props: { open: true, jobId: 5, onSaved },
    });
    const select = await findByLabelText(/Template/);
    await fireEvent.change(select, { target: { value: String(FLAT_TEMPLATE.template_id) } });
    await fireEvent.click(getByRole('button', { name: 'Apply' }));
    await waitFor(() => expect(api.post).toHaveBeenCalled());
    expect(api.post).toHaveBeenCalledWith('/api/jobs/5/populate-from-template/', { template_id: 1 });
    expect(onSaved).toHaveBeenCalled();
  });

  it('sends template_id and quantity for a product-structure template', async () => {
    const { findByLabelText, getByRole } = render(ApplyTemplateModal, {
      props: { open: true, jobId: 5 },
    });
    const select = await findByLabelText(/Template/);
    await fireEvent.change(select, { target: { value: String(STRUCTURE_TEMPLATE.template_id) } });
    const qtyInput = await findByLabelText(/Quantity/);
    await fireEvent.input(qtyInput, { target: { value: '10' } });
    await fireEvent.click(getByRole('button', { name: 'Apply' }));
    await waitFor(() => expect(api.post).toHaveBeenCalled());
    expect(api.post).toHaveBeenCalledWith(
      '/api/jobs/5/populate-from-template/', { template_id: 2, quantity: 10 },
    );
  });

  it('rejects submit with no template chosen', async () => {
    const { findByRole, getByRole, findByText } = render(ApplyTemplateModal, {
      props: { open: true, jobId: 5 },
    });
    await findByRole('button', { name: 'Apply' });
    await fireEvent.click(getByRole('button', { name: 'Apply' }));
    expect(await findByText('This field is required.')).toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
  });

  it('rejects submit with a blank quantity on a product-structure template', async () => {
    const { findByLabelText, getByRole, findByText } = render(ApplyTemplateModal, {
      props: { open: true, jobId: 5 },
    });
    const select = await findByLabelText(/Template/);
    await fireEvent.change(select, { target: { value: String(STRUCTURE_TEMPLATE.template_id) } });
    await fireEvent.click(getByRole('button', { name: 'Apply' }));
    expect(await findByText('Must be greater than zero.')).toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
  });

  it('rejects submit with a non-positive quantity', async () => {
    const { findByLabelText, getByRole, findByText } = render(ApplyTemplateModal, {
      props: { open: true, jobId: 5 },
    });
    const select = await findByLabelText(/Template/);
    await fireEvent.change(select, { target: { value: String(STRUCTURE_TEMPLATE.template_id) } });
    const qtyInput = await findByLabelText(/Quantity/);
    await fireEvent.input(qtyInput, { target: { value: '0' } });
    await fireEvent.click(getByRole('button', { name: 'Apply' }));
    expect(await findByText('Must be greater than zero.')).toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
  });
});

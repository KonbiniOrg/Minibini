import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() } }));

import { api } from '@/lib/api.js';
import TaskTemplateManager from '@/components/TaskTemplateManager.svelte';

const TMPL = { template_id: 1, template_name: 'Welding', rate_scheme: 1, default_billable_qty: '', is_active: true, default_active_modifiers: [] };

beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();
  api.delete.mockReset();
  api.get.mockImplementation((url) => {
    if (url === '/api/task-templates/') return Promise.resolve({ results: [TMPL] });
    if (url.startsWith('/api/rate-schemes/')) return Promise.resolve({ results: [{ rate_scheme_id: 1, name: 'Hourly', algorithm: 'elapsed_time' }] });
    return Promise.resolve({ results: [] });
  });
  api.post.mockResolvedValue({});
  api.delete.mockResolvedValue({});
});

describe('TaskTemplateManager', () => {
  it('loads and lists templates', async () => {
    const { findByText } = render(TaskTemplateManager);
    expect(await findByText('Welding')).toBeInTheDocument();
  });

  it('creates a template', async () => {
    const { findByRole, getByLabelText, getByRole } = render(TaskTemplateManager);
    await fireEvent.click(await findByRole('button', { name: 'Add Template' }));
    await fireEvent.input(getByLabelText(/Name/), { target: { value: 'Painting' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    expect(api.post).toHaveBeenCalledWith('/api/task-templates/', expect.objectContaining({ template_name: 'Painting' }));
  });

  it('deletes a template after confirmation', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    const { findByRole } = render(TaskTemplateManager);
    await fireEvent.click(await findByRole('button', { name: 'Delete' }));
    expect(api.delete).toHaveBeenCalledWith('/api/task-templates/1/');
    confirmSpy.mockRestore();
  });
});

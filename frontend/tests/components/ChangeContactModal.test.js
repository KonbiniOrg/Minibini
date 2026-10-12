import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, screen } from '@testing-library/svelte';
vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), patch: vi.fn() }, errorMessage: (e, f) => e?.data?.detail || f }));
import { api } from '@/lib/api.js';
import ChangeContactModal from '@/components/ChangeContactModal.svelte';

beforeEach(() => { api.get.mockReset(); api.patch.mockReset(); api.patch.mockResolvedValue({}); });

describe('ChangeContactModal', () => {
  it('scopes the picker to the business and PATCHes only the contact', async () => {
    api.get.mockResolvedValue({ results: [{ contact_id: 9, name: 'Sam Roe', business: { business_name: 'Acme' } }] });
    const onSaved = vi.fn();
    render(ChangeContactModal, { props: { open: true, patchUrl: '/api/jobs/5/', businessId: 7, onSaved } });
    await fireEvent.input(screen.getByPlaceholderText(/contact/i), { target: { value: 'sam' } });
    await new Promise((r) => setTimeout(r, 300));
    expect(api.get).toHaveBeenCalledWith('/api/contacts/?search=sam&page_size=25&business=7');
    await fireEvent.mouseDown(await screen.findByRole('button', { name: /Sam Roe/ }));
    await fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(api.patch).toHaveBeenCalledWith('/api/jobs/5/', { contact: 9 });
    expect(onSaved).toHaveBeenCalled();
  });

  it('renders a server refusal under the buttons', async () => {
    api.get.mockResolvedValue({ results: [{ contact_id: 9, name: 'Sam Roe', business: null }] });
    api.patch.mockRejectedValueOnce({ status: 400, data: { detail: 'Cannot edit this job: …' } });
    render(ChangeContactModal, { props: { open: true, patchUrl: '/api/jobs/5/', businessId: 7 } });
    await fireEvent.input(screen.getByPlaceholderText(/contact/i), { target: { value: 'sam' } });
    await new Promise((r) => setTimeout(r, 300));
    await fireEvent.mouseDown(await screen.findByRole('button', { name: /Sam Roe/ }));
    await fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByText('Cannot edit this job: …')).toBeInTheDocument();
  });
});

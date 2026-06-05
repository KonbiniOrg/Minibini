import { describe, it, expect, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import ContactForm from '@/components/contacts/ContactForm.svelte';

describe('ContactForm', () => {
  it('creates: submits the form with an empty business coerced to null', async () => {
    const onSubmit = vi.fn();
    const { getByLabelText, getByRole } = render(ContactForm, { props: { onSubmit, onCancel: vi.fn() } });

    await fireEvent.input(getByLabelText(/First Name/), { target: { value: 'Jane' } });
    await fireEvent.input(getByLabelText(/Last Name/), { target: { value: 'Doe' } });
    await fireEvent.input(getByLabelText(/Email/), { target: { value: 'j@x.com' } });
    await fireEvent.click(getByRole('button', { name: 'Create' }));

    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
      first_name: 'Jane', last_name: 'Doe', email: 'j@x.com', business: null,
    }));
  });

  it('shows a Save button in edit mode', () => {
    const { getByRole } = render(ContactForm, {
      props: { contact: { first_name: 'A', last_name: 'B', email: 'a@b.com' }, onSubmit: vi.fn(), onCancel: vi.fn() },
    });
    expect(getByRole('button', { name: 'Save' })).toBeInTheDocument();
  });

  it('cancels via onCancel', async () => {
    const onCancel = vi.fn();
    const { getByRole } = render(ContactForm, { props: { onSubmit: vi.fn(), onCancel } });
    await fireEvent.click(getByRole('button', { name: 'Cancel' }));
    expect(onCancel).toHaveBeenCalled();
  });
});

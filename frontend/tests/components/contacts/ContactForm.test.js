import { describe, it, expect, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import ContactForm from '@/components/contacts/ContactForm.svelte';

describe('ContactForm', () => {
  it('creates: submits business_id (the writable serializer field), empty coerced to null', async () => {
    const onSubmit = vi.fn();
    const { getByLabelText, getByRole } = render(ContactForm, { props: { onSubmit, onCancel: vi.fn() } });

    await fireEvent.input(getByLabelText(/First Name/), { target: { value: 'Jane' } });
    await fireEvent.input(getByLabelText(/Last Name/), { target: { value: 'Doe' } });
    await fireEvent.input(getByLabelText(/Email/), { target: { value: 'j@x.com' } });
    await fireEvent.click(getByRole('button', { name: 'Create' }));

    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
      first_name: 'Jane', last_name: 'Doe', email: 'j@x.com', business_id: null,
    }));
    // The read-only `business` key must NOT be sent (DRF ignores it).
    const payload = onSubmit.mock.calls[0][0];
    expect(payload).not.toHaveProperty('business');
  });

  it('edit: submits the chosen business as business_id so the association persists', async () => {
    const onSubmit = vi.fn();
    const { getByRole } = render(ContactForm, {
      props: {
        contact: {
          first_name: 'A', last_name: 'B', email: 'a@b.com',
          business: { business_id: 7, business_name: 'Acme Steel' },
        },
        onSubmit, onCancel: vi.fn(),
      },
    });
    await fireEvent.click(getByRole('button', { name: 'Save' }));

    const payload = onSubmit.mock.calls[0][0];
    expect(payload.business_id).toBe(7);
    expect(payload).not.toHaveProperty('business');
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

  it('renders the field-error bag under inputs and formError in the footer', () => {
    const { getByText } = render(ContactForm, {
      props: {
        onSubmit: vi.fn(), onCancel: vi.fn(),
        errors: { email: ['Enter a valid email address.'], business_id: ['Invalid pk.'] },
        formError: 'At least one phone number is required.',
      },
    });
    expect(getByText('Enter a valid email address.')).toBeInTheDocument();
    expect(getByText('Invalid pk.')).toBeInTheDocument();
    const footer = getByText('At least one phone number is required.');
    expect(footer.closest('[role="alert"]')).not.toBeNull();
  });
});

import { describe, it, expect, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import BusinessForm from '@/components/contacts/BusinessForm.svelte';

describe('BusinessForm', () => {
  it('creates: includes the nested contact and coerces empty fields to null', async () => {
    const onSubmit = vi.fn();
    const { getByLabelText, getByRole } = render(BusinessForm, { props: { onSubmit, onCancel: vi.fn() } });

    await fireEvent.input(getByLabelText(/Business Name/), { target: { value: 'Acme' } });
    // Create mode requires the nested default-contact fields.
    await fireEvent.input(getByLabelText(/First Name/), { target: { value: 'Boss' } });
    await fireEvent.input(getByLabelText(/Last Name/), { target: { value: 'Hogg' } });
    await fireEvent.input(getByLabelText(/Email/), { target: { value: 'boss@x.com' } });
    await fireEvent.input(getByLabelText(/Mobile/), { target: { value: '555' } });
    await fireEvent.click(getByRole('button', { name: 'Create' }));

    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
      business_name: 'Acme',
      terms: null,
      default_contact_id: null,
      tax_multiplier: null,
      _contact: expect.objectContaining({ first_name: 'Boss' }),
    }));
  });

  it('edits: omits the nested contact', async () => {
    const onSubmit = vi.fn();
    const { getByRole } = render(BusinessForm, {
      props: {
        business: { business_name: 'Acme', terms: '', tax_multiplier: 0.5, default_contact: { contact_id: 3 }, contacts: [] },
        onSubmit, onCancel: vi.fn(),
      },
    });
    await fireEvent.click(getByRole('button', { name: 'Save' }));

    const arg = onSubmit.mock.calls[0][0];
    expect(arg._contact).toBeUndefined();
    expect(arg.business_name).toBe('Acme');
  });

  it('cancels via onCancel', async () => {
    const onCancel = vi.fn();
    const { getByRole } = render(BusinessForm, { props: { onSubmit: vi.fn(), onCancel } });
    await fireEvent.click(getByRole('button', { name: 'Cancel' }));
    expect(onCancel).toHaveBeenCalled();
  });

  it('renders the field-error bag under inputs (incl. nested contact keys) and formError in the footer', () => {
    const { getByText } = render(BusinessForm, {
      props: {
        onSubmit: vi.fn(), onCancel: vi.fn(),
        errors: { business_name: ['This field is required.'], email: ['Enter a valid email address.'] },
        formError: 'Could not create.',
      },
    });
    expect(getByText('This field is required.')).toBeInTheDocument();
    // The nested default-contact create uses the contact payload keys.
    expect(getByText('Enter a valid email address.')).toBeInTheDocument();
    const footer = getByText('Could not create.');
    expect(footer.closest('[role="alert"]')).not.toBeNull();
  });
});

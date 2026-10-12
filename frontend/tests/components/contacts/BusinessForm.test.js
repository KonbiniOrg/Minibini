import { describe, it, expect, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import BusinessForm from '@/components/contacts/BusinessForm.svelte';

describe('BusinessForm', () => {
  it('creates: includes the nested contact and coerces empty fields to null', async () => {
    const onSubmit = vi.fn();
    const { getByLabelText, getByRole, getAllByRole } = render(BusinessForm, { props: { onSubmit, onCancel: vi.fn() } });

    await fireEvent.input(getByLabelText(/Business Name/), { target: { value: 'Acme' } });
    // Create mode requires the nested default-contact fields.
    await fireEvent.input(getByLabelText(/First Name/), { target: { value: 'Boss' } });
    await fireEvent.input(getByLabelText(/Last Name/), { target: { value: 'Hogg' } });
    await fireEvent.input(getByLabelText(/Email/), { target: { value: 'boss@x.com' } });
    // Business has its own editor (first Add phone); the default contact's is the second.
    await fireEvent.click(getAllByRole('button', { name: 'Add phone' })[1]);
    await fireEvent.input(getByLabelText('Phone 1 number'), { target: { value: '555' } });
    await fireEvent.click(getByRole('button', { name: 'Create' }));

    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
      business_name: 'Acme',
      terms: null,
      default_contact_id: null,
      tax_multiplier: null,
      _contact: expect.objectContaining({ first_name: 'Boss', phones: [{ number: '555', label: '' }] }),
      phones: [],
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

  it('edit: default-contact select omits inactive contacts but keeps the current default', () => {
    const { container } = render(BusinessForm, {
      props: {
        business: {
          business_name: 'Acme', terms: '', tax_multiplier: 0.5, default_contact: { contact_id: 3 },
          contacts: [
            { contact_id: 1, name: 'Active One', is_active: true },
            { contact_id: 2, name: 'Inactive Two', is_active: false },
            { contact_id: 3, name: 'Inactive Default', is_active: false },
          ],
        },
        onSubmit: vi.fn(), onCancel: vi.fn(),
      },
    });
    const names = Array.from(container.querySelectorAll('#default_contact_id option')).map((o) => o.textContent.trim());
    expect(names).toContain('Active One');
    expect(names).toContain('Inactive Default');
    expect(names).not.toContain('Inactive Two');
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


describe('BusinessForm payment terms options', () => {
  it('labels options with the term name, falling back to the id', () => {
    const { getByRole } = render(BusinessForm, { props: {
      paymentTerms: [
        { term_id: 1, name: 'Net 30' },
        { term_id: 2, name: '' },
      ],
    }});
    expect(getByRole('option', { name: 'Net 30' })).toBeInTheDocument();
    expect(getByRole('option', { name: '2' })).toBeInTheDocument();
  });
});

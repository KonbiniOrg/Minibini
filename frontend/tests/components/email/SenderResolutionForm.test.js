import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import SenderResolutionForm from '@/components/email/SenderResolutionForm.svelte';

describe('SenderResolutionForm', () => {
  it('defaults to the existing contact when there is a single match', async () => {
    const { findByText } = render(SenderResolutionForm, {
      props: {
        senderInfo: { matching_contacts: [{ id: 5, name: 'Bob', email: 'b@x.com' }], matching_businesses: [] },
      },
    });
    expect(await findByText('Bob (b@x.com)')).toBeInTheDocument();
  });

  it('switches to new-contact mode and pre-fills from the sender when there is no match', async () => {
    const { findByDisplayValue } = render(SenderResolutionForm, {
      props: {
        senderInfo: {
          matching_contacts: [], matching_businesses: [],
          sender_name: 'Jane Doe', sender_email: 'jane@x.com', extracted_company: 'Acme',
        },
      },
    });
    expect(await findByDisplayValue('Jane')).toBeInTheDocument();      // first name
    expect(await findByDisplayValue('jane@x.com')).toBeInTheDocument(); // email
    expect(await findByDisplayValue('Acme')).toBeInTheDocument();       // new business name
  });
});

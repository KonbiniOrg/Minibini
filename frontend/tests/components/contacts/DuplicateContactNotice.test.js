import { describe, it, expect, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import DuplicateContactNotice from '@/components/contacts/DuplicateContactNotice.svelte';

const CONTACT = { contact_id: 3, name: 'Casey Contact', email: 'c@example.com' };

describe('DuplicateContactNotice', () => {
  it('shows the existing contact and wires both buttons', async () => {
    const onViewExisting = vi.fn();
    const onBack = vi.fn();
    const { getByText, getByRole } = render(DuplicateContactNotice, {
      props: { contact: CONTACT, onViewExisting, onBack },
    });
    expect(getByText('This contact may already exist')).toBeInTheDocument();
    expect(getByText('Casey Contact')).toBeInTheDocument();
    await fireEvent.click(getByRole('button', { name: 'View Existing Contact' }));
    expect(onViewExisting).toHaveBeenCalled();
    await fireEvent.click(getByRole('button', { name: 'Go Back and Edit' }));
    expect(onBack).toHaveBeenCalled();
  });

  it('renders no dialog of its own (it is a fragment for a host modal)', () => {
    const { queryByRole } = render(DuplicateContactNotice, { props: { contact: CONTACT } });
    expect(queryByRole('dialog')).toBeNull();
  });
});

import { describe, it, expect, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import FrozenPartyBanner from '@/components/FrozenPartyBanner.svelte';

describe('FrozenPartyBanner', () => {
  it('names the inactive contact with a link and offers the swap when the business is active', async () => {
    const onChangeContact = vi.fn();
    const { getByRole, getByText } = render(FrozenPartyBanner, { props: {
      kind: 'job', partyName: 'Jane Doe', partyHref: '#/contacts/3', businessName: 'Acme', businessActive: true, onChangeContact,
    } });
    expect(getByText(/Frozen:/)).toBeInTheDocument();
    expect(getByRole('link', { name: 'Jane Doe' })).toHaveAttribute('href', '#/contacts/3');
    await fireEvent.click(getByRole('button', { name: 'Change contact…' }));
    expect(onChangeContact).toHaveBeenCalled();
  });

  it('omits the swap when the business is inactive or absent', () => {
    const { queryByRole, getByText } = render(FrozenPartyBanner, { props: {
      kind: 'po', partyName: 'Acme', partyHref: '#/businesses/7', businessName: null, businessActive: false,
    } });
    expect(queryByRole('button', { name: 'Change contact…' })).toBeNull();
    expect(getByText(/Reactivate/)).toBeInTheDocument();
  });
});

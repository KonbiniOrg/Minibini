import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), postMultipart: vi.fn() },
}));

import { api } from '@/lib/api.js';
import { resolveSenderToContact } from '@/lib/email.js';

beforeEach(() => {
  api.post.mockReset();
  api.patch.mockReset();
});

describe('resolveSenderToContact', () => {
  it('throws when state is missing', async () => {
    await expect(resolveSenderToContact(null)).rejects.toThrow(/state is missing/i);
  });

  it('existing mode: requires a selected contact', async () => {
    await expect(
      resolveSenderToContact({ mode: 'existing', selectedContactId: '' }),
    ).rejects.toThrow(/select a contact/i);
  });

  it('existing mode: returns the parsed contact id, no api calls', async () => {
    const result = await resolveSenderToContact({ mode: 'existing', selectedContactId: '5' });
    expect(result).toEqual({ contactId: 5, businessId: null });
    expect(api.post).not.toHaveBeenCalled();
  });

  it('new mode: requires at least one phone number', async () => {
    await expect(
      resolveSenderToContact({ mode: 'new', contactForm: { name: 'Bob' }, businessMode: 'none' }),
    ).rejects.toThrow(/phone number/i);
  });

  it('new mode + existing business: requires a selected business', async () => {
    await expect(
      resolveSenderToContact({
        mode: 'new',
        contactForm: { mobile_number: '555' },
        businessMode: 'existing',
        selectedBusinessId: '',
      }),
    ).rejects.toThrow(/select a business/i);
  });

  it('new mode + existing business: posts the contact with business_id', async () => {
    api.post.mockResolvedValue({ contact_id: 100 });
    const result = await resolveSenderToContact({
      mode: 'new',
      contactForm: { mobile_number: '555' },
      businessMode: 'existing',
      selectedBusinessId: '7',
    });
    expect(api.post).toHaveBeenCalledWith('/api/contacts/', { mobile_number: '555', business_id: 7 });
    expect(result).toEqual({ contactId: 100, businessId: 7 });
  });

  it('new mode + new business: creates contact, business, links them', async () => {
    api.post.mockImplementation((url) => {
      if (url === '/api/contacts/') return Promise.resolve({ contact_id: 100 });
      if (url === '/api/businesses/') return Promise.resolve({ business_id: 200 });
      return Promise.resolve({});
    });
    api.patch.mockResolvedValue({});

    const result = await resolveSenderToContact({
      mode: 'new',
      contactForm: { mobile_number: '555' },
      businessMode: 'new',
      newBusinessName: '  Acme  ',
    });

    expect(api.post).toHaveBeenCalledWith('/api/businesses/', {
      business_name: 'Acme',
      default_contact_id: 100,
    });
    expect(api.patch).toHaveBeenCalledWith('/api/contacts/100/', { business_id: 200 });
    expect(result).toEqual({ contactId: 100, businessId: 200 });
  });

  it('new mode + new business: requires a business name', async () => {
    api.post.mockResolvedValue({ contact_id: 100 });
    await expect(
      resolveSenderToContact({
        mode: 'new',
        contactForm: { mobile_number: '555' },
        businessMode: 'new',
        newBusinessName: '   ',
      }),
    ).rejects.toThrow(/business name is required/i);
  });
});

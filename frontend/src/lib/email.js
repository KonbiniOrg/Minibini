import { api } from './api.js';

export const emailApi = {
  list: (page = 1) => api.get(`/api/emails/?page=${page}`),
  get: (id) => api.get(`/api/emails/${id}/`),
  refresh: () => api.post('/api/emails/refresh/', {}),
  senderInfo: (id) => api.get(`/api/emails/${id}/sender-info/`),
  linkToJob: (id, jobId) => api.post(`/api/emails/${id}/link-to-job/`, { job_id: jobId }),
  unlinkFromJob: (id) => api.post(`/api/emails/${id}/unlink-from-job/`, {}),
  createJob: (id, { contact, name, description }) =>
    api.post(`/api/emails/${id}/create-job/`, { contact, name, description }),
  linkToPo: (id, poId) => api.post(`/api/emails/${id}/link-to-po/`, { po_id: poId }),
  unlinkFromPo: (id) => api.post(`/api/emails/${id}/unlink-from-po/`, {}),
  createPo: (id, { vendor_business_id }) =>
    api.post(`/api/emails/${id}/create-po/`, { vendor_business_id }),
  replyDefaults: (id) => api.get(`/api/emails/${id}/reply-defaults/`),
  reply: (id, formData) => api.postMultipart(`/api/emails/${id}/reply/`, formData),
};

/** Resolve a SenderResolutionForm state into {contactId, businessId} by
 * making the necessary contact/business POSTs. Throws on validation errors
 * the caller should surface to the user. */
export async function resolveSenderToContact(state) {
  if (!state) throw new Error('SenderResolutionForm state is missing.');

  if (state.mode === 'existing') {
    if (!state.selectedContactId) {
      throw new Error('Please select a contact.');
    }
    const contactId = parseInt(state.selectedContactId, 10);
    return { contactId, businessId: null };
  }

  // mode === 'new'
  const contactPayload = { ...state.contactForm };
  if (
    !contactPayload.work_number &&
    !contactPayload.mobile_number &&
    !contactPayload.home_number
  ) {
    throw new Error('At least one phone number (work, mobile, or home) is required.');
  }

  let businessId = null;
  let newBusinessName = null;
  if (state.businessMode === 'existing') {
    if (!state.selectedBusinessId) {
      throw new Error('Please select a business or choose "no business".');
    }
    businessId = parseInt(state.selectedBusinessId, 10);
    contactPayload.business_id = businessId;
  } else if (state.businessMode === 'new') {
    newBusinessName = (state.newBusinessName || '').trim();
    if (!newBusinessName) {
      throw new Error('Business name is required.');
    }
    // Check for a name conflict before creating the contact below —
    // otherwise a duplicate name fails only after the contact is already
    // committed, leaving it orphaned (mirrors BusinessFormPage's create flow).
    const nameCheck = await api.get(`/api/businesses/check-name/?name=${encodeURIComponent(newBusinessName)}`);
    if (nameCheck.exists) {
      const err = new Error('A business with this name already exists.');
      err.status = 409;
      err.data = { code: 'duplicate_business_name', existing_business: nameCheck.business };
      throw err;
    }
  }

  const contact = await api.post('/api/contacts/', contactPayload);

  if (state.businessMode === 'new') {
    const biz = await api.post('/api/businesses/', {
      business_name: newBusinessName,
      default_contact_id: contact.contact_id,
    });
    await api.patch(`/api/contacts/${contact.contact_id}/`, { business_id: biz.business_id });
    businessId = biz.business_id;
  }

  return { contactId: contact.contact_id, businessId };
}

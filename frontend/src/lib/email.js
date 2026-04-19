import { api } from './api.js';

export const emailApi = {
  list: (page = 1) => api.get(`/api/emails/?page=${page}`),
  get: (id) => api.get(`/api/emails/${id}/`),
  refresh: () => api.post('/api/emails/refresh/', {}),
  senderInfo: (id) => api.get(`/api/emails/${id}/sender-info/`),
  linkToJob: (id, jobId) => api.post(`/api/emails/${id}/link-to-job/`, { job_id: jobId }),
  unlinkFromJob: (id) => api.post(`/api/emails/${id}/unlink-from-job/`, {}),
  createJob: (id, { contact, name }) =>
    api.post(`/api/emails/${id}/create-job/`, { contact, name }),
};

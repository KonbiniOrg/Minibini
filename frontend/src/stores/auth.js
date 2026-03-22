import { writable } from 'svelte/store';
import { api } from '../lib/api.js';

export const user = writable(null);
export const authChecked = writable(false);

export async function checkAuth() {
  try {
    const data = await api.get('/api/auth/me/');
    user.set(data);
  } catch {
    user.set(null);
  }
  authChecked.set(true);
}

export async function login(username, password) {
  const data = await api.post('/api/auth/login/', { username, password });
  user.set(data);
  return data;
}

export async function logout() {
  await api.post('/api/auth/logout/');
  user.set(null);
}

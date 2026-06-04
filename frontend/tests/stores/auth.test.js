import { describe, it, expect, vi, beforeEach } from 'vitest';
import { get } from 'svelte/store';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn() } }));

import { api } from '@/lib/api.js';
import { user, authChecked, checkAuth, login, logout } from '@/stores/auth.js';

beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();
  user.set(null);
  authChecked.set(false);
});

describe('auth store', () => {
  it('checkAuth stores the user and marks auth checked on success', async () => {
    api.get.mockResolvedValue({ id: 1, username: 'rachel' });
    await checkAuth();
    expect(get(user)).toEqual({ id: 1, username: 'rachel' });
    expect(get(authChecked)).toBe(true);
  });

  it('checkAuth clears the user (still marks checked) on failure', async () => {
    user.set({ id: 9 });
    api.get.mockRejectedValue(new Error('401'));
    await checkAuth();
    expect(get(user)).toBeNull();
    expect(get(authChecked)).toBe(true);
  });

  it('login posts credentials, stores and returns the user', async () => {
    api.post.mockResolvedValue({ id: 2, username: 'sam' });
    const result = await login('sam', 'pw');
    expect(api.post).toHaveBeenCalledWith('/api/auth/login/', { username: 'sam', password: 'pw' });
    expect(get(user)).toEqual({ id: 2, username: 'sam' });
    expect(result).toEqual({ id: 2, username: 'sam' });
  });

  it('logout posts and clears the user', async () => {
    user.set({ id: 3 });
    api.post.mockResolvedValue(undefined);
    await logout();
    expect(api.post).toHaveBeenCalledWith('/api/auth/logout/');
    expect(get(user)).toBeNull();
  });
});

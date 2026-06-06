import { describe, it, expect, beforeEach } from 'vitest';
import { get } from 'svelte/store';

import { user } from '@/stores/auth.js';
import {
  canManageJobs,
  canManageFinancials,
  canManageTime,
  canManageConfig,
} from '@/stores/permissions.js';

beforeEach(() => {
  user.set(null);
});

describe('permissions store', () => {
  it('each atom is false when there is no user', () => {
    expect(get(canManageJobs)).toBe(false);
    expect(get(canManageFinancials)).toBe(false);
    expect(get(canManageTime)).toBe(false);
    expect(get(canManageConfig)).toBe(false);
  });

  it('each atom is false when the user lacks it (and missing permissions is treated as empty)', () => {
    user.set({ id: 1, permissions: [] });
    expect(get(canManageJobs)).toBe(false);
    user.set({ id: 1 }); // no permissions key at all
    expect(get(canManageFinancials)).toBe(false);
  });

  it('maps each atom to its codename independently', () => {
    user.set({ id: 1, permissions: ['can_manage_jobs'] });
    expect(get(canManageJobs)).toBe(true);
    expect(get(canManageFinancials)).toBe(false);
    expect(get(canManageTime)).toBe(false);
    expect(get(canManageConfig)).toBe(false);

    user.set({ id: 1, permissions: ['can_manage_financials', 'can_manage_time'] });
    expect(get(canManageJobs)).toBe(false);
    expect(get(canManageFinancials)).toBe(true);
    expect(get(canManageTime)).toBe(true);
    expect(get(canManageConfig)).toBe(false);
  });

  it('reacts when the user store changes', () => {
    expect(get(canManageJobs)).toBe(false);
    user.set({ id: 1, permissions: ['can_manage_jobs'] });
    expect(get(canManageJobs)).toBe(true);
    user.set(null);
    expect(get(canManageJobs)).toBe(false);
  });
});

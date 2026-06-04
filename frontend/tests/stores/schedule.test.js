import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn() } }));

// schedule.js keeps module-level `currentOffset`/`currentDays`/`refreshTimer`,
// so reset the module between tests to start from a clean offset.
let api;
let sched;

beforeEach(async () => {
  vi.resetModules();
  ({ api } = await import('@/lib/api.js'));
  sched = await import('@/stores/schedule.js');
  api.get.mockReset();
  api.post.mockReset();
  api.get.mockResolvedValue({ workers: [] });
});

afterEach(() => {
  sched.stopAutoRefresh();
  vi.useRealTimers();
});

describe('schedule store', () => {
  it('loadSchedule sets the days param (offset 0 is omitted)', async () => {
    await sched.loadSchedule(7);
    expect(api.get).toHaveBeenCalledWith('/api/schedule/?days=7');
  });

  it('scrollDays shifts the offset and reloads', async () => {
    await sched.loadSchedule(7);
    await sched.scrollDays(2);
    expect(api.get).toHaveBeenLastCalledWith('/api/schedule/?days=7&offset=2');
  });

  it('resetToToday clears the offset', async () => {
    await sched.loadSchedule(7);
    await sched.scrollDays(2);
    await sched.resetToToday();
    expect(api.get).toHaveBeenLastCalledWith('/api/schedule/?days=7');
  });

  it('startAutoRefresh polls on the interval until stopped', async () => {
    vi.useFakeTimers();
    sched.startAutoRefresh(1000);
    await vi.advanceTimersByTimeAsync(2500);
    expect(api.get).toHaveBeenCalledTimes(2);
    sched.stopAutoRefresh();
    await vi.advanceTimersByTimeAsync(3000);
    expect(api.get).toHaveBeenCalledTimes(2);
  });

  it('reorderTasksInLane posts the new order then reloads', async () => {
    api.post.mockResolvedValue({});
    await sched.reorderTasksInLane('worker-1', [3, 1, 2]);
    expect(api.post).toHaveBeenCalledWith('/api/tasks/reorder/', { task_ids: [3, 1, 2] });
    expect(api.get).toHaveBeenCalledTimes(1); // the follow-up loadSchedule
  });
});

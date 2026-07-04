import { describe, it, expect, vi } from 'vitest';
import { createFlushRegistry } from '@/lib/wizardFlush.js';

describe('createFlushRegistry', () => {
  it('flushAll runs every registered flusher', async () => {
    const r = createFlushRegistry();
    const a = vi.fn().mockResolvedValue();
    const b = vi.fn().mockResolvedValue();
    r.register(1, a);
    r.register(2, b);
    await r.flushAll();
    expect(a).toHaveBeenCalled();
    expect(b).toHaveBeenCalled();
  });

  it('unregister (null) removes a flusher', async () => {
    const r = createFlushRegistry();
    const a = vi.fn().mockResolvedValue();
    r.register(1, a);
    r.register(1, null);
    await r.flushAll();
    expect(a).not.toHaveBeenCalled();
  });

  it('flushAll attempts every flusher and rejects if any fails', async () => {
    const r = createFlushRegistry();
    const ok = vi.fn().mockResolvedValue();
    const bad = vi.fn().mockRejectedValue(new Error('nope'));
    r.register(1, ok);
    r.register(2, bad);
    await expect(r.flushAll()).rejects.toThrow(/could not be saved/);
    expect(ok).toHaveBeenCalled(); // attempted despite the sibling failure
    expect(bad).toHaveBeenCalled();
  });

  it('flushAll resolves when there is nothing to flush', async () => {
    const r = createFlushRegistry();
    await expect(r.flushAll()).resolves.toBeUndefined();
  });
});

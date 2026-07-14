import { describe, it, expect, beforeEach } from 'vitest';
import {
  getJobWs, rememberSection, rememberMode, rememberBand, JOB_WS_KEY,
} from '@/stores/jobWorkspace.js';

beforeEach(() => localStorage.removeItem(JOB_WS_KEY));

describe('jobWorkspace store', () => {
  it('returns defaults for an unknown job: expanded band, no selections', () => {
    expect(getJobWs(7)).toEqual({ band: 'expanded', sections: {}, modes: {} });
  });

  it('remembers the selected document per section per job', () => {
    rememberSection(7, 'estimate', 31);
    rememberSection(7, 'invoice', 12);
    rememberSection(8, 'estimate', 99);
    expect(getJobWs(7).sections).toEqual({ estimate: '31', invoice: '12' });
    expect(getJobWs(8).sections).toEqual({ estimate: '99' });
  });

  it('remembers per-DOCUMENT mode, not per-section', () => {
    rememberMode(7, 31, 'reconcile');
    rememberMode(7, 32, 'lines');
    expect(getJobWs(7).modes['31']).toBe('reconcile');
    expect(getJobWs(7).modes['32']).toBe('lines');
  });

  it('remembers band collapse per job and survives a reload (re-read from storage)', () => {
    rememberBand(7, 'collapsed');
    const raw = JSON.parse(localStorage.getItem(JOB_WS_KEY));
    expect(raw.jobs['7'].band).toBe('collapsed');
    expect(getJobWs(7).band).toBe('collapsed');
  });

  it('evicts least-recently-used jobs past 50', () => {
    for (let i = 1; i <= 51; i++) rememberBand(i, 'collapsed');
    expect(getJobWs(1)).toEqual({ band: 'expanded', sections: {}, modes: {} }); // evicted
    expect(getJobWs(51).band).toBe('collapsed');
    const raw = JSON.parse(localStorage.getItem(JOB_WS_KEY));
    expect(raw.order).toHaveLength(50);
  });

  it('touching an old job refreshes its LRU position', () => {
    for (let i = 1; i <= 50; i++) rememberBand(i, 'collapsed');
    rememberSection(1, 'estimate', 5); // touch job 1
    rememberBand(51, 'collapsed');     // evicts job 2, not job 1
    expect(getJobWs(1).sections.estimate).toBe('5');
    expect(getJobWs(2)).toEqual({ band: 'expanded', sections: {}, modes: {} });
  });

  it('tolerates corrupt storage', () => {
    localStorage.setItem(JOB_WS_KEY, '{not json');
    expect(getJobWs(7)).toEqual({ band: 'expanded', sections: {}, modes: {} });
  });
});

import { describe, it, expect } from 'vitest';
import { pageFromUrl, pageRange } from '@/lib/pagination.js';

describe('pageFromUrl', () => {
  it('extracts the page number from a url', () => {
    expect(pageFromUrl('http://x/api/jobs/?page=3')).toBe(3);
  });

  it('defaults to 1 when there is no page param or no url', () => {
    expect(pageFromUrl('http://x/api/jobs/')).toBe(1);
    expect(pageFromUrl(undefined)).toBe(1);
  });
});

describe('pageRange', () => {
  it('returns empty string when there are no results', () => {
    expect(pageRange({ results: [], count: 0 })).toBe('');
    expect(pageRange(null)).toBe('');
  });

  it('computes the range on a first page (has next)', () => {
    const data = { results: new Array(25), count: 30, next: 'http://x/?page=2', previous: null };
    expect(pageRange(data)).toBe('1–25 of 30');
  });

  it('computes the range on a last page (has previous)', () => {
    const data = { results: new Array(5), count: 30, next: null, previous: 'http://x/?page=1' };
    expect(pageRange(data)).toBe('26–30 of 30');
  });

  it('computes the range for a single page (no next/previous)', () => {
    const data = { results: new Array(10), count: 10, next: null, previous: null };
    expect(pageRange(data)).toBe('1–10 of 10');
  });
});

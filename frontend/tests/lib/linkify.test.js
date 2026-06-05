import { describe, it, expect } from 'vitest';
import { linkify } from '@/lib/linkify.js';

describe('linkify', () => {
  it('returns an empty array for empty input', () => {
    expect(linkify('')).toEqual([]);
  });

  it('keeps plain text as a single text segment', () => {
    expect(linkify('hello world')).toEqual([
      { type: 'text', value: 'hello world' },
    ]);
  });

  it('splits a dotted-host http(s) url into a url segment with href', () => {
    const segments = linkify('see https://example.com/x now');
    expect(segments).toEqual([
      { type: 'text', value: 'see ' },
      {
        type: 'url',
        value: 'https://example.com/x',
        href: 'https://example.com/x',
        display: 'example.com/x',
      },
      { type: 'text', value: ' now' },
    ]);
  });

  it('trims trailing sentence punctuation out of the link', () => {
    const segments = linkify('visit https://example.com.');
    expect(segments).toEqual([
      { type: 'text', value: 'visit ' },
      {
        type: 'url',
        value: 'https://example.com',
        href: 'https://example.com',
        display: 'example.com',
      },
      { type: 'text', value: '.' },
    ]);
  });

  it('does not link a scheme-less or dotless host', () => {
    expect(linkify('http://localhost/wiki')).toEqual([
      { type: 'text', value: 'http://localhost/wiki' },
    ]);
  });
});

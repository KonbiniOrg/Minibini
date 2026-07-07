// triageError routes api errors to the three display venues (see
// architecture-and-conventions.md §3.9 and frontend/README.md → Error
// Handling): overlay (infrastructure), form-footer message (operation
// errors + non_field_errors), field bag (validation).
import { describe, it, expect } from 'vitest';
import { triageError } from '@/lib/errorTriage.js';

describe('triageError', () => {
  it('routes no-body errors (backend down) to the overlay', () => {
    const t = triageError({ status: 502, data: null, message: 'Server error (502)' });
    expect(t.overlay).toBe('Server error (502)');
    expect(t.message).toBe('');
    expect(t.fields).toEqual({});
  });

  it('routes 5xx to the overlay even with a JSON detail', () => {
    const t = triageError({ status: 502, data: { detail: 'Email send failed.' } });
    expect(t.overlay).toBe('Email send failed.');
  });

  it('routes detail bodies to the footer message, ignoring machine payload', () => {
    const t = triageError({
      status: 409,
      data: {
        detail: 'Scheme is referenced; create a new version instead of editing.',
        supersede_url: 'http://x/supersede/',
        reference_counts: { tasks: 3 },
      },
    });
    expect(t.overlay).toBeNull();
    expect(t.message).toBe('Scheme is referenced; create a new version instead of editing.');
    expect(t.fields).toEqual({});
  });

  it('routes field-keyed bodies to the bag', () => {
    const t = triageError({ status: 400, data: { rate: ['Must be positive.'] } });
    expect(t.overlay).toBeNull();
    expect(t.message).toBe('');
    expect(t.fields).toEqual({ rate: ['Must be positive.'] });
  });

  it('splits non_field_errors into the footer, rest into the bag', () => {
    const t = triageError({
      status: 400,
      data: { non_field_errors: ['Dates overlap.'], end: ['Required.'] },
    });
    expect(t.message).toBe('Dates overlap.');
    expect(t.fields).toEqual({ end: ['Required.'] });
  });
});

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import { viewMode } from '@/stores/viewMode.js';
import HistoryPanel from '@/components/HistoryPanel.svelte';

// A note entry (has text) and a system entry (no text, changes only).
const NOTE = { timestamp: '2026-01-02T10:00:00Z', text: 'hello there', username: 'alice' };
const SYSTEM = {
  timestamp: '2026-01-01T10:00:00Z', username: 'bob',
  entry_type: 'update', object_type: 'Job', changes: { status: { old: 'a', new: 'b' } },
};

beforeEach(() => {
  viewMode.set('lite'); // shared singleton — normalize per test
});

describe('HistoryPanel', () => {
  it('full mode shows both note and system entries', () => {
    viewMode.set('full');
    const { getByText } = render(HistoryPanel, {
      props: { history: { results: [SYSTEM, NOTE] } },
    });
    expect(getByText('alice')).toBeInTheDocument();
    expect(getByText('bob')).toBeInTheDocument();
  });

  it('lite mode hides entries without text', () => {
    viewMode.set('lite');
    const { getByText, queryByText } = render(HistoryPanel, {
      props: { history: { results: [SYSTEM, NOTE] } },
    });
    expect(getByText('alice')).toBeInTheDocument();
    expect(queryByText('bob')).toBeNull();
  });

  it('submits a note via the callback and clears the textarea', async () => {
    const onAddNote = vi.fn().mockResolvedValue(undefined);
    const { getByPlaceholderText, getByRole } = render(HistoryPanel, {
      props: { history: { results: [] }, onAddNote },
    });
    const textarea = getByPlaceholderText('Add a note...');
    await fireEvent.input(textarea, { target: { value: 'my note' } });
    await fireEvent.click(getByRole('button', { name: 'Add Note' }));

    expect(onAddNote).toHaveBeenCalledWith('my note');
    expect(textarea.value).toBe('');
  });

  it('disables Add Note when the field is empty', () => {
    const { getByRole } = render(HistoryPanel, {
      props: { history: { results: [] }, onAddNote: vi.fn() },
    });
    expect(getByRole('button', { name: 'Add Note' })).toBeDisabled();
  });

  it('renders no note form when onAddNote is absent', () => {
    const { queryByPlaceholderText } = render(HistoryPanel, {
      props: { history: { results: [] } },
    });
    expect(queryByPlaceholderText('Add a note...')).toBeNull();
  });
});

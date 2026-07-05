import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn() } }));

import { api } from '@/lib/api.js';
import TagEditor from '@/components/TagEditor.svelte';

const ENDPOINT = '/api/jobs/5';

beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();
  api.get.mockResolvedValue({ results: [] }); // the on-mount $effect tag fetch
});

describe('TagEditor', () => {
  it('renders the initial tags', () => {
    const { getByText } = render(TagEditor, {
      props: { endpoint: ENDPOINT, initialTags: [{ tag_id: 1, name: 'urgent' }] },
    });
    expect(getByText('urgent')).toBeInTheDocument();
  });

  it('readonly renders chips without remove/add controls', () => {
    const { getByText, queryByPlaceholderText, queryByRole } = render(TagEditor, {
      props: { readonly: true, initialTags: [{ tag_id: 1, name: 'urgent' }] },
    });
    expect(getByText('urgent')).toBeInTheDocument();
    expect(queryByPlaceholderText('Add tag…')).toBeNull();
    expect(queryByRole('button')).toBeNull();
    // No tag-list fetch in readonly mode either.
    expect(api.get).not.toHaveBeenCalled();
  });

  it('shows "No tags" when there are none', () => {
    const { getByText } = render(TagEditor, {
      props: { endpoint: ENDPOINT, initialTags: [] },
    });
    expect(getByText('No tags')).toBeInTheDocument();
  });

  it('adds a tag via the Add button', async () => {
    api.post.mockResolvedValue([{ tag_id: 2, name: 'rush' }]);
    const { getByPlaceholderText, getByRole } = render(TagEditor, {
      props: { endpoint: ENDPOINT, initialTags: [] },
    });

    await fireEvent.input(getByPlaceholderText('Add tag…'), { target: { value: 'rush' } });
    await fireEvent.click(getByRole('button', { name: 'Add' }));

    expect(api.post).toHaveBeenCalledWith('/api/jobs/5/add-tag/', { name: 'rush' });
  });

  it('adds a tag on Enter', async () => {
    api.post.mockResolvedValue([{ tag_id: 2, name: 'rush' }]);
    const { getByPlaceholderText } = render(TagEditor, {
      props: { endpoint: ENDPOINT, initialTags: [] },
    });
    const input = getByPlaceholderText('Add tag…');
    await fireEvent.input(input, { target: { value: 'rush' } });
    await fireEvent.keyDown(input, { key: 'Enter' });

    expect(api.post).toHaveBeenCalledWith('/api/jobs/5/add-tag/', { name: 'rush' });
  });

  it('removes a tag', async () => {
    api.post.mockResolvedValue([]);
    const { getByRole } = render(TagEditor, {
      props: { endpoint: ENDPOINT, initialTags: [{ tag_id: 1, name: 'urgent' }] },
    });

    await fireEvent.click(getByRole('button', { name: '×' }));
    expect(api.post).toHaveBeenCalledWith('/api/jobs/5/remove-tag/', { tag_id: 1 });
  });

  it('filters suggestions by the typed query', async () => {
    api.get.mockResolvedValue({
      results: [{ tag_id: 2, name: 'rush' }, { tag_id: 3, name: 'late' }],
    });
    const { getByPlaceholderText, findByRole, queryByRole } = render(TagEditor, {
      props: { endpoint: ENDPOINT, initialTags: [] },
    });
    const input = getByPlaceholderText('Add tag…');
    await fireEvent.focus(input);
    await fireEvent.input(input, { target: { value: 'ru' } });

    expect(await findByRole('button', { name: 'rush' })).toBeInTheDocument();
    expect(queryByRole('button', { name: 'late' })).toBeNull();
  });
});

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('svelte-spa-router', () => ({ push: vi.fn() }));

import { push } from 'svelte-spa-router';
import SearchBox from '@/components/home/SearchBox.svelte';

beforeEach(() => {
  push.mockReset();
});

describe('SearchBox', () => {
  it('navigates to the search route with the encoded query', async () => {
    const { getByLabelText, getByRole } = render(SearchBox);
    await fireEvent.input(getByLabelText('Search'), { target: { value: 'a b' } });
    await fireEvent.click(getByRole('button', { name: 'Search' }));
    expect(push).toHaveBeenCalledWith('/search?q=a%20b');
  });

  it('does nothing for a blank query', async () => {
    const { getByLabelText, getByRole } = render(SearchBox);
    await fireEvent.input(getByLabelText('Search'), { target: { value: '   ' } });
    await fireEvent.click(getByRole('button', { name: 'Search' }));
    expect(push).not.toHaveBeenCalled();
  });
});

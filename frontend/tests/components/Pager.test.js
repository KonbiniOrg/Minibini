import { describe, it, expect, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import Pager from '@/components/Pager.svelte';

describe('Pager', () => {
  it('renders nothing when everything fits on one page', () => {
    const { container } = render(Pager, { props: { page: 1, count: 25, onPage: () => {} } });
    expect(container.querySelector('.pager')).toBeNull();
  });

  it('always renders both buttons; Previous is disabled on the first page, Next on the last', async () => {
    const onPage = vi.fn();
    const { getByRole, getByText, rerender } = render(Pager, { props: { page: 1, count: 60, onPage } });
    expect(getByRole('button', { name: 'Previous' })).toBeDisabled();
    expect(getByRole('button', { name: 'Next' })).toBeEnabled();
    expect(getByText('Page 1 of 3')).toBeInTheDocument();

    await fireEvent.click(getByRole('button', { name: 'Next' }));
    expect(onPage).toHaveBeenCalledWith(2);

    await rerender({ page: 3, count: 60, onPage });
    expect(getByRole('button', { name: 'Previous' })).toBeEnabled();
    expect(getByRole('button', { name: 'Next' })).toBeDisabled();
    await fireEvent.click(getByRole('button', { name: 'Previous' }));
    expect(onPage).toHaveBeenLastCalledWith(2);
  });

  it('keeps the buttons in the same DOM order on every page so they never move', async () => {
    const { getAllByRole, rerender } = render(Pager, { props: { page: 1, count: 60, onPage: () => {} } });
    const order = () => getAllByRole('button').map((b) => b.textContent);
    expect(order()).toEqual(['Previous', 'Next']);
    await rerender({ page: 2, count: 60, onPage: () => {} });
    expect(order()).toEqual(['Previous', 'Next']);
  });

  it('honours a custom page size and a caller-supplied label', () => {
    const { getByText, getByRole } = render(Pager, {
      props: { page: 2, count: 20, pageSize: 10, label: '11–20 of 20', onPage: () => {} },
    });
    expect(getByText('11–20 of 20')).toBeInTheDocument();
    expect(getByRole('button', { name: 'Next' })).toBeDisabled();
  });
});

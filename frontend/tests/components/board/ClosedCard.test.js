import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import ClosedCard from '@/components/board/ClosedCard.svelte';

describe('ClosedCard', () => {
  it('labels an archived job and renders without a completed date', () => {
    const { getByText, container } = render(ClosedCard, {
      props: { job: { job_id: 1, job_number: 'OLD-1', name: 'x', status: 'archived', contact_name: 'C',
                      billed: '0.00', spent: '0.00', profit: '0.00' } },
    });
    expect(getByText('Archived')).toBeInTheDocument();
    expect(container.querySelector('.card-border').getAttribute('style')).toContain('rgb(156, 163, 175)');
  });
});

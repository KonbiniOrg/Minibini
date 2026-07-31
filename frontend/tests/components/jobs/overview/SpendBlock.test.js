import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import SpendBlock from '@/components/jobs/overview/SpendBlock.svelte';
import { spendBlock } from '@/lib/jobOverview.js';

describe('SpendBlock', () => {
  it('active — renders labor/materials/total stats', () => {
    const props = {
      job: { status: 'in_progress' },
      overview: { spend: { labor: 2340, materials_bought: 1176, total: 3516, labor_hours: 41.5 } },
      scopeTotal: 12400,
    };
    const expected = spendBlock(props);
    const { container, getByText } = render(SpendBlock, { props });
    expect(container.querySelector('.summary-block')).toHaveClass('active');
    expect(getByText('Spend')).toBeInTheDocument();
    expect(getByText(expected.stats[0].value)).toBeInTheDocument();
    expect(getByText(expected.stats[2].sub)).toBeInTheDocument();
  });

  it('dormant — nothing spent yet', () => {
    const props = { job: { status: 'in_progress' }, overview: { spend: { total: 0 } }, scopeTotal: 0 };
    const expected = spendBlock(props);
    const { container, getByText } = render(SpendBlock, { props });
    expect(container.querySelector('.summary-block')).toHaveClass('dormant');
    expect(getByText(expected.dormantText)).toBeInTheDocument();
  });

  it('links the card at the history section (Analysis placeholder)', () => {
    const props = {
      job: { job_id: 42, status: 'in_progress' },
      overview: { spend: { labor: 100, materials_bought: 50, total: 150, labor_hours: 2 } },
      scopeTotal: 1000,
    };
    const { container } = render(SpendBlock, { props });
    expect(container.querySelector('.summary-block').getAttribute('href')).toBe('#/jobs/42/history');
  });
});

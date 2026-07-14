import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import WorkBlock from '@/components/jobs/overview/WorkBlock.svelte';
import { workBlock } from '@/lib/jobOverview.js';

describe('WorkBlock', () => {
  it('active — renders the progress bar + task/due stats', () => {
    const props = {
      job: { status: 'in_progress' },
      overview: {
        work: {
          est_time_total_hours: 64,
          est_time_complete_hours: 41,
          tasks_total: 14,
          tasks_complete: 9,
          tasks_blocked: 1,
          working_now: [{ worker_name: 'Dana', task_name: 'CNC cut shelving parts' }],
        },
        due: { date: '2025-07-24', working_days_left: 11 },
        spend: { labor_hours: 41.5 },
      },
      tasksPlanned: 0,
    };
    const expected = workBlock(props);
    const { container, getByText } = render(WorkBlock, { props });
    expect(container.querySelector('.summary-block')).toHaveClass('active');
    expect(getByText('Work')).toBeInTheDocument();
    expect(container.querySelector('.stat-progress-fill').getAttribute('style')).toContain(`${expected.stats[0].bar}%`);
    expect(getByText(expected.clock.lines[0])).toBeInTheDocument();
  });

  it('dormant — job not yet approved, tasks planned', () => {
    const props = { job: { status: 'draft' }, overview: { work: {} }, tasksPlanned: 12 };
    const expected = workBlock(props);
    const { container, getByText } = render(WorkBlock, { props });
    expect(container.querySelector('.summary-block')).toHaveClass('dormant');
    expect(getByText(expected.dormantText)).toBeInTheDocument();
  });
});

import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import SummaryBlock from '@/components/jobs/overview/SummaryBlock.svelte';

// ---------------------------------------------------------------------------
// Fixture models — shaped exactly like the lib's (Task 4) return values.
// ---------------------------------------------------------------------------
const activeModel = {
  state: 'active',
  stats: [
    {
      label: 'Estimate',
      value: 'v2',
      pill: { text: 'OPEN', tone: 'open' },
      sub: 'v1 superseded',
    },
    {
      label: 'Due',
      value: '7/24',
      valueTone: 'warn',
      sub: '11 working days left',
      subTone: 'warn',
    },
    {
      label: 'Progress · by estimated time',
      value: '64%',
      unit: '41h of 64h',
      bar: 64,
    },
    {
      label: 'Overdue',
      value: '6/1',
      valueTone: 'bad',
      sub: 'overdue by 3 working days',
      subTone: 'bad',
    },
    {
      label: 'Coverage',
      value: 'OK',
      valueTone: 'good',
    },
    {
      label: 'Neutral stat',
      value: '5',
      valueTone: 'neutral',
      sub: 'neither here nor there',
      subTone: 'neutral',
    },
  ],
  clock: {
    tone: 'bad',
    lines: ['No customer response in 12 days', 'second signal line'],
  },
  href: '#/jobs/42/estimate/8',
};

const frozenModel = {
  state: 'frozen',
  frozenText: 'v2 accepted 6/30 · 3 deliverables',
  href: '#/jobs/42/estimate/8',
};
const dormantModel = { state: 'dormant', dormantText: 'no estimate yet', href: '#/jobs/42/estimate' };

describe('SummaryBlock', () => {
  it('renders an active block with the .active temperature class and title', () => {
    const { container, getByText } = render(SummaryBlock, {
      props: { title: 'Scope', model: activeModel },
    });
    const block = container.querySelector('.summary-block');
    expect(block).toHaveClass('active');
    expect(getByText('Scope')).toBeInTheDocument();
  });

  it('applies the accent identity class in every temperature; none without the prop', () => {
    for (const [model, temp] of [[activeModel, 'active'], [frozenModel, 'frozen'], [dormantModel, 'dormant']]) {
      const { container } = render(SummaryBlock, {
        props: { title: 'Scope', model, accent: 'scope' },
      });
      const block = container.querySelector(`.summary-block.${temp}`);
      expect(block).toHaveClass('accent-scope');
    }
    const { container } = render(SummaryBlock, {
      props: { title: 'Scope', model: activeModel },
    });
    const bare = container.querySelector('.summary-block');
    expect([...bare.classList].some((c) => c.startsWith('accent-'))).toBe(false);
  });

  it('renders each stat label, value, and unit', () => {
    const { container } = render(SummaryBlock, { props: { title: 'Work', model: activeModel } });
    const stats = container.querySelectorAll('.stat');
    expect(stats.length).toBe(activeModel.stats.length);
    expect(container.textContent).toContain('Estimate');
    expect(container.textContent).toContain('v2');
    expect(container.textContent).toContain('41h of 64h');
    const unitEl = container.querySelector('.stat-value .unit');
    expect(unitEl).toBeInTheDocument();
    expect(unitEl.textContent).toBe('41h of 64h');
  });

  it('renders a status pill via the global status-badge vocabulary', () => {
    const { container } = render(SummaryBlock, { props: { title: 'Scope', model: activeModel } });
    const pill = container.querySelector('.status-badge.status-open');
    expect(pill).toBeInTheDocument();
    expect(pill.textContent).toBe('OPEN');
  });

  it('applies subTone as a clock-color class on .stat-sub', () => {
    const { container } = render(SummaryBlock, { props: { title: 'Work', model: activeModel } });
    const subs = container.querySelectorAll('.stat-sub');
    const warnSub = Array.from(subs).find((el) => el.textContent === '11 working days left');
    expect(warnSub).toHaveClass('clock-warn');
    const badSub = Array.from(subs).find((el) => el.textContent === 'overdue by 3 working days');
    expect(badSub).toHaveClass('clock-bad');
    const neutralSub = Array.from(subs).find((el) => el.textContent === 'neither here nor there');
    expect(neutralSub).not.toHaveClass('clock-bad');
    expect(neutralSub).not.toHaveClass('clock-warn');
    expect(neutralSub).not.toHaveClass('clock-good');
  });

  it('applies valueTone as a clock-color class on .stat-value', () => {
    const { container } = render(SummaryBlock, { props: { title: 'Work', model: activeModel } });
    const values = container.querySelectorAll('.stat-value');
    const warnValue = Array.from(values).find((el) => el.textContent.startsWith('7/24'));
    expect(warnValue).toHaveClass('clock-warn');
    const badValue = Array.from(values).find((el) => el.textContent.startsWith('6/1'));
    expect(badValue).toHaveClass('clock-bad');
    const goodValue = Array.from(values).find((el) => el.textContent.startsWith('OK'));
    expect(goodValue).toHaveClass('clock-good');
  });

  it('renders a progress bar fill sized to the bar percentage', () => {
    const { container } = render(SummaryBlock, { props: { title: 'Work', model: activeModel } });
    const fill = container.querySelector('.stat-progress .stat-progress-fill');
    expect(fill).toBeInTheDocument();
    expect(fill.getAttribute('style')).toContain('64%');
  });

  it('renders every clock line with the clock tone class applied', () => {
    const { container } = render(SummaryBlock, { props: { title: 'Scope', model: activeModel } });
    const clockLine = container.querySelector('.clock-line');
    expect(clockLine).toHaveClass('clock-bad');
    expect(clockLine.textContent).toContain('No customer response in 12 days');
    expect(clockLine.textContent).toContain('second signal line');
  });

  it('renders a frozen block with title + frozenText', () => {
    const { container, getByText } = render(SummaryBlock, {
      props: { title: 'Scope', model: frozenModel },
    });
    const block = container.querySelector('.summary-block');
    expect(block).toHaveClass('frozen');
    expect(getByText('Scope')).toBeInTheDocument();
    expect(getByText(frozenModel.frozenText)).toBeInTheDocument();
  });

  it('renders a dormant block with title + dormantText', () => {
    const { container, getByText } = render(SummaryBlock, {
      props: { title: 'Work', model: dormantModel },
    });
    const block = container.querySelector('.summary-block');
    expect(block).toHaveClass('dormant');
    expect(getByText('Work')).toBeInTheDocument();
    expect(getByText(dormantModel.dormantText)).toBeInTheDocument();
  });

  // 2026-07-28: the card itself IS the link (reversing the 2026-07-09
  // "no block-level links" decision). See jobs-and-tasks.md §9.1a.
  it('renders the card as an anchor carrying model.href, in every temperature', () => {
    for (const [title, model] of [['Scope', activeModel], ['Scope', frozenModel], ['Work', dormantModel]]) {
      const { container, unmount } = render(SummaryBlock, { props: { title, model } });
      const block = container.querySelector('.summary-block');
      expect(block.tagName).toBe('A');
      expect(block.getAttribute('href')).toBe(model.href);
      unmount();
    }
  });

  // The plain-anchor rendering is only valid HTML because the card has no
  // interactive descendants. Adding one silently makes the markup invalid and
  // forces the stretched-link overlay instead — this guards that boundary.
  it('renders no interactive descendants inside the card', () => {
    for (const [title, model] of [['Scope', activeModel], ['Scope', frozenModel], ['Work', dormantModel]]) {
      const { container, unmount } = render(SummaryBlock, { props: { title, model } });
      const block = container.querySelector('.summary-block');
      expect(block.querySelectorAll('a, button, input, select, textarea').length).toBe(0);
      unmount();
    }
  });
});

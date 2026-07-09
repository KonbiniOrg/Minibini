import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render } from '@testing-library/svelte';
import DocSubnav from '@/components/jobs/DocSubnav.svelte';

describe('DocSubnav', () => {
  it('renders one <a> per item with the given href', () => {
    const items = [
      { id: 1, label: 'Estimate', href: '#/jobs/5/estimate', current: false },
      { id: 2, label: 'Invoice', href: '#/jobs/5/invoice', current: false },
    ];
    const { getAllByRole } = render(DocSubnav, { props: { items } });
    const links = getAllByRole('link');
    expect(links).toHaveLength(2);
    expect(links[0]).toHaveAttribute('href', '#/jobs/5/estimate');
    expect(links[0]).toHaveTextContent('Estimate');
    expect(links[1]).toHaveAttribute('href', '#/jobs/5/invoice');
    expect(links[1]).toHaveTextContent('Invoice');
  });

  it('marks the current item with the active class', () => {
    const items = [
      { id: 1, label: 'Estimate', href: '#/jobs/5/estimate', current: true },
      { id: 2, label: 'Invoice', href: '#/jobs/5/invoice', current: false },
    ];
    const { getAllByRole } = render(DocSubnav, { props: { items } });
    const links = getAllByRole('link');
    expect(links[0]).toHaveClass('active');
    expect(links[1]).not.toHaveClass('active');
  });

  it('marks a lone current document active (its chip carries the highlight)', () => {
    const items = [{ id: 1, label: 'EST-1', href: '#/jobs/5/estimate', current: true }];
    const { getAllByRole } = render(DocSubnav, { props: { items } });
    expect(getAllByRole('link')[0]).toHaveClass('active');
  });

  it('renders a pill with status-{status} class when status is given', () => {
    const items = [
      { id: 1, label: 'Estimate', href: '#/jobs/5/estimate', current: false, status: 'draft' },
      { id: 2, label: 'Invoice', href: '#/jobs/5/invoice', current: false, status: 'sent' },
    ];
    const { container } = render(DocSubnav, { props: { items } });
    const pills = container.querySelectorAll('.status-badge');
    expect(pills).toHaveLength(2);
    expect(pills[0]).toHaveClass('status-draft');
    expect(pills[1]).toHaveClass('status-sent');
    expect(pills[0]).toHaveTextContent('draft');
    expect(pills[1]).toHaveTextContent('sent');
  });

  it('renders no pill when status is not given', () => {
    const items = [
      { id: 1, label: 'Estimate', href: '#/jobs/5/estimate', current: false },
      { id: 2, label: 'Invoice', href: '#/jobs/5/invoice', current: false, status: 'sent' },
    ];
    const { container } = render(DocSubnav, { props: { items } });
    const pills = container.querySelectorAll('.status-badge');
    expect(pills).toHaveLength(1);
    expect(pills[0]).toHaveTextContent('sent');
  });

  it('renders nothing when items is empty', () => {
    const { container } = render(DocSubnav, { props: { items: [] } });
    const links = container.querySelectorAll('a');
    expect(links).toHaveLength(0);
  });
});

describe('DocSubnav caret alignment', () => {
  // jsdom has no layout, so stub getBoundingClientRect: the rail link reports a
  // known box (centre at x=80) and everything else a wide band.
  let rail;
  let originalGBCR;
  const rect = (o) => ({ left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0, x: 0, y: 0, toJSON() {}, ...o });

  beforeEach(() => {
    rail = document.createElement('nav');
    rail.className = 'job-nav-rail';
    rail.innerHTML = '<a class="rail-link" data-section="estimate">Estimates</a>';
    document.body.appendChild(rail);
    originalGBCR = Element.prototype.getBoundingClientRect;
    Element.prototype.getBoundingClientRect = function () {
      // Rail link: 60px wide (centre x=80), 28px tall ending at y=34.
      if (this.classList?.contains('rail-link')) {
        return rect({ left: 50, width: 60, right: 110, top: 6, bottom: 34, height: 28 });
      }
      // Band / row / chips: a wide box starting just below the rail.
      return rect({ left: 0, width: 300, right: 300, top: 36, bottom: 60, height: 24 });
    };
  });

  afterEach(() => {
    Element.prototype.getBoundingClientRect = originalGBCR;
    rail.remove();
  });

  it('draws a caret pinned under the centre of its rail section', async () => {
    const items = [
      { id: 1, label: 'v1', href: '#/a', current: false, status: 'superseded' },
      { id: 2, label: 'v2', href: '#/b', current: true, status: 'draft' },
    ];
    const { container } = render(DocSubnav, { props: { items, section: 'estimate' } });
    await vi.waitFor(() => expect(container.querySelector('.doc-subnav-caret')).not.toBeNull());
    const style = container.querySelector('.doc-subnav-caret').getAttribute('style');
    // rail-link centre = 50 + 60/2 = 80
    expect(style).toContain('left: 80px');
    // Raised up into the rail (base on the rail underline), so top is negative.
    const top = parseFloat(style.match(/top:\s*(-?[\d.]+)px/)[1]);
    expect(top).toBeLessThan(0);
  });

  it('draws no caret when its rail section is not present', async () => {
    const items = [{ id: 1, label: 'INV-1', href: '#/a', current: true }];
    const { container } = render(DocSubnav, { props: { items, section: 'invoice' } });
    await new Promise((r) => setTimeout(r, 0));
    expect(container.querySelector('.doc-subnav-caret')).toBeNull();
  });
});

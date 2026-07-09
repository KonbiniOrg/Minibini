import { describe, it, expect } from 'vitest';
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

import { describe, it, expect } from 'vitest';
import { render, within } from '@testing-library/svelte';
import { createRawSnippet } from 'svelte';
import TabHeader from '@/components/TabHeader.svelte';
import EmptyState from '@/components/EmptyState.svelte';

const snippet = (html) => createRawSnippet(() => ({ render: () => html }));

describe('TabHeader', () => {
  it('renders a header with an h2 carrying the given id and title', () => {
    const { container, getByRole } = render(TabHeader, { props: { id: 'tab-x', title: 'Shipments' } });
    const header = container.querySelector('header');
    expect(header).toBeInTheDocument();
    const h2 = getByRole('heading', { level: 2, name: 'Shipments' });
    expect(h2.id).toBe('tab-x');
    expect(header.contains(h2)).toBe(true);
  });

  it('renders badges after the title and actions in a trailing group', () => {
    const { container } = render(TabHeader, {
      props: {
        id: 'tab-x', title: 'Estimate: EST-1-1',
        badges: snippet('<span class="status-badge">draft</span>'),
        actions: snippet('<span><button type="button">Send Email</button></span>'),
      },
    });
    const header = container.querySelector('header');
    const children = [...header.children];
    expect(children[0].tagName).toBe('H2');
    expect(children[1]).toHaveClass('tab-header-badges');
    expect(children[children.length - 1]).toHaveClass('tab-header-actions');
    expect(within(children[children.length - 1]).getByRole('button', { name: 'Send Email' })).toBeInTheDocument();
  });

  it('hides the title visually but keeps it as the labelled h2 when titleHidden', () => {
    const { getByRole } = render(TabHeader, { props: { id: 'tab-x', title: 'Tasks', titleHidden: true } });
    const h2 = getByRole('heading', { level: 2, name: 'Tasks' });
    expect(h2.id).toBe('tab-x');
    expect(h2).toHaveClass('visually-hidden');
  });

  it('omits the badge and action groups when no snippets are given', () => {
    const { container } = render(TabHeader, { props: { id: 'tab-x', title: 'History' } });
    expect(container.querySelector('.tab-header-badges')).toBeNull();
    expect(container.querySelector('.tab-header-actions')).toBeNull();
  });

  it('adds extra classes to the header (doc tabs keep the toolbar vocabulary)', () => {
    const { container } = render(TabHeader, { props: { id: 'tab-x', title: 'T', class: 'toolbar' } });
    expect(container.querySelector('header')).toHaveClass('tab-header', 'toolbar');
  });
});

describe('EmptyState', () => {
  it('renders the sentence and, when given, the action', () => {
    const { getByText, getByRole, container } = render(EmptyState, {
      props: { text: 'No estimates yet. Start one to quote this job.', action: snippet('<span><button type="button">Start Estimate</button></span>') },
    });
    expect(getByText('No estimates yet. Start one to quote this job.')).toBeInTheDocument();
    expect(within(container.querySelector('.empty-state')).getByRole('button', { name: 'Start Estimate' })).toBeInTheDocument();
    expect(getByRole('button', { name: 'Start Estimate' })).toBeInTheDocument();
  });

  it('renders text only when there is no action', () => {
    const { container } = render(EmptyState, { props: { text: 'No history yet.' } });
    expect(container.querySelector('.empty-state-action')).toBeNull();
    expect(container.querySelector('.empty-state p')).toHaveTextContent('No history yet.');
  });
});

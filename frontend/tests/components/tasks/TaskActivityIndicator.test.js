import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import TaskActivityIndicator from '@/components/tasks/TaskActivityIndicator.svelte';

describe('TaskActivityIndicator', () => {
  it('renders the activity label with a dot by default', () => {
    const { getByText, container } = render(TaskActivityIndicator, {
      props: { task: { status: 'in_progress' } },
    });
    expect(getByText('Ongoing')).toBeInTheDocument();
    expect(container.querySelector('.ta-dot')).toBeInTheDocument();
    expect(container.querySelector('.status-badge')).not.toBeInTheDocument();
  });

  it('compact drops the label', () => {
    const { queryByText, container } = render(TaskActivityIndicator, {
      props: { task: { status: 'in_progress' }, compact: true },
    });
    expect(queryByText('Ongoing')).not.toBeInTheDocument();
    expect(container.querySelector('.ta-dot')).toBeInTheDocument();
  });

  it('pill variant wraps the indicator in shared status-badge classes', () => {
    const { getByText, container } = render(TaskActivityIndicator, {
      props: { task: { status: 'blocked' }, pill: true },
    });
    expect(getByText('Blocked')).toBeInTheDocument();
    const pill = container.querySelector('.status-badge');
    expect(pill).toBeInTheDocument();
    expect(pill).toHaveClass('status-blocked');
    expect(container.querySelector('.ta-dot')).toBeInTheDocument();
  });

  it('pill variant keys the badge class off the live activity, not raw status', () => {
    const { getByText, container } = render(TaskActivityIndicator, {
      props: {
        task: { status: 'in_progress', has_active_blep: true },
        pill: true,
      },
    });
    expect(getByText('Working')).toBeInTheDocument();
    expect(container.querySelector('.status-badge')).toHaveClass('status-working');
  });
});

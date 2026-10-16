import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import Harness from './_LoadStateHarness.svelte';

describe('LoadState', () => {
  it('shows the default loading text and no content while loading', () => {
    const { getByText, queryByTestId, container } = render(Harness, { props: { loading: true } });
    expect(getByText('Loading...')).toBeInTheDocument();
    expect(container.querySelector('p.load-state.loading')).toBeTruthy();
    expect(queryByTestId('content')).toBeNull();
  });

  it('uses a custom loadingText', () => {
    const { getByText } = render(Harness, { props: { loading: true, loadingText: 'Searching...' } });
    expect(getByText('Searching...')).toBeInTheDocument();
  });

  it('shows the error as an alert and no content when error is set', () => {
    const { getByRole, queryByTestId, container } = render(Harness, { props: { error: 'Could not load jobs.' } });
    expect(getByRole('alert')).toHaveTextContent('Could not load jobs.');
    expect(container.querySelector('p.load-state.error')).toBeTruthy();
    expect(queryByTestId('content')).toBeNull();
  });

  it('loading wins over a stale error (a reload in progress hides the old error)', () => {
    const { getByText, queryByRole } = render(Harness, { props: { loading: true, error: 'old' } });
    expect(getByText('Loading...')).toBeInTheDocument();
    expect(queryByRole('alert')).toBeNull();
  });

  it('renders children when neither loading nor error', () => {
    const { getByTestId, container } = render(Harness);
    expect(getByTestId('content')).toHaveTextContent('Loaded content');
    expect(container.querySelector('p.load-state')).toBeNull();
  });

  it('treats an empty-string error as no error', () => {
    const { getByTestId } = render(Harness, { props: { error: '' } });
    expect(getByTestId('content')).toBeInTheDocument();
  });
});

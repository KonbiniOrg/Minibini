import { describe, it, expect, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import MessageOverlay from '@/components/MessageOverlay.svelte';
import { showError, showSuccess, clearMessage } from '@/stores/messages.js';

describe('MessageOverlay', () => {
  beforeEach(() => clearMessage());

  it('is empty until a message is raised', () => {
    const { container } = render(MessageOverlay);
    expect(container.querySelector('.error-overlay')).toBeNull();
    expect(container.querySelector('.success-overlay')).toBeNull();
  });

  it('shows an error raised through the store and dismisses on X', async () => {
    const { container, getByLabelText } = render(MessageOverlay);
    showError('Server error (502)');
    await Promise.resolve();
    expect(container.querySelector('.error-overlay-content').textContent)
      .toContain('Server error (502)');
    await fireEvent.click(getByLabelText('Dismiss message'));
    expect(container.querySelector('.error-overlay')).toBeNull();
  });

  it('shows success in the green variant', async () => {
    const { container } = render(MessageOverlay);
    showSuccess('Invoice sent.');
    await Promise.resolve();
    expect(container.querySelector('.success-overlay-content').textContent)
      .toContain('Invoice sent.');
    expect(container.querySelector('.error-overlay')).toBeNull();
  });
});

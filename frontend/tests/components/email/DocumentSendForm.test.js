import { describe, it, expect, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import DocumentSendForm from '@/components/email/DocumentSendForm.svelte';

describe('DocumentSendForm', () => {
  it('submits the composed payload after confirmation', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    const onSubmit = vi.fn();
    const { getByRole } = render(DocumentSendForm, {
      props: { sendDefaults: { to: 'a@b.com', subject: 'S', body: 'B' }, onSubmit },
    });
    await fireEvent.click(getByRole('button', { name: 'Send Email' }));
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
      to: 'a@b.com', cc: '', bcc: '', subject: 'S', body: 'B',
    }));
    confirmSpy.mockRestore();
  });

  it('accepts a comma-separated list of recipients in To', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    const onSubmit = vi.fn();
    const { getByLabelText, getByRole } = render(DocumentSendForm, {
      props: { sendDefaults: { subject: 'S', body: 'B' }, onSubmit },
    });
    await fireEvent.input(getByLabelText('To *'), {
      target: { value: 'a@b.com, c@d.com' },
    });
    await fireEvent.click(getByRole('button', { name: 'Send Email' }));
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
      to: 'a@b.com, c@d.com',
    }));
    confirmSpy.mockRestore();
  });

  it('disables submit when To is empty', () => {
    const { getByRole } = render(DocumentSendForm, { props: { sendDefaults: {}, onSubmit: vi.fn() } });
    expect(getByRole('button', { name: 'Send Email' })).toBeDisabled();
  });

  it('does not submit if the confirm is cancelled', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false);
    const onSubmit = vi.fn();
    const { getByRole } = render(DocumentSendForm, {
      props: { sendDefaults: { to: 'a@b.com' }, onSubmit },
    });
    await fireEvent.click(getByRole('button', { name: 'Send Email' }));
    expect(onSubmit).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });
});

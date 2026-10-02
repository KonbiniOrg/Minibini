import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), patch: vi.fn(), postMultipart: vi.fn(), delete: vi.fn() },
  errorMessage: (e, fallback) =>
    e?.data?.detail || e?.message || fallback || 'Something went wrong.',
}));
vi.mock('@/stores/messages.js', () => ({
  showError: vi.fn(), showSuccess: vi.fn(),
}));

import { api } from '@/lib/api.js';
import { showError } from '@/stores/messages.js';
import DocumentPdfSettings from '@/components/settings/DocumentPdfSettings.svelte';

const LOGO = 'data:image/png;base64,AAAA';

function mockLoad({ settings = {}, logo = '' } = {}) {
  api.get.mockImplementation(async (url) => {
    if (url === '/api/settings/pdf-logo/') return { logo };
    return settings;
  });
}

beforeEach(() => {
  api.get.mockReset();
  api.patch.mockReset();
  api.postMultipart.mockReset();
  api.delete.mockReset();
  showError.mockReset();
  mockLoad();
  api.patch.mockResolvedValue({});
});

describe('DocumentPdfSettings', () => {
  it('loads stored letterhead values and defaults the logo position to left', async () => {
    mockLoad({ settings: { pdf_company_name: 'Neal CNC' } });
    const { findByDisplayValue, getByRole } = render(DocumentPdfSettings);
    expect(await findByDisplayValue('Neal CNC')).toBeInTheDocument();
    expect(getByRole('radio', { name: 'Left' })).toBeChecked();
  });

  it('saves the letterhead keys together', async () => {
    const { findByLabelText, getByRole, findByText } = render(DocumentPdfSettings);
    await fireEvent.input(await findByLabelText('Company name'), { target: { value: 'Neal CNC' } });
    await fireEvent.click(getByRole('radio', { name: 'Right' }));
    await fireEvent.click(getByRole('button', { name: 'Save letterhead' }));
    expect(api.patch).toHaveBeenCalledWith('/api/settings/', {
      pdf_logo_position: 'right',
      pdf_company_name: 'Neal CNC',
      pdf_company_address: '',
      pdf_company_phone: '',
      pdf_company_email: '',
    });
    expect(await findByText('saved')).toBeInTheDocument();
  });

  it('saves one document\'s four text slots together', async () => {
    mockLoad({ settings: { po_pdf_text_below_totals: 'PO terms' } });
    const { findByRole, findByDisplayValue } = render(DocumentPdfSettings);
    expect(await findByDisplayValue('PO terms')).toBeInTheDocument();
    await fireEvent.click(await findByRole('button', { name: 'Save Purchase Order text' }));
    expect(api.patch).toHaveBeenCalledWith('/api/settings/', {
      po_pdf_text_below_header: '',
      po_pdf_text_above_lines: '',
      po_pdf_text_below_totals: 'PO terms',
      po_pdf_text_page_footer: '',
    });
  });

  it('links each document to its preview PDF', async () => {
    const { findByRole } = render(DocumentPdfSettings);
    const link = await findByRole('link', { name: 'Preview Change Order PDF' });
    expect(link).toHaveAttribute('href', '/api/settings/pdf-preview/?document=change_order');
    expect(link).toHaveAttribute('target', '_blank');
  });

  it('uploads a chosen logo and shows it', async () => {
    api.postMultipart.mockResolvedValue({ logo: LOGO });
    const { findByLabelText, getByRole, findByAltText } = render(DocumentPdfSettings);
    const input = await findByLabelText('Logo image');
    const file = new File(['x'], 'logo.png', { type: 'image/png' });
    await fireEvent.change(input, { target: { files: [file] } });
    await fireEvent.click(getByRole('button', { name: 'Upload logo' }));

    expect(api.postMultipart).toHaveBeenCalledTimes(1);
    const [url, fd] = api.postMultipart.mock.calls[0];
    expect(url).toBe('/api/settings/pdf-logo/');
    expect(fd.get('logo')).toBe(file);
    expect(await findByAltText('Current logo')).toHaveAttribute('src', LOGO);
  });

  it('shows a rejected logo\'s error under the file input', async () => {
    api.postMultipart.mockRejectedValue(Object.assign(new Error('Request failed'), {
      status: 400, data: { logo: ['The logo must be a PNG or JPEG image.'] },
    }));
    const { findByLabelText, getByRole, findByText } = render(DocumentPdfSettings);
    const input = await findByLabelText('Logo image');
    await fireEvent.change(input, {
      target: { files: [new File(['x'], 'logo.bmp', { type: 'image/bmp' })] },
    });
    await fireEvent.click(getByRole('button', { name: 'Upload logo' }));
    expect(await findByText('The logo must be a PNG or JPEG image.')).toBeInTheDocument();
  });

  it('removes the stored logo', async () => {
    mockLoad({ logo: LOGO });
    api.delete.mockResolvedValue({ message: 'Logo removed.' });
    const { findByRole, queryByAltText } = render(DocumentPdfSettings);
    await fireEvent.click(await findByRole('button', { name: 'Remove logo' }));
    expect(api.delete).toHaveBeenCalledWith('/api/settings/pdf-logo/');
    await vi.waitFor(() => expect(queryByAltText('Current logo')).toBeNull());
  });

  it('shows a field-keyed save error in the letterhead footer', async () => {
    api.patch.mockRejectedValueOnce(Object.assign(new Error('Request failed'), {
      status: 400, data: { pdf_logo_position: ['Must be one of: left, center, right.'] },
    }));
    const { findByRole } = render(DocumentPdfSettings);
    await fireEvent.click(await findByRole('button', { name: 'Save letterhead' }));
    expect(await findByRole('alert')).toHaveTextContent('Must be one of: left, center, right.');
  });

  it('routes an infrastructure failure to the overlay', async () => {
    api.patch.mockRejectedValueOnce(Object.assign(new Error('Server error (502)'), {
      status: 502, data: null,
    }));
    const { findByRole } = render(DocumentPdfSettings);
    await fireEvent.click(await findByRole('button', { name: 'Save letterhead' }));
    await vi.waitFor(() => expect(showError).toHaveBeenCalledWith('Server error (502)'));
  });
});

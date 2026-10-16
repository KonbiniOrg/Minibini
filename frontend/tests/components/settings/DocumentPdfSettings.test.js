import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, within, waitFor } from '@testing-library/svelte';
import { tick } from 'svelte';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), postMultipart: vi.fn(), delete: vi.fn() },
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
const PREVIEW_URL = '/api/settings/pdf-preview/';
const PDF = 'data:application/pdf;base64,JVBERi0=';
const page = (label) => `data:image/png;base64,${btoa(label)}`;

// The rich-text fields are Tiptap editors (`textbox.editor`); jsdom can't
// type into a contenteditable, so "typing" replaces the editor's content.
async function typeRich(textbox, text) {
  textbox.editor.commands.setContent(`<p>${text}</p>`);
  await tick();
}
const richHtml = (textbox) => textbox.editor.getHTML();

// Previews requested for one document kind, in call order.
const previewCalls = (kind) =>
  api.post.mock.calls.filter(([url, body]) => url === PREVIEW_URL && body.document === kind);

// Each preview answers with one page image naming its document and the
// below-totals draft it was rendered from.
function mockPreviews() {
  api.post.mockImplementation(async (url, body) => ({
    pages: [page(`${body.document}:${body.values[`${body.document}_pdf_text_below_totals`]}`)],
    pdf: PDF,
  }));
}

function mockLoad({ settings = {}, logo = '' } = {}) {
  api.get.mockImplementation(async (url) => {
    if (url === '/api/settings/pdf-logo/') return { logo };
    return settings;
  });
}

beforeEach(() => {
  api.get.mockReset();
  api.patch.mockReset();
  api.post.mockReset();
  api.postMultipart.mockReset();
  api.delete.mockReset();
  showError.mockReset();
  mockLoad();
  mockPreviews();
  api.patch.mockResolvedValue({});
  URL.createObjectURL = vi.fn(() => 'blob:preview');
  URL.revokeObjectURL = vi.fn();
});

describe('DocumentPdfSettings', () => {
  it('loads stored letterhead values and defaults the logo position to left', async () => {
    mockLoad({ settings: { pdf_company_name: '<p>Neal CNC</p>' } });
    const { findByRole, getByRole } = render(DocumentPdfSettings);
    const name = await findByRole('textbox', { name: 'Company name' });
    await waitFor(() => expect(richHtml(name)).toBe('<p>Neal CNC</p>'));
    expect(getByRole('radio', { name: 'Left' })).toBeChecked();
  });

  it('shows a load failure through the standard error text', async () => {
    api.get.mockRejectedValue(Object.assign(new Error('Request failed'), {
      status: 403, data: { detail: 'You do not have permission to perform this action.' },
    }));
    const { findByRole, queryByRole } = render(DocumentPdfSettings);
    expect(await findByRole('alert'))
      .toHaveTextContent('You do not have permission to perform this action.');
    expect(queryByRole('group', { name: 'Letterhead' })).toBeNull();
  });

  it('saves the letterhead keys together', async () => {
    const { findByLabelText, getByRole, findByText } = render(DocumentPdfSettings);
    await typeRich(await findByLabelText('Company name'), 'Neal CNC');
    await fireEvent.click(getByRole('radio', { name: 'Right' }));
    await fireEvent.click(getByRole('button', { name: 'Save letterhead' }));
    expect(api.patch).toHaveBeenCalledWith('/api/settings/', {
      pdf_logo_position: 'right',
      pdf_company_name: '<p>Neal CNC</p>',
      pdf_company_address: '',
      pdf_company_phone: '',
      pdf_company_email: '',
    });
    expect(await findByText('saved')).toBeInTheDocument();
  });

  it('saves one document\'s four text slots together', async () => {
    mockLoad({ settings: { po_pdf_text_below_totals: '<p>PO terms</p>' } });
    const { findByRole } = render(DocumentPdfSettings);
    const po = await findByRole('group', { name: 'Purchase Order' });
    await waitFor(() => expect(
      richHtml(within(po).getByRole('textbox', { name: 'Below the totals' })),
    ).toBe('<p>PO terms</p>'));
    await fireEvent.click(await findByRole('button', { name: 'Save Purchase Order text' }));
    expect(api.patch).toHaveBeenCalledWith('/api/settings/', {
      po_pdf_text_below_header: '',
      po_pdf_text_above_lines: '',
      po_pdf_text_below_totals: '<p>PO terms</p>',
      po_pdf_text_page_footer: '',
    });
  });

  it('saves toolbar formatting as rich text', async () => {
    const { findByRole } = render(DocumentPdfSettings);
    const estimate = await findByRole('group', { name: 'Estimate' });
    const footer = within(estimate).getByRole('textbox', { name: 'Page footer' });
    await typeRich(footer, 'Page {page}');
    footer.editor.commands.selectAll();
    const toolbar = within(estimate).getByRole('toolbar', { name: 'Page footer formatting' });
    await fireEvent.click(within(toolbar).getByRole('button', { name: 'Bold' }));
    await fireEvent.change(within(toolbar).getByRole('combobox', { name: 'Text size' }),
      { target: { value: 'size-small' } });
    await fireEvent.click(within(estimate).getByRole('button', { name: 'Save Estimate text' }));
    expect(api.patch.mock.calls[0][1].estimate_pdf_text_page_footer)
      .toBe('<p><strong><span class="size-small">Page {page}</span></strong></p>');
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

  describe('live preview', () => {
    const draftsFor = (kind, overrides = {}) => ({
      pdf_logo_position: 'left',
      pdf_company_name: '',
      pdf_company_address: '',
      pdf_company_phone: '',
      pdf_company_email: '',
      [`${kind}_pdf_text_below_header`]: '',
      [`${kind}_pdf_text_above_lines`]: '',
      [`${kind}_pdf_text_below_totals`]: '',
      [`${kind}_pdf_text_page_footer`]: '',
      ...overrides,
    });

    it('previews each document beside its form once loaded', async () => {
      mockLoad({ settings: { po_pdf_text_below_totals: '<p>PO terms</p>' } });
      const { findByAltText } = render(DocumentPdfSettings, { previewDelay: 0 });
      expect(await findByAltText('Estimate preview, page 1'))
        .toHaveAttribute('src', page('estimate:'));
      expect(await findByAltText('Change Order preview, page 1'))
        .toHaveAttribute('src', page('change_order:'));
      expect(await findByAltText('Purchase Order preview, page 1'))
        .toHaveAttribute('src', page('po:<p>PO terms</p>'));
      expect(previewCalls('po')[0][1]).toEqual({
        document: 'po', values: draftsFor('po', { po_pdf_text_below_totals: '<p>PO terms</p>' }),
      });
    });

    it('re-renders a document\'s preview from unsaved typing without saving', async () => {
      const { findByAltText, findAllByLabelText } = render(DocumentPdfSettings, { previewDelay: 0 });
      await findByAltText('Estimate preview, page 1');
      const [estimateTotals] = await findAllByLabelText('Below the totals');
      await typeRich(estimateTotals, 'Draft terms');
      await vi.waitFor(async () => expect(await findByAltText('Estimate preview, page 1'))
        .toHaveAttribute('src', page('estimate:<p>Draft terms</p>')));
      expect(previewCalls('estimate').at(-1)[1]).toEqual({
        document: 'estimate',
        values: draftsFor('estimate', { estimate_pdf_text_below_totals: '<p>Draft terms</p>' }),
      });
      expect(api.patch).not.toHaveBeenCalled();
    });

    it('a document\'s edits leave the other previews alone', async () => {
      const { findByAltText, findAllByLabelText } = render(DocumentPdfSettings, { previewDelay: 0 });
      await findByAltText('Purchase Order preview, page 1');
      const before = previewCalls('po').length;
      const [estimateTotals] = await findAllByLabelText('Below the totals');
      await typeRich(estimateTotals, 'Draft terms');
      await vi.waitFor(() => expect(previewCalls('estimate').length).toBe(2));
      expect(previewCalls('po').length).toBe(before);
    });

    it('letterhead edits re-render all three previews', async () => {
      const { findByAltText, findByLabelText } = render(DocumentPdfSettings, { previewDelay: 0 });
      await findByAltText('Purchase Order preview, page 1');
      await typeRich(await findByLabelText('Company name'), 'Draft Co');
      await vi.waitFor(() => {
        for (const kind of ['estimate', 'change_order', 'po']) {
          expect(previewCalls(kind).at(-1)[1].values.pdf_company_name).toBe('<p>Draft Co</p>');
        }
      });
    });

    it('waits for a pause in typing before requesting', async () => {
      const { findByAltText, findAllByLabelText } = render(DocumentPdfSettings, { previewDelay: 50 });
      await findByAltText('Estimate preview, page 1');
      const [estimateTotals] = await findAllByLabelText('Below the totals');
      for (const value of ['D', 'Dr', 'Dra']) {
        await typeRich(estimateTotals, value);
      }
      await vi.waitFor(() => expect(previewCalls('estimate').length).toBe(2));
      await new Promise((r) => setTimeout(r, 100));
      expect(previewCalls('estimate').length).toBe(2);
      expect(previewCalls('estimate')[1][1].values.estimate_pdf_text_below_totals).toBe('<p>Dra</p>');
    });

    it('ignores a slow response that a newer one already replaced', async () => {
      let releaseFirst;
      const { findByAltText, findAllByLabelText } = render(DocumentPdfSettings, { previewDelay: 0 });
      await findByAltText('Estimate preview, page 1');
      api.post.mockImplementationOnce((url, body) => new Promise((resolve) => {
        releaseFirst = () => resolve({ pages: [page('estimate:stale')], pdf: PDF });
      }));
      const [estimateTotals] = await findAllByLabelText('Below the totals');
      await typeRich(estimateTotals, 'first');
      await vi.waitFor(() => expect(releaseFirst).toBeTypeOf('function'));
      await typeRich(estimateTotals, 'second');
      await vi.waitFor(async () => expect(await findByAltText('Estimate preview, page 1'))
        .toHaveAttribute('src', page('estimate:<p>second</p>')));
      releaseFirst();
      await new Promise((r) => setTimeout(r, 20));
      expect(await findByAltText('Estimate preview, page 1'))
        .toHaveAttribute('src', page('estimate:<p>second</p>'));
    });

    it('previews the letterhead beside its form from the letterhead drafts alone', async () => {
      mockLoad({ settings: { pdf_company_name: '<p>Neal CNC</p>' } });
      const { findByRole } = render(DocumentPdfSettings, { previewDelay: 0 });
      const letterhead = await findByRole('group', { name: 'Letterhead' });
      expect(await within(letterhead).findByAltText('Letterhead preview, page 1'))
        .toHaveAttribute('src', page('letterhead:undefined'));
      expect(previewCalls('letterhead')[0][1]).toEqual({
        document: 'letterhead',
        values: {
          pdf_logo_position: 'left',
          pdf_company_name: '<p>Neal CNC</p>',
          pdf_company_address: '',
          pdf_company_phone: '',
          pdf_company_email: '',
        },
      });
      expect(within(letterhead).getByRole('link', { name: 'Open the Letterhead preview PDF' }))
        .toHaveAttribute('target', '_blank');
    });

    it('letterhead edits re-render the letterhead preview; document edits do not', async () => {
      const { findByAltText, findByLabelText, findAllByLabelText } =
        render(DocumentPdfSettings, { previewDelay: 0 });
      await findByAltText('Letterhead preview, page 1');
      await typeRich(await findByLabelText('Company name'), 'Draft Co');
      await vi.waitFor(() => expect(previewCalls('letterhead').at(-1)[1].values.pdf_company_name)
        .toBe('<p>Draft Co</p>'));
      const before = previewCalls('letterhead').length;
      const [estimateTotals] = await findAllByLabelText('Below the totals');
      await typeRich(estimateTotals, 'Draft terms');
      await vi.waitFor(() => expect(previewCalls('estimate').at(-1)[1]
        .values.estimate_pdf_text_below_totals).toBe('<p>Draft terms</p>'));
      expect(previewCalls('letterhead').length).toBe(before);
    });

    it('says so when the letterhead would print nothing', async () => {
      api.post.mockImplementation(async (url, body) => ({
        pages: body.document === 'letterhead' ? [] : [page(body.document)], pdf: PDF,
      }));
      const { findByRole } = render(DocumentPdfSettings, { previewDelay: 0 });
      const letterhead = await findByRole('group', { name: 'Letterhead' });
      expect(await within(letterhead).findByText(
        'Nothing set — the letterhead is left off every document.')).toBeInTheDocument();
      expect(within(letterhead).queryByText(/Rendering preview/)).toBeNull();
    });

    it('re-renders the previews when the logo changes', async () => {
      api.postMultipart.mockResolvedValue({ logo: LOGO });
      const { findByAltText, findByLabelText, getByRole } = render(DocumentPdfSettings, { previewDelay: 0 });
      await findByAltText('Purchase Order preview, page 1');
      const before = previewCalls('po').length;
      await fireEvent.change(await findByLabelText('Logo image'), {
        target: { files: [new File(['x'], 'logo.png', { type: 'image/png' })] },
      });
      await fireEvent.click(getByRole('button', { name: 'Upload logo' }));
      await vi.waitFor(() => expect(previewCalls('po').length).toBe(before + 1));
    });

    it('opens the full-size preview PDF in a new tab', async () => {
      const { findByRole } = render(DocumentPdfSettings, { previewDelay: 0 });
      const link = await findByRole('link', { name: 'Open the Change Order preview PDF' });
      await vi.waitFor(() => expect(link).toHaveAttribute('href', 'blob:preview'));
      expect(link).toHaveAttribute('target', '_blank');
      const blob = URL.createObjectURL.mock.calls[0][0];
      expect(blob.type).toBe('application/pdf');
    });

    it('shows a preview failure inside that document\'s preview', async () => {
      api.post.mockImplementation(async (url, body) => {
        if (body.document === 'po') {
          throw Object.assign(new Error('Request failed'), {
            status: 400, data: { values: ['Cannot preview: units_list.'] },
          });
        }
        return { pages: [page(body.document)], pdf: PDF };
      });
      const { findByRole } = render(DocumentPdfSettings, { previewDelay: 0 });
      const po = await findByRole('group', { name: 'Purchase Order' });
      await vi.waitFor(() =>
        expect(within(po).getByRole('alert')).toHaveTextContent('Cannot preview: units_list.'));
      expect(showError).not.toHaveBeenCalled();
    });
  });
});

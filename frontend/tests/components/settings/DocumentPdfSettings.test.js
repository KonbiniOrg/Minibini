import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, within, waitFor } from '@testing-library/svelte';
import { tick } from 'svelte';

vi.mock('@/lib/api.js', () => ({
  api: {
    get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(),
    postMultipart: vi.fn(), delete: vi.fn(),
  },
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
const KINDS = ['estimate', 'change_order', 'po'];

const CATALOG = {
  blocks: [
    { type: 'logo', label: 'Logo', settings: { align: 'left' }, single: false, required: false },
    { type: 'company_name', label: 'Company name', settings: { align: 'left' }, single: false, required: false },
    { type: 'text', label: 'Text', settings: { align: 'left', html: '' }, single: false, required: false },
    { type: 'spacer', label: 'Spacer', settings: { orientation: 'vertical', size: 'medium', side: 'left' }, single: false, required: false },
    { type: 'title', label: 'Title', settings: { align: 'left' }, single: true, required: false },
    { type: 'line_items', label: 'Line items', settings: {}, single: true, required: true },
  ],
  presets: [{ key: 'full', widths: [100] }, { key: '1/2-1/2', widths: [50, 50] }],
  default_heading: 'Sample title',
};
const PARTS = {
  blocks: {
    title: '<h1>Sample title</h1>',
    title_number: '<h2>Sample number</h2>',
    details: '<div class="header-info">Sample details</div>',
    line_items: '<table class="lines"><tbody><tr><td>Sample line</td></tr></tbody></table>',
  },
  stylesheet: '.pdf-page table.lines { width: 100%; }',
};
const DEFAULT = {
  version: 1,
  rows: [
    { columns: 'full', cells: [[{ type: 'title', align: 'left' }]] },
    { columns: 'full', cells: [[{ type: 'line_items' }]] },
  ],
};
const withText = (html) => ({
  version: 1,
  rows: [...DEFAULT.rows, { columns: 'full', cells: [[{ type: 'text', align: 'left', html }]] }],
});

// The rich-text fields are Tiptap editors (`textbox.editor`); jsdom can't
// type into a contenteditable, so "typing" replaces the editor's content.
async function typeRich(textbox, text) {
  textbox.editor.commands.setContent(`<p>${text}</p>`);
  await tick();
}
const richHtml = (textbox) => textbox.editor.getHTML();

const previewCalls = (kind) =>
  api.post.mock.calls.filter(([url, body]) => url === PREVIEW_URL && body.document === kind);

// Each preview answers with one page image naming its document and the
// row count of the layout it was rendered from.
function mockPreviews() {
  api.post.mockImplementation(async (url, body) => ({
    pages: [page(`${body.document}:${body.layout.rows.length}`)],
    pdf: PDF,
  }));
}

function mockLoad({ settings = {}, logo = '', layouts = {}, images = [] } = {}) {
  api.get.mockImplementation(async (url) => {
    if (url === '/api/settings/pdf-logo/') return { logo };
    const match = url.match(/^\/api\/settings\/pdf-layout\/(\w+)\/$/);
    if (match) {
      return { layout: layouts[match[1]] ?? DEFAULT, default: DEFAULT, catalog: CATALOG };
    }
    if (url.startsWith('/api/settings/pdf-canvas/')) return PARTS;
    if (url === '/api/settings/pdf-images/') return { images };
    return settings;
  });
}

beforeEach(() => {
  for (const fn of Object.values(api)) fn.mockReset();
  showError.mockReset();
  mockLoad();
  mockPreviews();
  api.patch.mockResolvedValue({});
  api.put.mockImplementation(async (url, body) => ({
    layout: body.layout, default: DEFAULT, catalog: CATALOG,
  }));
  URL.createObjectURL = vi.fn(() => 'blob:preview');
  URL.revokeObjectURL = vi.fn();
});

const printView = async (getByRole) => fireEvent.click(getByRole('button', { name: 'Print view' }));

describe('DocumentPdfSettings', () => {
  it('loads the company details and every document\'s layout and canvas', async () => {
    mockLoad({ settings: { pdf_company_name: '<p>Neal CNC</p>' } });
    const { findByRole, getByRole } = render(DocumentPdfSettings);
    const name = await findByRole('textbox', { name: 'Company name' });
    await waitFor(() => expect(richHtml(name)).toBe('<p>Neal CNC</p>'));
    for (const kind of KINDS) {
      expect(api.get).toHaveBeenCalledWith(`/api/settings/pdf-layout/${kind}/`);
      expect(api.get).toHaveBeenCalledWith(`/api/settings/pdf-canvas/${kind}/`);
    }
    expect(getByRole('tab', { name: 'Estimate' })).toHaveAttribute('aria-selected', 'true');
    const page = getByRole('region', { name: 'estimate page' });
    expect(within(page).getByText('Sample title')).toBeInTheDocument();
    expect(within(page).getByText('Sample line')).toBeInTheDocument();
    expect(within(page).getByText('Sample number')).toBeInTheDocument();
  });

  it('keeps Save above the page, not below it', async () => {
    const { findByRole, getByRole } = render(DocumentPdfSettings);
    const page = await findByRole('region', { name: 'estimate page' });
    const save = getByRole('button', { name: 'Save Estimate' });
    // eslint-disable-next-line no-bitwise
    expect(save.compareDocumentPosition(page) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('a company field edited on the page is saved with the document', async () => {
    const layout = { version: 1, rows: [
      { columns: 'full', cells: [[{ type: 'company_name', align: 'left' }]] }, ...DEFAULT.rows] };
    mockLoad({ settings: { pdf_company_name: '<p>Old Co</p>' }, layouts: { estimate: layout } });
    const { findByRole, getByRole, findByText } = render(DocumentPdfSettings);
    await fireEvent.click(await findByRole('button', { name: 'Company name block' }));
    const onPage = within(getByRole('region', { name: 'estimate page' }))
      .getByRole('textbox', { name: 'Company name' });
    onPage.editor.commands.setContent('<p>New Co</p>', { emitUpdate: true });
    await tick();
    expect(await findByText('unsaved changes')).toBeInTheDocument();
    // The Company details form above follows.
    const above = within(getByRole('group', { name: 'Company details' }))
      .getByRole('textbox', { name: 'Company name' });
    await vi.waitFor(() => expect(richHtml(above)).toBe('<p>New Co</p>'));
    await fireEvent.click(getByRole('button', { name: 'Save Estimate' }));
    await vi.waitFor(() => expect(api.patch).toHaveBeenCalledWith('/api/settings/', {
      estimate_pdf_text_page_footer: '',
      pdf_company_name: '<p>New Co</p>',
      pdf_company_address: '',
      pdf_company_phone: '',
      pdf_company_email: '',
    }));
    await vi.waitFor(() => expect(getByRole('tab', { name: 'Estimate' })).toHaveTextContent(/^Estimate$/));
  });

  it('a document save leaves untouched company details alone', async () => {
    const { findByRole, getByRole } = render(DocumentPdfSettings);
    await fireEvent.click(await findByRole('button', { name: 'Save Estimate' }));
    await vi.waitFor(() => expect(api.patch).toHaveBeenCalledWith('/api/settings/', {
      estimate_pdf_text_page_footer: '',
    }));
    expect(getByRole('tab', { name: 'Estimate' })).toBeInTheDocument();
  });

  describe('image library', () => {
    const IMAGE = { id: 'a'.repeat(32), name: 'shop.png', src: 'data:image/png;base64,AAAA' };

    it('lists, adds and removes images', async () => {
      mockLoad({ images: [IMAGE] });
      const added = { id: 'b'.repeat(32), name: 'new.png', src: 'data:image/png;base64,BBBB' };
      api.postMultipart.mockResolvedValue(added);
      api.delete.mockResolvedValue({ message: 'Image removed.' });
      const {
        findByAltText, findByLabelText, findByRole, getByRole, queryByAltText,
      } = render(DocumentPdfSettings);
      const library = await findByRole('group', { name: 'Images' });
      expect(within(library).getByAltText('shop.png')).toHaveAttribute('src', IMAGE.src);
      const file = new File(['x'], 'new.png', { type: 'image/png' });
      await fireEvent.change(await findByLabelText('Add an image'), { target: { files: [file] } });
      expect(api.postMultipart.mock.calls[0][0]).toBe('/api/settings/pdf-images/');
      expect(api.postMultipart.mock.calls[0][1].get('image')).toBe(file);
      expect(await findByAltText('new.png')).toBeInTheDocument();
      await fireEvent.click(getByRole('button', { name: 'Remove shop.png' }));
      expect(api.delete).toHaveBeenCalledWith(`/api/settings/pdf-images/${IMAGE.id}/`);
      await vi.waitFor(() => expect(queryByAltText('shop.png')).toBeNull());
    });

    it('shows a rejected upload under its input', async () => {
      api.postMultipart.mockRejectedValue(Object.assign(new Error('Request failed'), {
        status: 400, data: { image: ['The image must be a PNG or JPEG image.'] },
      }));
      const { findByLabelText, findByText } = render(DocumentPdfSettings);
      await fireEvent.change(await findByLabelText('Add an image'),
        { target: { files: [new File(['x'], 'x.bmp')] } });
      expect(await findByText('The image must be a PNG or JPEG image.')).toBeInTheDocument();
    });
  });

  it('shows a load failure through the standard error text', async () => {
    api.get.mockRejectedValue(Object.assign(new Error('Request failed'), {
      status: 403, data: { detail: 'You do not have permission to perform this action.' },
    }));
    const { findByRole, queryByRole } = render(DocumentPdfSettings);
    expect(await findByRole('alert'))
      .toHaveTextContent('You do not have permission to perform this action.');
    expect(queryByRole('group', { name: 'Company details' })).toBeNull();
  });

  it('saves the company details together', async () => {
    const { findByLabelText, getByRole, findByText } = render(DocumentPdfSettings);
    await typeRich(await findByLabelText('Company name'), 'Neal CNC');
    await fireEvent.click(getByRole('button', { name: 'Save company details' }));
    expect(api.patch).toHaveBeenCalledWith('/api/settings/', {
      pdf_company_name: '<p>Neal CNC</p>',
      pdf_company_address: '',
      pdf_company_phone: '',
      pdf_company_email: '',
    });
    expect(await findByText('saved')).toBeInTheDocument();
  });

  it('draws unsaved company edits on the canvas', async () => {
    const { findByLabelText, getByRole } = render(DocumentPdfSettings);
    await typeRich(await findByLabelText('Company name'), 'Draft Co');
    // The default sample layout has no company block; add one from the palette.
    await fireEvent.click(getByRole('button', { name: 'Add Company name' }));
    expect(within(getByRole('region', { name: 'estimate page' })).getByText('Draft Co'))
      .toBeInTheDocument();
  });

  it('switches documents with the tabs', async () => {
    mockLoad({ layouts: { po: withText('<p>PO terms</p>') } });
    const { findByRole, getByRole, queryByText } = render(DocumentPdfSettings);
    await findByRole('region', { name: 'estimate page' });
    expect(queryByText('PO terms')).toBeNull();
    await fireEvent.click(getByRole('tab', { name: 'Purchase Order' }));
    const page = await findByRole('region', { name: 'po page' });
    expect(within(page).getByText('PO terms')).toBeInTheDocument();
    expect(getByRole('button', { name: 'Save Purchase Order' })).toBeInTheDocument();
  });

  it('saves one document\'s layout and footer', async () => {
    const { findByRole, getByRole, findByText } = render(DocumentPdfSettings);
    await fireEvent.click(await findByRole('tab', { name: 'Change Order' }));
    await fireEvent.click(getByRole('button', { name: 'Add Spacer' }));
    expect(await findByText('unsaved changes')).toBeInTheDocument();
    await fireEvent.click(getByRole('button', { name: 'Edit page footer' }));
    await typeRich(await findByRole('textbox', { name: 'Page footer' }), 'Page {page}');
    await fireEvent.click(getByRole('button', { name: 'Save Change Order' }));

    expect(api.put).toHaveBeenCalledWith('/api/settings/pdf-layout/change_order/', {
      layout: {
        version: 1,
        rows: [...DEFAULT.rows, { columns: 'full', cells: [[{ type: 'spacer', orientation: 'vertical', size: 'medium', side: 'left' }]] }],
      },
    });
    await vi.waitFor(() => expect(api.patch).toHaveBeenCalledWith('/api/settings/', {
      change_order_pdf_text_page_footer: '<p>Page {page}</p>',
    }));
    expect(await findByText('saved')).toBeInTheDocument();
  });

  it('shows "saved" briefly, and new edits mark the layout unsaved again', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const { findByRole, getByRole, findByText, queryByText } = render(DocumentPdfSettings);
      await fireEvent.click(await findByRole('button', { name: 'Save Estimate' }));
      expect(await findByText('saved')).toBeInTheDocument();
      await vi.advanceTimersByTimeAsync(3100);
      expect(queryByText('saved')).toBeNull();

      await fireEvent.click(getByRole('button', { name: 'Save Estimate' }));
      expect(await findByText('saved')).toBeInTheDocument();
      await fireEvent.click(getByRole('button', { name: 'Add Spacer' }));
      expect(await findByText('unsaved changes')).toBeInTheDocument();
      expect(queryByText('saved')).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it('shows a rejected layout\'s errors under the save button', async () => {
    api.put.mockRejectedValueOnce(Object.assign(new Error('Request failed'), {
      status: 400, data: { layout: ['Row 2: line items need a full-width row.'] },
    }));
    const { findByRole } = render(DocumentPdfSettings);
    await fireEvent.click(await findByRole('button', { name: 'Save Estimate' }));
    expect(await findByRole('alert')).toHaveTextContent('Row 2: line items need a full-width row.');
    expect(api.patch).not.toHaveBeenCalled();
  });

  it('routes an infrastructure failure to the overlay', async () => {
    api.patch.mockRejectedValueOnce(Object.assign(new Error('Server error (502)'), {
      status: 502, data: null,
    }));
    const { findByRole } = render(DocumentPdfSettings);
    await fireEvent.click(await findByRole('button', { name: 'Save company details' }));
    await vi.waitFor(() => expect(showError).toHaveBeenCalledWith('Server error (502)'));
  });

  it('resets a layout to the default as an unsaved draft', async () => {
    mockLoad({ layouts: { estimate: withText('<p>Custom</p>') } });
    const { findByText, getByRole, queryByText } = render(DocumentPdfSettings);
    await findByText('Custom');
    await fireEvent.click(getByRole('button', { name: 'Reset to default' }));
    await vi.waitFor(() => expect(queryByText('Custom')).toBeNull());
    expect(await findByText('unsaved changes')).toBeInTheDocument();
    expect(api.put).not.toHaveBeenCalled();
  });

  it('copies another document\'s layout without linking them', async () => {
    mockLoad({ layouts: { estimate: withText('<p>From estimate</p>') } });
    const { findByText, findByRole, getByRole, queryByText } = render(DocumentPdfSettings);
    await findByText('From estimate');
    await fireEvent.click(getByRole('tab', { name: 'Purchase Order' }));
    await findByRole('region', { name: 'po page' });
    await fireEvent.change(getByRole('combobox', { name: 'Copy layout from' }),
      { target: { value: 'estimate' } });
    await fireEvent.click(await findByRole('button', { name: 'Text block' }));
    await fireEvent.click(getByRole('button', { name: 'Remove Text' }));
    await vi.waitFor(() => expect(queryByText('From estimate')).toBeNull());
    await fireEvent.click(getByRole('tab', { name: 'Estimate' }));
    expect(await findByText('From estimate')).toBeInTheDocument();
  });

  it('uploads a chosen logo and shows it', async () => {
    api.postMultipart.mockResolvedValue({ logo: LOGO });
    const { findByLabelText, getByRole, findByAltText } = render(DocumentPdfSettings);
    const input = await findByLabelText('Logo image');
    const file = new File(['x'], 'logo.png', { type: 'image/png' });
    await fireEvent.change(input, { target: { files: [file] } });
    await fireEvent.click(getByRole('button', { name: 'Upload logo' }));

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
    await fireEvent.change(await findByLabelText('Logo image'), {
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

  describe('print view', () => {
    const blankValues = (kind, overrides = {}) => ({
      pdf_company_name: '',
      pdf_company_address: '',
      pdf_company_phone: '',
      pdf_company_email: '',
      [`${kind}_pdf_text_page_footer`]: '',
      ...overrides,
    });

    it('renders nothing server-side while editing the page', async () => {
      const { findByRole } = render(DocumentPdfSettings, { previewDelay: 0 });
      await findByRole('region', { name: 'estimate page' });
      await new Promise((r) => setTimeout(r, 20));
      expect(api.post).not.toHaveBeenCalled();
    });

    it('shows the real PDF of the selected document with its unsaved edits', async () => {
      mockLoad({ settings: { pdf_company_name: '<p>Neal CNC</p>' } });
      const { findByRole, getByRole, findByAltText } = render(DocumentPdfSettings, { previewDelay: 0 });
      await findByRole('region', { name: 'estimate page' });
      await fireEvent.click(getByRole('button', { name: 'Add Spacer' }));
      await printView(getByRole);
      expect(await findByAltText('Estimate preview, page 1'))
        .toHaveAttribute('src', page('estimate:3'));
      expect(previewCalls('estimate').at(-1)[1]).toEqual({
        document: 'estimate',
        values: blankValues('estimate', { pdf_company_name: '<p>Neal CNC</p>' }),
        layout: { ...DEFAULT, rows: [...DEFAULT.rows, { columns: 'full', cells: [[{ type: 'spacer', orientation: 'vertical', size: 'medium', side: 'left' }]] }] },
      });
      expect(api.put).not.toHaveBeenCalled();
      expect(api.patch).not.toHaveBeenCalled();
    });

    it('previews the newly selected document when the tab changes', async () => {
      const { findByRole, getByRole, findByAltText } = render(DocumentPdfSettings, { previewDelay: 0 });
      await findByRole('region', { name: 'estimate page' });
      await printView(getByRole);
      await findByAltText('Estimate preview, page 1');
      await fireEvent.click(getByRole('tab', { name: 'Purchase Order' }));
      expect(await findByAltText('Purchase Order preview, page 1'))
        .toHaveAttribute('src', page('po:2'));
      expect(previewCalls('po')[0][1].values).toEqual(blankValues('po'));
    });

    it('company edits re-render it', async () => {
      const { findByRole, getByRole, findByAltText, findByLabelText } = render(DocumentPdfSettings, { previewDelay: 0 });
      await findByRole('region', { name: 'estimate page' });
      await printView(getByRole);
      await findByAltText('Estimate preview, page 1');
      await typeRich(await findByLabelText('Company name'), 'Draft Co');
      await vi.waitFor(() => expect(previewCalls('estimate').at(-1)[1].values.pdf_company_name)
        .toBe('<p>Draft Co</p>'));
    });

    it('waits for a pause in editing before requesting', async () => {
      const { findByRole, getByRole, findByAltText, findByLabelText } = render(DocumentPdfSettings, { previewDelay: 50 });
      await findByRole('region', { name: 'estimate page' });
      await printView(getByRole);
      await findByAltText('Estimate preview, page 1');
      const name = await findByLabelText('Company name');
      for (const value of ['D', 'Dr', 'Dra']) await typeRich(name, value);
      await vi.waitFor(() => expect(previewCalls('estimate').length).toBe(2));
      await new Promise((r) => setTimeout(r, 100));
      expect(previewCalls('estimate').length).toBe(2);
      expect(previewCalls('estimate')[1][1].values.pdf_company_name).toBe('<p>Dra</p>');
    });

    it('ignores a slow response that a newer one already replaced', async () => {
      let releaseFirst;
      const { findByRole, getByRole, findByAltText, findByLabelText } = render(DocumentPdfSettings, { previewDelay: 0 });
      await findByRole('region', { name: 'estimate page' });
      await printView(getByRole);
      await findByAltText('Estimate preview, page 1');
      api.post.mockImplementationOnce(() => new Promise((resolve) => {
        releaseFirst = () => resolve({ pages: [page('estimate:stale')], pdf: PDF });
      }));
      const name = await findByLabelText('Company name');
      await typeRich(name, 'first');
      await vi.waitFor(() => expect(releaseFirst).toBeTypeOf('function'));
      await typeRich(name, 'second');
      await vi.waitFor(() => expect(previewCalls('estimate').length).toBe(3));
      await new Promise((r) => setTimeout(r, 20));
      releaseFirst();
      await new Promise((r) => setTimeout(r, 20));
      expect(await findByAltText('Estimate preview, page 1'))
        .toHaveAttribute('src', page('estimate:2'));
    });

    it('re-renders when the logo changes', async () => {
      api.postMultipart.mockResolvedValue({ logo: LOGO });
      const { findByRole, getByRole, findByAltText, findByLabelText } = render(DocumentPdfSettings, { previewDelay: 0 });
      await findByRole('region', { name: 'estimate page' });
      await printView(getByRole);
      await findByAltText('Estimate preview, page 1');
      const before = previewCalls('estimate').length;
      await fireEvent.change(await findByLabelText('Logo image'), {
        target: { files: [new File(['x'], 'logo.png', { type: 'image/png' })] },
      });
      await fireEvent.click(getByRole('button', { name: 'Upload logo' }));
      await vi.waitFor(() => expect(previewCalls('estimate').length).toBe(before + 1));
    });

    it('opens the full-size PDF in a new tab', async () => {
      const { findByRole, getByRole } = render(DocumentPdfSettings, { previewDelay: 0 });
      await findByRole('region', { name: 'estimate page' });
      await printView(getByRole);
      const link = await findByRole('link', { name: 'Open the Estimate preview PDF' });
      await vi.waitFor(() => expect(link).toHaveAttribute('href', 'blob:preview'));
      expect(link).toHaveAttribute('target', '_blank');
      expect(URL.createObjectURL.mock.calls[0][0].type).toBe('application/pdf');
    });

    it('shows a failure inside the print view', async () => {
      api.post.mockRejectedValue(Object.assign(new Error('Request failed'), {
        status: 400, data: { layout: ['Row 1: unknown block type "video".'] },
      }));
      const { findByRole, getByRole } = render(DocumentPdfSettings, { previewDelay: 0 });
      await findByRole('region', { name: 'estimate page' });
      await printView(getByRole);
      const pane = await findByRole('region', { name: 'Estimate preview' });
      await vi.waitFor(() => expect(within(pane).getByRole('alert'))
        .toHaveTextContent('Row 1: unknown block type "video".'));
      expect(showError).not.toHaveBeenCalled();
    });

    it('goes back to editing the page', async () => {
      const { findByRole, getByRole, queryByRole } = render(DocumentPdfSettings, { previewDelay: 0 });
      await findByRole('region', { name: 'estimate page' });
      await printView(getByRole);
      expect(queryByRole('region', { name: 'estimate page' })).toBeNull();
      await fireEvent.click(getByRole('button', { name: 'Edit page' }));
      expect(await findByRole('region', { name: 'estimate page' })).toBeInTheDocument();
    });
  });
});

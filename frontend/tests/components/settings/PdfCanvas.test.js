import { describe, it, expect, vi } from 'vitest';
import { render, fireEvent, within } from '@testing-library/svelte';
import { tick } from 'svelte';
import PdfCanvasHarness from '../_PdfCanvasHarness.svelte';

const CATALOG = {
  blocks: [
    { type: 'logo', label: 'Logo', settings: { align: 'left' }, single: false, required: false },
    { type: 'company_name', label: 'Company name', settings: { align: 'left' }, single: false, required: false },
    { type: 'company_phone', label: 'Company phone', settings: { align: 'left' }, single: false, required: false },
    { type: 'text', label: 'Text', settings: { align: 'left', html: '' }, single: false, required: false },
    { type: 'spacer', label: 'Spacer', settings: { orientation: 'vertical', size: 'medium', side: 'left' }, single: false, required: false },
    { type: 'image', label: 'Image', settings: { image: '', align: 'left', size: 'medium' }, single: false, required: false },
    { type: 'title', label: 'Title', settings: { align: 'left', heading: '' }, single: true, required: false },
    { type: 'line_items', label: 'Line items', settings: {}, single: true, required: true },
  ],
  presets: [
    { key: 'full', widths: [100] },
    { key: '1/3-2/3', widths: [33.333, 66.667] },
    { key: '1/2-1/2', widths: [50, 50] },
    { key: '2/3-1/3', widths: [66.667, 33.333] },
    { key: '1/3-1/3-1/3', widths: [33.333, 33.333, 33.334] },
  ],
  default_heading: 'Estimate',
};
const PARTS = {
  blocks: {
    title: '<h1>Estimate</h1><h2>EST-0000</h2>',
    title_number: '<h2>EST-0000</h2>',
    details: '<div class="header-info">Sample Customer Co.</div>',
    line_items: '<table class="lines"><tbody><tr><td>Sample service line</td></tr></tbody></table>',
  },
  stylesheet: '.pdf-page table.lines { width: 100%; }',
};

function sample() {
  return {
    version: 1,
    rows: [
      { columns: '1/2-1/2', cells: [[{ type: 'logo', align: 'left' }],
        [{ type: 'company_name', align: 'right' }, { type: 'company_phone', align: 'right' }]] },
      { columns: 'full', cells: [[{ type: 'title', align: 'left' }]] },
      { columns: 'full', cells: [[{ type: 'line_items' }]] },
      { columns: 'full', cells: [[{ type: 'text', align: 'left', html: '<p>Net 30</p>' }]] },
    ],
  };
}

// Renders the canvas bound (through the harness) to a holder, so tests read
// what it emits.
const IMAGES = [{ id: 'a'.repeat(32), name: 'shop.png', src: 'data:image/png;base64,AAAA' }];

function setup({ layout = sample(), footer = '', company, images = IMAGES, onUploadImage } = {}) {
  const holder = { layout, footer, company: null };
  const result = render(PdfCanvasHarness, {
    props: {
      holder,
      catalog: CATALOG,
      kind: 'estimate',
      parts: PARTS,
      company: company ?? {
        logo: '', company_name: '<p>Neal CNC</p>', company_address: '',
        company_phone: '', company_email: '',
      },
      images,
      onCompany: (type, html) => { holder.company = [type, html]; },
      onUploadImage: onUploadImage ?? (async () => { throw new Error('unused'); }),
    },
  });
  return { ...result, holder };
}

const types = (layout) => layout.rows.map((r) => r.cells.map((c) => c.map((b) => b.type)));

describe('PdfCanvas', () => {
  it('draws the page from the layout, the sample blocks and the company values', () => {
    const { getByRole, getByText, container } = setup();
    const page = getByRole('region', { name: 'estimate page' });
    expect(within(page).getByText('EST-0000')).toBeInTheDocument();
    expect(within(page).getByText('Sample service line')).toBeInTheDocument();
    expect(within(page).getByText('Neal CNC')).toBeInTheDocument();
    expect(within(page).getByText('Net 30')).toBeInTheDocument();
    // Nothing to print yet: placeholders only the canvas draws.
    expect(getByText('Logo — none uploaded')).toBeInTheDocument();
    expect(getByText('Company phone — click to type')).toBeInTheDocument();
    // Column rows are layout tables, as in the PDF; the stylesheet is in.
    expect(container.querySelector('table.layout-row col').style.width).toBe('50%');
    expect(container.querySelector('style').textContent).toContain('.pdf-page table.lines');
  });

  it('selects a block on click and shows its tools', async () => {
    const { getByRole, queryByRole, holder } = setup();
    expect(queryByRole('toolbar', { name: 'Title tools' })).toBeNull();
    await fireEvent.click(getByRole('button', { name: 'Title block' }));
    const tools = getByRole('toolbar', { name: 'Title tools' });
    await fireEvent.click(within(tools).getByRole('button', { name: 'Align block center' }));
    expect(holder.layout.rows[1].cells[0][0]).toEqual({ type: 'title', align: 'center' });
  });

  it('moves the selected block with its arrows, tidying empty rows', async () => {
    const { getByRole, holder } = setup();
    await fireEvent.click(getByRole('button', { name: 'Title block' }));
    await fireEvent.click(getByRole('button', { name: 'Move Title up' }));
    expect(types(holder.layout)).toEqual([
      [['logo', 'title'], ['company_name', 'company_phone']],
      [['line_items']],
      [['text']],
    ]);
    // The selection follows the block.
    expect(getByRole('toolbar', { name: 'Title tools' })).toBeInTheDocument();
  });

  it('removes the selected block with its button or the Delete key', async () => {
    const { getByRole, holder } = setup();
    await fireEvent.click(getByRole('button', { name: 'Company phone block' }));
    await fireEvent.click(getByRole('button', { name: 'Remove Company phone' }));
    expect(types(holder.layout)[0]).toEqual([['logo'], ['company_name']]);
    await fireEvent.click(getByRole('button', { name: 'Logo block' }));
    await fireEvent.keyDown(window, { key: 'Delete' });
    expect(types(holder.layout)[0]).toEqual([['company_name']]);
  });

  it('never removes the line items', async () => {
    const { getByRole, queryByRole, holder } = setup();
    await fireEvent.click(getByRole('button', { name: 'Line items block' }));
    expect(queryByRole('button', { name: 'Remove Line items' })).toBeNull();
    await fireEvent.keyDown(window, { key: 'Delete' });
    expect(types(holder.layout)).toContainEqual([['line_items']]);
  });

  it('adds a palette block as a new row at the end on click', async () => {
    const { getByRole, holder } = setup();
    await fireEvent.click(getByRole('button', { name: 'Add Spacer' }));
    expect(holder.layout.rows.at(-1)).toEqual({
      columns: 'full', cells: [[{ type: 'spacer', orientation: 'vertical', size: 'medium', side: 'left' }]],
    });
    await fireEvent.change(getByRole('combobox', { name: 'Spacer size' }), { target: { value: 'large' } });
    expect(holder.layout.rows.at(-1).cells[0][0].size).toBe('large');
    expect(getByRole('button', { name: 'Add Title' })).toBeDisabled();
  });

  const cellAt = (container, r, c) => container.querySelector(`[data-row="${r}"] [data-cell="${c}"]`);

  function framed() {
    const layout = sample();
    layout.rows[0].cells[1].unshift({ type: 'spacer', orientation: 'vertical', size: 'medium', side: 'left' });
    return layout;
  }

  it('turns a spacer into an indent of its column', async () => {
    const { getByRole, getByText, container, holder } = setup({ layout: framed() });
    await fireEvent.click(getByRole('button', { name: 'Spacer block' }));
    await fireEvent.click(getByRole('button', { name: 'Indent' }));
    await fireEvent.change(getByRole('combobox', { name: 'Spacer size' }), { target: { value: 'large' } });
    expect(holder.layout.rows[0].cells[1][0])
      .toEqual({ type: 'spacer', orientation: 'horizontal', size: 'large', side: 'left' });
    expect(getByText('↔ Indent — left, large')).toBeInTheDocument();
    expect(cellAt(container, 0, 1).style.paddingLeft).toBe('64px');   // 16 gap + 48 indent
  });

  it('sets the column gap from any block in a column row', async () => {
    const { getByRole, queryByRole, container, holder } = setup();
    await fireEvent.click(getByRole('button', { name: 'Title block' }));
    expect(queryByRole('combobox', { name: 'Column gap' })).toBeNull();
    await fireEvent.click(getByRole('button', { name: 'Logo block' }));
    await fireEvent.change(getByRole('combobox', { name: 'Column gap' }), { target: { value: 'large' } });
    expect(holder.layout.rows[0].gap).toBe('large');
    expect(cellAt(container, 0, 1).style.paddingLeft).toBe('32px');
    await fireEvent.change(getByRole('combobox', { name: 'Column gap' }), { target: { value: 'medium' } });
    expect('gap' in holder.layout.rows[0]).toBe(false);
  });

  it('a divider is in the palette but is no block: clicked, it lines the last row', async () => {
    const { getByRole, container, holder } = setup();
    await fireEvent.click(getByRole('button', { name: 'Add Divider' }));
    expect(holder.layout.rows).toHaveLength(4);
    expect(holder.layout.rows[3].line_below).toBe(true);
    expect(container.querySelector('[data-row="3"]').classList.contains('row-line')).toBe(true);
    // The new line is selected, with its tools.
    expect(getByRole('button', { name: 'Line below row 4' })).toHaveAttribute('aria-pressed', 'true');
    expect(getByRole('toolbar', { name: 'Line tools' })).toBeInTheDocument();
  });

  it('drags a divider onto a border: between columns, between blocks', async () => {
    const { getByRole, container, holder } = setup();
    stubGeometry(container);
    const divider = getByRole('button', { name: 'Add Divider' });
    // Onto the right edge of the logo's column: a line between the columns.
    await drag(divider, [0, 0], [10, 10], [280, 50]);
    expect(holder.layout.rows[0].column_lines).toEqual([true]);
    expect(container.querySelector('[data-row="0"] [data-cell="0"]').style.borderRight)
      .toBe('1px solid rgb(51, 51, 51)');
    expect(getByRole('button', { name: 'Line between columns 1 and 2 of row 1' })).toBeInTheDocument();
    // Between the company name and phone (stacked at 0–30 and 30–60).
    stubGeometry(container);
    await drag(divider, [0, 0], [10, 10], [450, 40]);
    expect(holder.layout.rows[0].cells[1][0].line_below).toBe(true);
    expect(holder.layout.rows).toHaveLength(4);   // no block was added
  });

  it('refuses a border that isn\'t one: the top of the page', async () => {
    const { getByRole, container, holder } = setup();
    stubGeometry(container);
    await drag(getByRole('button', { name: 'Add Divider' }), [0, 0], [10, 10], [300, 2]);
    expect(holder.layout).toEqual(sample());
    expect(container.querySelector('.cv-indicator')).toBeNull();
  });

  it('moves a line by dragging it to another border', async () => {
    const layout = sample();
    layout.rows[1].line_below = true;
    const { getByRole, container, holder } = setup({ layout });
    stubGeometry(container);
    await drag(getByRole('button', { name: 'Line below row 2' }), [300, 160], [300, 170], [280, 50]);
    expect(holder.layout.rows[1].line_below).toBeUndefined();
    expect(holder.layout.rows[0].column_lines).toEqual([true]);
  });

  it('selects a line and removes it with its button or the Delete key', async () => {
    const layout = sample();
    layout.rows[1].line_below = true;
    layout.rows[0].cells[1][0].line_below = true;
    const { getByRole, holder } = setup({ layout });
    await fireEvent.click(getByRole('button', { name: 'Line below row 2' }));
    await fireEvent.click(getByRole('button', { name: 'Remove line' }));
    expect(holder.layout.rows[1].line_below).toBeUndefined();
    await fireEvent.click(getByRole('button', { name: 'Line below Company name' }));
    // Selecting the line doesn't select its block.
    expect(getByRole('button', { name: 'Company name block' })).toHaveAttribute('aria-pressed', 'false');
    await fireEvent.keyDown(window, { key: 'Delete' });
    expect(holder.layout).toEqual(sample());
  });

  it('one click on a text block opens it with the caret in place', async () => {
    const { getByRole, findByRole } = setup();
    await fireEvent.click(getByRole('button', { name: 'Text block' }), { clientX: 10, clientY: 10 });
    const box = await findByRole('textbox', { name: 'Text' });
    await vi.waitFor(() => expect(document.activeElement).toBe(box));
  });

  it('edits a company field in place, as the shared value', async () => {
    const { getByRole, findByRole, holder } = setup();
    await fireEvent.click(getByRole('button', { name: 'Company name block' }));
    const box = await findByRole('textbox', { name: 'Company name' });
    await vi.waitFor(() => expect(document.activeElement).toBe(box));
    box.editor.commands.setContent('<p>Neal CNC Ltd</p>', { emitUpdate: true });
    await tick();
    expect(holder.company).toEqual(['company_name', '<p>Neal CNC Ltd</p>']);
    // The layout itself is unchanged: company text isn't stored per document.
    expect(holder.layout).toEqual(sample());
  });

  it('edits the title\'s heading in place; blank prints the document\'s name', async () => {
    const { getByRole, findByRole, holder } = setup();
    expect(within(getByRole('button', { name: 'Title block' })).getByRole('heading', { level: 1 }))
      .toHaveTextContent('Estimate');
    await fireEvent.click(getByRole('button', { name: 'Title block' }));
    const input = await findByRole('textbox', { name: 'Title text' });
    expect(input).toHaveAttribute('placeholder', 'Estimate');
    await vi.waitFor(() => expect(document.activeElement).toBe(input));
    await fireEvent.input(input, { target: { value: 'Quotation' } });
    expect(holder.layout.rows[1].cells[0][0]).toEqual({ type: 'title', align: 'left', heading: 'Quotation' });
    // The sample number still shows under it.
    expect(getByRole('button', { name: 'Title block' })).toHaveTextContent('EST-0000');
  });

  it('places a library image and sizes it', async () => {
    const { getByRole, getByText, container, holder } = setup();
    await fireEvent.click(getByRole('button', { name: 'Add Image' }));
    expect(getByText('Image — choose or upload one in its tools')).toBeInTheDocument();
    await fireEvent.change(getByRole('combobox', { name: 'Image' }), { target: { value: 'a'.repeat(32) } });
    await fireEvent.change(getByRole('combobox', { name: 'Image size' }), { target: { value: 'large' } });
    expect(holder.layout.rows.at(-1).cells[0][0])
      .toEqual({ type: 'image', image: 'a'.repeat(32), align: 'left', size: 'large' });
    const img = container.querySelector('img.image');
    expect(img).toHaveAttribute('src', 'data:image/png;base64,AAAA');
    expect(img.classList.contains('image-large')).toBe(true);
  });

  it('uploads an image from the block\'s tools and places it', async () => {
    const uploaded = { id: 'b'.repeat(32), name: 'new.png', src: 'data:image/png;base64,BBBB' };
    const onUploadImage = vi.fn(async () => uploaded);
    const { getByRole, holder } = setup({ onUploadImage });
    await fireEvent.click(getByRole('button', { name: 'Add Image' }));
    const file = new File(['x'], 'new.png', { type: 'image/png' });
    await fireEvent.change(getByRole('button', { name: 'Image block' }).querySelector('input[type=file]'),
      { target: { files: [file] } });
    await vi.waitFor(() => expect(holder.layout.rows.at(-1).cells[0][0].image).toBe('b'.repeat(32)));
    expect(onUploadImage).toHaveBeenCalledWith(file);
  });

  it('shows an upload failure in the block\'s tools', async () => {
    const onUploadImage = vi.fn(async () => { throw new Error('The image must be a PNG or JPEG image.'); });
    const { getByRole, findByRole } = setup({ onUploadImage });
    await fireEvent.click(getByRole('button', { name: 'Add Image' }));
    await fireEvent.change(getByRole('button', { name: 'Image block' }).querySelector('input[type=file]'),
      { target: { files: [new File(['x'], 'x.bmp')] } });
    expect(await findByRole('alert')).toHaveTextContent('The image must be a PNG or JPEG image.');
  });

  it('edits a text block in place', async () => {
    const { getByRole, findByRole, holder } = setup();
    await fireEvent.click(getByRole('button', { name: 'Text block' }));
    const box = await findByRole('textbox', { name: 'Text' });
    box.editor.commands.setContent('<p>Net 45</p>', { emitUpdate: true });
    await tick();
    expect(holder.layout.rows[3].cells[0][0].html).toBe('<p>Net 45</p>');
  });

  it('edits the page footer in place', async () => {
    const { getByRole, findByRole, holder } = setup();
    await fireEvent.click(getByRole('button', { name: 'Edit page footer' }));
    const box = await findByRole('textbox', { name: 'Page footer' });
    box.editor.commands.setContent('<p>Page {page}</p>', { emitUpdate: true });
    await tick();
    expect(holder.footer).toBe('<p>Page {page}</p>');
  });

  it('snaps a two-column row\'s divider between the supported splits', async () => {
    const { getByRole, holder } = setup();
    const divider = getByRole('slider', { name: 'Row 1 column split' });
    await fireEvent.keyDown(divider, { key: 'ArrowLeft' });
    expect(holder.layout.rows[0].columns).toBe('1/3-2/3');
    await fireEvent.keyDown(divider, { key: 'ArrowLeft' });
    expect(holder.layout.rows[0].columns).toBe('1/3-2/3');
    await fireEvent.keyDown(divider, { key: 'ArrowRight' });
    await fireEvent.keyDown(divider, { key: 'ArrowRight' });
    expect(holder.layout.rows[0].columns).toBe('2/3-1/3');
  });

  // jsdom has no layout: give the page, rows, columns and blocks boxes.
  // Row 1 (letterhead) 0–100, row 2 (title) 120–160, row 3 (lines)
  // 180–300, row 4 (text) 320–360; columns split at x=300 in row 1.
  function stubGeometry(container) {
    const rect = (top, bottom, left = 0, right = 600) => () => ({
      top, bottom, left, right, width: right - left, height: bottom - top, x: left, y: top,
    });
    const page = container.querySelector('.pdf-page');
    page.getBoundingClientRect = rect(0, 400);
    const rowBoxes = [[0, 100], [120, 160], [180, 300], [320, 360]];
    container.querySelectorAll('[data-row]').forEach((row, r) => {
      row.getBoundingClientRect = rect(...rowBoxes[r]);
      row.querySelectorAll('[data-cell]').forEach((cell, c) => {
        const [left, right] = row.querySelectorAll('[data-cell]').length === 2
          ? [[0, 300], [300, 600]][c] : [0, 600];
        cell.getBoundingClientRect = rect(...rowBoxes[r], left, right);
        cell.querySelectorAll(':scope > [data-block]').forEach((block, i) => {
          block.getBoundingClientRect = rect(rowBoxes[r][0] + i * 30, rowBoxes[r][0] + i * 30 + 30, left, right);
        });
      });
    });
  }

  async function drag(el, from, ...to) {
    await fireEvent.pointerDown(el, { button: 0, clientX: from[0], clientY: from[1] });
    for (const [x, y] of to) await fireEvent.pointerMove(window, { clientX: x, clientY: y });
    await fireEvent.pointerUp(window, { clientX: to.at(-1)[0], clientY: to.at(-1)[1] });
  }

  it('drops a dragged block where the indicator shows', async () => {
    const { getByRole, container, holder } = setup();
    stubGeometry(container);

    // Drag the text block (row 4) to the right edge of the title's column.
    const text = getByRole('button', { name: 'Text block' });
    await fireEvent.pointerDown(text, { button: 0, clientX: 300, clientY: 340 });
    await fireEvent.pointerMove(window, { clientX: 300, clientY: 300 });
    await fireEvent.pointerMove(window, { clientX: 590, clientY: 140 });
    expect(container.querySelector('.cv-indicator')).not.toBeNull();
    expect(container.querySelector('.cv-ghost').textContent).toBe('Text');
    await fireEvent.pointerUp(window, { clientX: 590, clientY: 140 });

    expect(holder.layout.rows[1]).toEqual({
      columns: '1/2-1/2',
      cells: [[{ type: 'title', align: 'left' }], [{ type: 'text', align: 'left', html: '<p>Net 30</p>' }]],
    });
    expect(holder.layout.rows).toHaveLength(3);
    expect(container.querySelector('.cv-indicator')).toBeNull();

    // The browser's click after the release lands on the page: it must not
    // deselect the dropped block, nor eat the next real click.
    await fireEvent.click(container.querySelector('.cv-sheet'));
    expect(getByRole('toolbar', { name: 'Text tools' })).toBeInTheDocument();
    await fireEvent.click(getByRole('button', { name: 'Title block' }));
    expect(getByRole('toolbar', { name: 'Title tools' })).toBeInTheDocument();
  });
});

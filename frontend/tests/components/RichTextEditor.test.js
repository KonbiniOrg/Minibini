import { describe, it, expect, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

import RichTextEditor from '@/components/RichTextEditor.svelte';

// Tiptap hangs its Editor on the editable element (`dom.editor`); jsdom can't
// type into a contenteditable, so tests drive the editor through it.
function editorFor(textbox) {
  return textbox.editor;
}

function setup(props = {}) {
  const utils = render(RichTextEditor, { id: 'rte', label: 'Terms', value: '', ...props });
  const textbox = utils.getByRole('textbox', { name: 'Terms' });
  return { ...utils, textbox, editor: editorFor(textbox) };
}

describe('RichTextEditor', () => {
  it('names its textbox by the label and shows the stored value', () => {
    const { editor, textbox } = setup({ value: '<p><strong>Net 30</strong></p>' });
    expect(textbox).toHaveAttribute('aria-multiline', 'true');
    expect(editor.getHTML()).toBe('<p><strong>Net 30</strong></p>');
  });

  it('applies bold, italic and underline to the selection', async () => {
    const { editor, getByRole } = setup({ value: '<p>Terms</p>' });
    for (const [name, tag] of [['Bold', 'strong'], ['Italic', 'em'], ['Underline', 'u']]) {
      editor.commands.selectAll();
      const button = getByRole('button', { name });
      await fireEvent.click(button);
      expect(editor.getHTML()).toContain(`<${tag}>`);
      expect(button).toHaveAttribute('aria-pressed', 'true');
    }
  });

  it('sets one of the size steps, and Normal clears it', async () => {
    const { editor, getByRole } = setup({ value: '<p>Terms</p>' });
    const size = getByRole('combobox', { name: 'Text size' });
    expect([...size.options].map((o) => o.text))
      .toEqual(['Small', 'Normal', 'Large', 'Extra large']);

    editor.commands.selectAll();
    await fireEvent.change(size, { target: { value: 'size-large' } });
    expect(editor.getHTML()).toBe('<p><span class="size-large">Terms</span></p>');

    editor.commands.selectAll();
    await fireEvent.change(size, { target: { value: '' } });
    expect(editor.getHTML()).toBe('<p>Terms</p>');
  });

  it('keeps what the toolbar can make from pasted markup and drops everything else', () => {
    const { editor } = setup();
    editor.commands.setContent(
      '<p style="margin:0"><b style="font-family:Calibri">B</b> <i>I</i> '
      + '<span style="text-decoration: underline">U</span> '
      + '<span style="color:red; font-size:40px">red</span><img src="x.png"><a href="http://x">link</a></p>');
    // No Calibri (not a family the PDF keeps), no font size, no image, no
    // link. (The bare span around U is unwrapped by the server's sanitizer.)
    expect(editor.getHTML()).toBe(
      '<p><strong>B</strong> <em>I</em> <span><u>U</u></span> <span style="color: red;">red</span>link</p>');
  });

  it('reads the stored size steps back', () => {
    const { editor } = setup({ value: '<p><span class="size-xlarge">Big</span></p>' });
    expect(editor.getHTML()).toBe('<p><span class="size-xlarge">Big</span></p>');
  });

  it('a single-line field stays one line', () => {
    const { editor, textbox } = setup({ value: '<p>Neal CNC</p>', singleLine: true });
    expect(textbox).toHaveAttribute('aria-multiline', 'false');
    editor.commands.setTextSelection(3);
    expect(editor.commands.splitBlock()).toBe(false);
    expect(editor.commands.setHardBreak?.() ?? false).toBe(false);
    expect(editor.getHTML()).toBe('<p>Neal CNC</p>');
  });

  it('a multi-line field takes paragraphs and line breaks', () => {
    const { editor } = setup({ value: '<p>a</p>' });
    editor.commands.setContent('<p>a<br>b</p><p>c</p>');
    expect(editor.getHTML()).toBe('<p>a<br>b</p><p>c</p>');
  });

  it('turns the selection into a bulleted or numbered list and back', async () => {
    const { editor, getByRole } = setup({ value: '<p>one</p><p>two</p>' });
    const bullets = getByRole('button', { name: 'Bulleted list' });
    const numbers = getByRole('button', { name: 'Numbered list' });

    editor.commands.selectAll();
    await fireEvent.click(bullets);
    expect(editor.getHTML()).toBe('<ul><li><p>one</p></li><li><p>two</p></li></ul>');
    expect(bullets).toHaveAttribute('aria-pressed', 'true');

    editor.commands.selectAll();
    await fireEvent.click(numbers);
    expect(editor.getHTML()).toBe('<ol><li><p>one</p></li><li><p>two</p></li></ol>');
    expect(numbers).toHaveAttribute('aria-pressed', 'true');
    expect(bullets).toHaveAttribute('aria-pressed', 'false');

    editor.commands.selectAll();
    await fireEvent.click(numbers);
    expect(editor.getHTML()).toBe('<p>one</p><p>two</p>');
  });

  it('reads stored lists back, nesting and start number included', () => {
    const html = '<ol start="3"><li><p>c</p><ul><li><p>d</p></li></ul></li></ol>';
    const { editor } = setup({ value: html });
    expect(editor.getHTML()).toBe(html);
  });

  it('keeps lists from pasted markup', () => {
    const { editor } = setup();
    editor.commands.setContent('<ul style="x"><li>a</li><li><b>b</b></li></ul>');
    expect(editor.getHTML()).toBe('<ul><li><p>a</p></li><li><p><strong>b</strong></p></li></ul>');
  });

  it('a single-line field has no list buttons', () => {
    const { queryByRole } = setup({ value: '<p>Neal CNC</p>', singleLine: true });
    expect(queryByRole('button', { name: 'Bulleted list' })).toBeNull();
    expect(queryByRole('button', { name: 'Numbered list' })).toBeNull();
  });

  it('offers strikethrough, sub- and superscript', async () => {
    const { editor, getByRole } = setup({ value: '<p>H2O</p>' });
    for (const [name, tag] of [['Strikethrough', 's'], ['Subscript', 'sub'], ['Superscript', 'sup']]) {
      editor.commands.selectAll();
      await fireEvent.click(getByRole('button', { name }));
      expect(editor.getHTML()).toContain(`<${tag}>`);
      await fireEvent.click(getByRole('button', { name }));
    }
  });

  it('sets a font family, a text colour and a highlight', async () => {
    const { editor, getByRole } = setup({ value: '<p>Terms</p>' });
    const font = getByRole('combobox', { name: 'Font' });
    expect([...font.options].map((o) => o.value)).toEqual(['', 'sans-serif', 'serif', 'monospace']);
    editor.commands.selectAll();
    await fireEvent.change(font, { target: { value: 'serif' } });
    editor.commands.selectAll();
    await fireEvent.input(getByRole('textbox', { name: 'Terms' }).ownerDocument
      .querySelector('input[aria-label="Text colour"]'), { target: { value: '#cc0000' } });
    editor.commands.selectAll();
    await fireEvent.input(getByRole('textbox', { name: 'Terms' }).ownerDocument
      .querySelector('input[aria-label="Highlight colour"]'), { target: { value: '#ffff00' } });
    const html = editor.getHTML();
    expect(html).toContain('font-family: serif');
    // The DOM normalizes colours to rgb(), which the server keeps too.
    expect(html).toContain('color: rgb(204, 0, 0)');
    expect(html).toContain('background-color: rgb(255, 255, 0)');
  });

  it('aligns paragraphs and clears formatting', async () => {
    const { editor, getByRole } = setup({ value: '<p><strong>Terms</strong></p>' });
    editor.commands.selectAll();
    await fireEvent.click(getByRole('button', { name: 'Align center' }));
    expect(editor.getHTML()).toBe('<p style="text-align: center;"><strong>Terms</strong></p>');
    expect(getByRole('button', { name: 'Align center' })).toHaveAttribute('aria-pressed', 'true');
    editor.commands.selectAll();
    await fireEvent.click(getByRole('button', { name: 'Clear formatting' }));
    expect(editor.getHTML()).toBe('<p>Terms</p>');
  });

  it('undoes and redoes', async () => {
    const { editor, getByRole } = setup({ value: '<p>Terms</p>' });
    editor.commands.selectAll();
    await fireEvent.click(getByRole('button', { name: 'Bold' }));
    await fireEvent.click(getByRole('button', { name: 'Undo' }));
    expect(editor.getHTML()).toBe('<p>Terms</p>');
    await fireEvent.click(getByRole('button', { name: 'Redo' }));
    expect(editor.getHTML()).toBe('<p><strong>Terms</strong></p>');
  });

  it('has no link or HTML tools', () => {
    const { queryByRole } = setup();
    expect(queryByRole('button', { name: /link/i })).toBeNull();
    expect(queryByRole('button', { name: /html|source/i })).toBeNull();
  });

  it('focuses itself when asked, so one click opens it ready to type', async () => {
    const { textbox } = setup({ value: '<p>Terms</p>', focusAt: { x: 0, y: 0 } });
    await vi.waitFor(() => expect(document.activeElement).toBe(textbox));
  });

  it('does not take focus unless asked', async () => {
    const { textbox } = setup({ value: '<p>Terms</p>' });
    await new Promise((r) => setTimeout(r, 30));
    expect(document.activeElement).not.toBe(textbox);
  });

  it('follows a new value from the parent', async () => {
    const { editor, rerender } = setup({ value: '<p>old</p>' });
    await rerender({ value: '<p>new</p>' });
    expect(editor.getHTML()).toBe('<p>new</p>');
  });
});

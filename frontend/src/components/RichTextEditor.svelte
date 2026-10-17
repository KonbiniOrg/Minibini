<script>
  import { onMount, onDestroy } from 'svelte';
  import { Editor } from '@tiptap/core';
  import Document from '@tiptap/extension-document';
  import Paragraph from '@tiptap/extension-paragraph';
  import Text from '@tiptap/extension-text';
  import Bold from '@tiptap/extension-bold';
  import Italic from '@tiptap/extension-italic';
  import Underline from '@tiptap/extension-underline';
  import Strike from '@tiptap/extension-strike';
  import Subscript from '@tiptap/extension-subscript';
  import Superscript from '@tiptap/extension-superscript';
  import { TextStyle, Color, BackgroundColor } from '@tiptap/extension-text-style';
  import TextAlign from '@tiptap/extension-text-align';
  import HardBreak from '@tiptap/extension-hard-break';
  import { BulletList, OrderedList, ListItem } from '@tiptap/extension-list';
  import { UndoRedo } from '@tiptap/extensions';
  import {
    ALIGNMENTS, AllowedFontFamily, FONT_FAMILIES, SIZES, TextSize,
  } from '../lib/richText.js';

  // A rich-text box with the usual formatting toolbar: bold / italic /
  // underline / strikethrough, sub- / superscript, four size steps, font
  // family, text colour, highlight, paragraph alignment, bulleted /
  // numbered lists (Tab / Shift-Tab nest and un-nest an item; "- " or "1. "
  // at a line start begins one), clear formatting, undo / redo. Nothing
  // that links or embeds: no links, images or raw HTML. Pasted formatting
  // keeps only what the toolbar can make (Tiptap's schema drops the rest).
  // The value is HTML; the server re-sanitizes it against the same
  // allowlist (apps/core/rich_text.py), so this editor is a convenience,
  // not the safety boundary.
  //
  // singleLine: one paragraph, Enter does nothing, no lists (company name /
  // phone / email).
  // focusAt: focus the editor once it's created — at the text under
  // {x, y} (viewport coordinates of the click that opened it), or at the
  // end — so a click that opens an in-place editor also places the caret.
  let { id, label, value = $bindable(''), singleLine = false, focusAt = null } = $props();

  let element;
  let editor = $state(null);
  let tick = $state(0);       // bumped per transaction so toolbar state re-reads
  let lastHtml = '';          // what this editor last emitted, to ignore our own echo

  const labelId = $derived(`${id}-label`);

  // A single-line field is a document of exactly one paragraph, with no
  // hard breaks and Enter swallowed.
  const OneLineDocument = Document.extend({ content: 'paragraph' });
  const NoEnter = Paragraph.extend({
    addKeyboardShortcuts() {
      return { Enter: () => true, 'Shift-Enter': () => true, 'Mod-Enter': () => true };
    },
  });

  onMount(() => {
    editor = new Editor({
      element,
      extensions: [
        singleLine ? OneLineDocument : Document,
        singleLine ? NoEnter : Paragraph,
        Text, Bold, Italic, Underline, Strike, Subscript, Superscript,
        TextSize, TextStyle, Color, BackgroundColor, AllowedFontFamily,
        TextAlign.configure({ types: ['paragraph'] }),
        UndoRedo,
        ...(singleLine ? [] : [HardBreak, BulletList, OrderedList, ListItem]),
      ],
      content: value || '',
      editorProps: {
        attributes: {
          id,
          role: 'textbox',
          'aria-multiline': String(!singleLine),
          'aria-labelledby': labelId,
          class: `rich-input${singleLine ? ' single-line' : ''}`,
        },
      },
      onUpdate: ({ editor: ed }) => {
        lastHtml = ed.getHTML();
        value = lastHtml;
      },
      onTransaction: () => { tick += 1; },
    });
    lastHtml = editor.getHTML();
    if (focusAt) focusEditor(focusAt);
  });

  function focusEditor(at) {
    let pos = null;
    if (at.x !== undefined) {
      try {
        pos = editor.view.posAtCoords({ left: at.x, top: at.y })?.pos ?? null;
      } catch {
        pos = null;   // no layout to measure (e.g. jsdom): fall back to the end
      }
    }
    // No scroll: the editor opened where the user just clicked.
    editor.commands.focus(pos ?? 'end', { scrollIntoView: false });
  }

  // A value set from outside (load, reset) replaces the content.
  $effect(() => {
    const next = value || '';
    if (editor && next !== lastHtml) {
      lastHtml = next;
      editor.commands.setContent(next, { emitUpdate: false });
    }
  });

  onDestroy(() => editor?.destroy());

  function active(name, attrs) {
    tick;
    return editor?.isActive(name, attrs) ?? false;
  }

  function currentSize() {
    tick;
    return editor?.getAttributes('textSize').size ?? '';
  }

  function textStyle(attr) {
    tick;
    return editor?.getAttributes('textStyle')[attr] ?? '';
  }

  // <input type="color"> wants #rrggbb; the editor may hold rgb(...).
  function hex(colour, fallback) {
    const m = /^rgb\((\d+),\s*(\d+),\s*(\d+)\)$/.exec(colour || '');
    if (m) return `#${m.slice(1).map((n) => Number(n).toString(16).padStart(2, '0')).join('')}`;
    return /^#[0-9a-f]{6}$/i.test(colour || '') ? colour : fallback;
  }

  function run(build) {
    if (editor) build(editor.chain().focus()).run();
  }
</script>

<div class="rich-field">
  <strong id={labelId} class="rich-label">{label}</strong>
  <div class="rte-toolbar row-actions" role="toolbar" aria-label={`${label} formatting`}>
    {#each [
      ['bold', 'Bold', 'Bold (Ctrl+B)', 'toggleBold', 'B'],
      ['italic', 'Italic', 'Italic (Ctrl+I)', 'toggleItalic', 'I'],
      ['underline', 'Underline', 'Underline (Ctrl+U)', 'toggleUnderline', 'U'],
      ['strike', 'Strikethrough', 'Strikethrough', 'toggleStrike', 'S'],
      ['subscript', 'Subscript', 'Subscript', 'toggleSubscript', 'x₂'],
      ['superscript', 'Superscript', 'Superscript', 'toggleSuperscript', 'x²'],
    ] as [mark, name, title, command, text] (mark)}
      <button type="button" class={mark} aria-label={name} {title}
              aria-pressed={active(mark)} onmousedown={(e) => e.preventDefault()}
              onclick={() => run((c) => c[command]())}>{text}</button>
    {/each}
    <select aria-label="Text size" value={currentSize()}
            onchange={(e) => run((c) => c.setTextSize(e.currentTarget.value))}>
      {#each SIZES as [cls, name]}
        <option value={cls}>{name}</option>
      {/each}
    </select>
    <select aria-label="Font" value={textStyle('fontFamily')}
            onchange={(e) => run((c) => (e.currentTarget.value
              ? c.setFontFamily(e.currentTarget.value) : c.unsetFontFamily()))}>
      {#each FONT_FAMILIES as [family, name]}
        <option value={family}>{name}</option>
      {/each}
    </select>
    <label class="colour" title="Text colour">
      <span aria-hidden="true">A</span>
      <input type="color" aria-label="Text colour" value={hex(textStyle('color'), '#000000')}
             oninput={(e) => run((c) => c.setColor(e.currentTarget.value))}>
    </label>
    <label class="colour" title="Highlight">
      <span aria-hidden="true" class="highlight-swatch">ab</span>
      <input type="color" aria-label="Highlight colour" value={hex(textStyle('backgroundColor'), '#ffff00')}
             oninput={(e) => run((c) => c.setBackgroundColor(e.currentTarget.value))}>
    </label>
    {#each ALIGNMENTS as [align, name, glyph] (align)}
      <button type="button" aria-label={name} title={name}
              aria-pressed={active({ textAlign: align })} onmousedown={(e) => e.preventDefault()}
              onclick={() => run((c) => c.setTextAlign(align))}>{glyph}</button>
    {/each}
    {#if !singleLine}
      <button type="button" aria-label="Bulleted list" title="Bulleted list"
              aria-pressed={active('bulletList')} onmousedown={(e) => e.preventDefault()}
              onclick={() => run((c) => c.toggleBulletList())}>&bull;&ensp;&#8801;</button>
      <button type="button" aria-label="Numbered list" title="Numbered list"
              aria-pressed={active('orderedList')} onmousedown={(e) => e.preventDefault()}
              onclick={() => run((c) => c.toggleOrderedList())}>1.&ensp;&#8801;</button>
    {/if}
    <button type="button" aria-label="Clear formatting" title="Clear formatting"
            onmousedown={(e) => e.preventDefault()}
            onclick={() => run((c) => c.unsetAllMarks().unsetTextAlign())}>T&#x338;</button>
    <button type="button" aria-label="Undo" title="Undo (Ctrl+Z)" onmousedown={(e) => e.preventDefault()}
            onclick={() => run((c) => c.undo())}>&#x21B6;</button>
    <button type="button" aria-label="Redo" title="Redo (Ctrl+Shift+Z)" onmousedown={(e) => e.preventDefault()}
            onclick={() => run((c) => c.redo())}>&#x21B7;</button>
  </div>
  <div bind:this={element}></div>
</div>

<style>
  /* Buttons and menus take the shared small-button look (.row-actions in
     app.css, which also styles the pressed state); this block only lays
     them out. Not `.toolbar` — that is the banner-page action row. */
  .rich-field { max-width: 720px; }
  .rich-label { display: block; margin-bottom: 2px; }
  .rte-toolbar {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    margin-bottom: 2px;
  }
  .rte-toolbar button { min-width: 24px; }
  .bold { font-weight: bold; }
  .italic { font-style: italic; }
  .underline { text-decoration: underline; }
  .strike { text-decoration: line-through; }
  .colour {
    display: inline-flex;
    align-items: center;
    gap: 1px;
    margin: 0 2px;
    cursor: pointer;
  }
  .colour input { width: 22px; height: 20px; padding: 0; border: none; background: none; cursor: pointer; }
  .highlight-swatch { background: #ff0; padding: 0 2px; }
  /* The editable surface is created by Tiptap, so it is styled globally —
     like the page's other text inputs. */
  :global(.rich-input) {
    border: 1px solid var(--border-control);
    border-radius: 2px;
    padding: 4px 6px;
    min-height: 4.5em;
    font-size: 14px;
    line-height: 1.4;
    background: #fff;
    overflow-wrap: anywhere;
  }
  :global(.rich-input.single-line) { min-height: 0; }
  :global(.rich-input p) { margin: 0; }
  :global(.rich-input ul), :global(.rich-input ol) { margin: 0; padding-left: 1.4em; }
  :global(.rich-input .size-small) { font-size: 0.85em; }
  :global(.rich-input .size-large) { font-size: 1.25em; }
  :global(.rich-input .size-xlarge) { font-size: 1.5em; }
</style>

<script>
  import { onMount, onDestroy } from 'svelte';
  import { Editor } from '@tiptap/core';
  import Document from '@tiptap/extension-document';
  import Paragraph from '@tiptap/extension-paragraph';
  import Text from '@tiptap/extension-text';
  import Bold from '@tiptap/extension-bold';
  import Italic from '@tiptap/extension-italic';
  import Underline from '@tiptap/extension-underline';
  import HardBreak from '@tiptap/extension-hard-break';
  import { BulletList, OrderedList, ListItem } from '@tiptap/extension-list';
  import { UndoRedo } from '@tiptap/extensions';
  import { SIZES, TextSize } from '../lib/richText.js';

  // A small rich-text box: bold / italic / underline, four size steps, and
  // bulleted / numbered lists (Tab / Shift-Tab nest and un-nest an item;
  // "- " or "1. " at a line start begins one), nothing else. Pasted formatting keeps only those marks (Tiptap's schema
  // drops the rest). The value is HTML; the server re-sanitizes it, so this
  // editor is a convenience, not the safety boundary.
  //
  // singleLine: one paragraph, Enter does nothing, no lists (company name /
  // phone / email).
  let { id, label, value = $bindable(''), singleLine = false } = $props();

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
        Text, Bold, Italic, Underline, TextSize, UndoRedo,
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
  });

  // A value set from outside (load, reset) replaces the content.
  $effect(() => {
    const next = value || '';
    if (editor && next !== lastHtml) {
      lastHtml = next;
      editor.commands.setContent(next, { emitUpdate: false });
    }
  });

  onDestroy(() => editor?.destroy());

  function active(name) {
    tick;
    return editor?.isActive(name) ?? false;
  }

  function currentSize() {
    tick;
    return editor?.getAttributes('textSize').size ?? '';
  }

  function toggle(command) {
    editor?.chain().focus()[command]().run();
  }

  function setSize(size) {
    editor?.chain().focus().setTextSize(size).run();
  }
</script>

<div class="rich-field">
  <strong id={labelId} class="rich-label">{label}</strong>
  <div class="rte-toolbar row-actions" role="toolbar" aria-label={`${label} formatting`}>
    <button type="button" class="bold" aria-label="Bold" title="Bold (Ctrl+B)"
            aria-pressed={active('bold')} onmousedown={(e) => e.preventDefault()}
            onclick={() => toggle('toggleBold')}>B</button>
    <button type="button" class="italic" aria-label="Italic" title="Italic (Ctrl+I)"
            aria-pressed={active('italic')} onmousedown={(e) => e.preventDefault()}
            onclick={() => toggle('toggleItalic')}>I</button>
    <button type="button" class="underline" aria-label="Underline" title="Underline (Ctrl+U)"
            aria-pressed={active('underline')} onmousedown={(e) => e.preventDefault()}
            onclick={() => toggle('toggleUnderline')}>U</button>
    {#if !singleLine}
      <button type="button" aria-label="Bulleted list" title="Bulleted list"
              aria-pressed={active('bulletList')} onmousedown={(e) => e.preventDefault()}
              onclick={() => toggle('toggleBulletList')}>&bull;&ensp;&#8801;</button>
      <button type="button" aria-label="Numbered list" title="Numbered list"
              aria-pressed={active('orderedList')} onmousedown={(e) => e.preventDefault()}
              onclick={() => toggle('toggleOrderedList')}>1.&ensp;&#8801;</button>
    {/if}
    <select aria-label="Text size" value={currentSize()}
            onchange={(e) => setSize(e.currentTarget.value)}>
      {#each SIZES as [cls, name]}
        <option value={cls}>{name}</option>
      {/each}
    </select>
  </div>
  <div bind:this={element}></div>
</div>

<style>
  /* Buttons and the size menu take the shared small-button look
     (.row-actions in app.css, which also styles the pressed state); this
     block only lays them out. Not `.toolbar` — that is the banner-page
     action row. */
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

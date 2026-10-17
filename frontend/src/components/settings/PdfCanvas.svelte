<script>
  import { onDestroy } from 'svelte';
  import RichTextEditor from '../RichTextEditor.svelte';
  import PdfCanvasBlock from './PdfCanvasBlock.svelte';
  import {
    LINE_ITEMS, cellStyle, dropBlock, hasLine, insertBlock, isLinesRow, moveBlock, newBlock,
    placeLine, placedCounts, presetsFor, removeBlock, setColumns, setGap, setLine, updateBlock,
  } from '../../lib/pdfLayout.js';
  import { indicatorFor, snapPreset, targetAt } from '../../lib/pdfCanvas.js';

  // One document's PDF layout drawn as its page — A4 with the PDF's margins
  // and stylesheet (`parts.stylesheet`, scoped under .pdf-page) — that the
  // user arranges by dragging blocks on the page itself:
  //
  // - Drag a block (or a palette entry) and an indicator shows where it
  //   lands: a line between blocks (stack), a bar at a column's edge
  //   (beside — a new column), a line between rows (a new row). Drops and
  //   their rules are lib/pdfLayout.js; hit-testing is lib/pdfCanvas.js
  //   over a geometry snapshot measured when the drag starts.
  // - Click a block to select it: a toolbar above it sets alignment,
  //   spacer kind / side / size, an image's picture and size, the row's
  //   column gap, moves it with arrows, removes it. An indent frames its
  //   column (padding, as lib/pdfLayout.js cellStyle and the PDF draw it)
  //   and shows as a small marker. Text edits in place, caret where the
  //   click landed: a text block, the company fields (the shared values,
  //   via onCompany), the title's heading, and the page footer.
  // - Divider lines are not blocks: dragging Divider from the palette (or
  //   an existing line) drops a line on the border under the pointer —
  //   between stacked blocks, between rows, or between two columns. A line
  //   can be clicked to select it, dragged to another border, or removed.
  // - A two-column row's width grip drags (or arrow-keys) between ⅓ / ½ / ⅔.
  //
  // Everything is an unsaved draft in `layout` / `footer`; the parent saves.
  // All of it is reversible, so nothing confirms.
  // images: the shared library [{id, name, src}]; onUploadImage(file)
  // adds one and resolves to it (or rejects with the API error).
  let {
    layout = $bindable(), footer = $bindable(''), catalog, kind, parts, company,
    images = [], onCompany, onUploadImage,
  } = $props();

  const ALIGNMENTS = [['left', 'Left'], ['center', 'Center'], ['right', 'Right']];
  const SIZES = [['small', 'Small'], ['medium', 'Medium'], ['large', 'Large']];
  const SIDES = [['left', 'Left'], ['right', 'Right']];
  const SPACER_KINDS = [['vertical', 'Gap'], ['horizontal', 'Indent']];
  const IMAGE_SIZES = [['small', 'Small (¼)'], ['medium', 'Medium (½)'], ['large', 'Full width']];
  // Blocks whose text edits in place when selected.
  const EDITABLE = new Set(['text', 'title', 'company_name', 'company_address',
    'company_phone', 'company_email']);
  const DRAG_THRESHOLD = 4;

  let pageEl = $state();
  let selected = $state(null);       // {row, cell, index}
  let selectedLine = $state(null);   // a line (lib/pdfLayout.js) — exclusive with `selected`
  let editingFooter = $state(false);
  // Where the click that opened an editor landed (viewport coordinates), or
  // 'end' when opened from the keyboard — the editor puts its caret there.
  let focusPoint = $state(null);
  let uploading = $state(false);
  let uploadError = $state('');
  let drag = $state(null);           // {label, x, y, indicator} while dragging
  let press = null;                  // the pointer press that may become a drag
  // A drag ends with a click on whatever lies under the release point (often
  // the page, which would deselect): the click right after a drag is
  // ignored, wherever it lands. Reset on every press.
  let suppressClick = false;

  const entries = $derived(Object.fromEntries(catalog.blocks.map((e) => [e.type, e])));
  const widths = $derived(Object.fromEntries(catalog.presets.map((p) => [p.key, p.widths])));
  const counts = $derived(placedCounts(layout));
  const palette = $derived(catalog.blocks.filter((e) => e.type !== LINE_ITEMS));
  const selectedBlock = $derived(
    selected ? layout.rows[selected.row]?.cells[selected.cell]?.[selected.index] : null);

  const imagesById = $derived(Object.fromEntries(images.map((image) => [image.id, image])));
  const label = (block) => entries[block.type]?.label ?? block.type;
  const isSelected = (r, c, i) =>
    selected?.row === r && selected?.cell === c && selected?.index === i;

  const sameLine = (a, b) => Boolean(a && b) && JSON.stringify(a) === JSON.stringify(b);
  const lineSelected = (line) => sameLine(line, selectedLine) && hasLine(layout, line);

  function select(pos, at = { end: true }) {
    selected = pos;
    selectedLine = null;
    editingFooter = false;
    focusPoint = at;
    uploadError = '';
  }

  function selectLine(line) {
    selectedLine = line;
    selected = null;
    editingFooter = false;
  }

  function apply(result) {
    if (!result) return;
    layout = result.layout;
    if (result.line) selectLine(result.line);
    else select(result.pos);
  }

  // --- Measuring ------------------------------------------------------------

  function measure() {
    const origin = pageEl.getBoundingClientRect();
    const rel = (el) => {
      const b = el.getBoundingClientRect();
      return {
        top: b.top - origin.top, bottom: b.bottom - origin.top,
        left: b.left - origin.left, right: b.right - origin.left,
      };
    };
    const rows = [...pageEl.querySelectorAll('[data-row]')].map((rowEl, r) => ({
      ...rel(rowEl),
      lines: isLinesRow(layout.rows[r]),
      cells: [...rowEl.querySelectorAll('[data-cell]')].map((cellEl) => ({
        ...rel(cellEl),
        blocks: [...cellEl.querySelectorAll(':scope > [data-block]')].map(rel),
      })),
    }));
    return { rows };
  }

  // --- Dragging blocks --------------------------------------------------------

  // What a drop at `target` would produce, or null when it isn't allowed.
  // A divider (new, or a line being moved) lands on a border.
  function attempt(source, target) {
    if (source.divider) return placeLine(layout, target, source.lineFrom ?? null);
    return source.from
      ? dropBlock(layout, source.from, target)
      : insertBlock(layout, source.block, target);
  }

  function beginPress(e, source) {
    if (e.button !== 0) return;
    suppressClick = false;
    press = { x: e.clientX, y: e.clientY, source, geometry: null, result: null };
    window.addEventListener('pointermove', onPointerMove);
    window.addEventListener('pointerup', onPointerUp);
  }

  function onPointerMove(e) {
    if (!press) return;
    if (!drag) {
      if (Math.hypot(e.clientX - press.x, e.clientY - press.y) < DRAG_THRESHOLD) return;
      press.geometry = measure();
      drag = { label: press.source.label, x: 0, y: 0, indicator: null };
      editingFooter = false;
    }
    e.preventDefault();
    const origin = pageEl.getBoundingClientRect();
    const x = e.clientX - origin.left;
    const y = e.clientY - origin.top;
    const target = targetAt(press.geometry, x, y);
    press.result = attempt(press.source, target);
    drag = {
      ...drag, x, y,
      indicator: press.result ? indicatorFor(press.geometry, target) : null,
    };
  }

  function onPointerUp() {
    window.removeEventListener('pointermove', onPointerMove);
    window.removeEventListener('pointerup', onPointerUp);
    if (drag) {
      suppressClick = true;
      apply(press.result);
    }
    drag = null;
    press = null;
  }

  onDestroy(() => {
    window.removeEventListener('pointermove', onPointerMove);
    window.removeEventListener('pointerup', onPointerUp);
  });

  function pressBlock(e, pos, block) {
    // Typing in a text block, using its toolbar, or grabbing a line is not
    // a drag of the block.
    if (e.target.closest('.rich-field, .cv-toolbar, .cv-line, input')) return;
    beginPress(e, { from: pos, label: label(block) });
  }

  function clickBlock(e, pos) {
    e.stopPropagation();
    if (suppressClick) {
      suppressClick = false;
      return;
    }
    if (e.target.closest('.rich-field, .cv-toolbar, .cv-line, input')) return;
    select(pos, { x: e.clientX, y: e.clientY });
  }

  // A click on empty page deselects — unless it's the tail of a drag.
  function clickPage() {
    if (suppressClick) {
      suppressClick = false;
      return;
    }
    selected = null;
    selectedLine = null;
    editingFooter = false;
  }

  // A palette entry clicked (not dragged) lands as a new row at the end.
  function clickPalette(entry) {
    if (suppressClick) {
      suppressClick = false;
      return;
    }
    apply(insertBlock(layout, newBlock(entry), { kind: 'newRow', index: layout.rows.length }));
  }

  // The Divider clicked (not dragged): a line under the last row.
  function clickDivider() {
    if (suppressClick) {
      suppressClick = false;
      return;
    }
    apply(placeLine(layout, { kind: 'newRow', index: layout.rows.length }));
  }

  // --- Lines -----------------------------------------------------------------

  function pressLine(e, line) {
    e.stopPropagation();
    beginPress(e, { divider: true, lineFrom: line, label: 'Divider' });
  }

  function clickLine(e, line) {
    e.stopPropagation();
    if (suppressClick) {
      suppressClick = false;
      return;
    }
    selectLine(line);
  }

  function removeLine() {
    layout = setLine(layout, selectedLine, false);
    selectedLine = null;
  }

  // Where a column line's handle sits: the boundary, as % of the row.
  function boundaryAt(row, boundary) {
    return (widths[row.columns] ?? []).slice(0, boundary + 1).reduce((sum, w) => sum + w, 0);
  }

  // --- Selected block -----------------------------------------------------------

  function move(direction) {
    apply(moveBlock(layout, selected, direction));
  }

  function remove() {
    layout = removeBlock(layout, selected);
    selected = null;
  }

  function update(changes) {
    layout = updateBlock(layout, selected, changes);
  }

  function setRowGap(gap) {
    layout = setGap(layout, selected.row, gap);
  }

  async function uploadImage(input) {
    const file = input.files?.[0];
    input.value = '';
    if (!file) return;
    const at = selected;
    uploading = true;
    uploadError = '';
    try {
      const image = await onUploadImage(file);
      layout = updateBlock(layout, at, { image: image.id });
    } catch (err) {
      uploadError = err?.message || 'Could not upload the image.';
    } finally {
      uploading = false;
    }
  }

  function onKeydown(e) {
    if (e.target.closest?.('.rich-field, input, select')) return;
    if (e.key === 'Escape') {
      selected = null;
      selectedLine = null;
      editingFooter = false;
    } else if (e.key === 'Delete' || e.key === 'Backspace') {
      if (selectedLine && hasLine(layout, selectedLine)) {
        e.preventDefault();
        removeLine();
      } else if (selectedBlock && selectedBlock.type !== LINE_ITEMS) {
        e.preventDefault();
        remove();
      }
    }
  }

  // --- Column dividers -------------------------------------------------------------

  function pressDivider(e, r) {
    if (e.button !== 0) return;
    e.preventDefault();
    e.stopPropagation();
    suppressClick = false;
    const rowEl = e.currentTarget.parentElement;
    const onMove = (ev) => {
      suppressClick = true;
      const box = rowEl.getBoundingClientRect();
      if (!box.width) return;
      const preset = snapPreset((ev.clientX - box.left) / box.width);
      if (preset !== layout.rows[r].columns) layout = setColumns(layout, r, preset);
    };
    const onUp = () => {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
    };
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
  }

  function dividerKey(e, r) {
    const options = presetsFor(2);
    const at = options.indexOf(layout.rows[r].columns);
    const step = { ArrowLeft: -1, ArrowRight: 1 }[e.key];
    if (!step) return;
    e.preventDefault();
    const next = options[at + step];
    if (next) layout = setColumns(layout, r, next);
  }
</script>

<svelte:window onkeydown={onKeydown} />

{#snippet blockAt(block, r, c, i)}
  {@const pos = { row: r, cell: c, index: i }}
  {@const chosen = isSelected(r, c, i)}
  <div class={`block block-${block.type}${block.align ? ` align-${block.align}` : ''}${block.line_below ? ' line-below' : ''} cv-block`}
       class:cv-selected={chosen}
       data-block={i}
       role="button"
       tabindex="0"
       aria-label={`${label(block)} block`}
       aria-pressed={chosen}
       onpointerdown={(e) => pressBlock(e, pos, block)}
       onclick={(e) => clickBlock(e, pos)}
       onkeydown={(e) => { if (e.key === 'Enter' && e.target === e.currentTarget) select(pos); }}>
    {#if chosen && !drag}
      {@render toolbar(block)}
    {/if}
    <PdfCanvasBlock {block} {parts} {company} images={imagesById}
                    defaultHeading={catalog.default_heading}
                    editing={chosen && EDITABLE.has(block.type) && !drag}
                    focusAt={chosen ? focusPoint : null}
                    id={`${kind}-${block.type}-${r}-${c}-${i}`}
                    onText={(html) => update({ html })}
                    onHeading={(heading) => update({ heading })}
                    {onCompany} />
    {#if block.line_below}
      {@render lineHandle({ kind: 'block', row: r, cell: c, index: i }, 'h', `Line below ${label(block)}`)}
    {/if}
  </div>
{/snippet}

{#snippet lineHandle(line, orient, name, style = '')}
  <div class={`cv-line cv-line-${orient}`} class:cv-line-selected={lineSelected(line)} {style}>
    <button type="button" class="cv-line-hit" aria-label={name} aria-pressed={lineSelected(line)}
            onpointerdown={(e) => pressLine(e, line)} onclick={(e) => clickLine(e, line)}></button>
    {#if lineSelected(line) && !drag}
      <div class="cv-toolbar cv-line-tools row-actions" role="toolbar" aria-label="Line tools">
        <strong>Divider</strong>
        <small>drag to move</small>
        <button type="button" aria-label="Remove line" title="Remove" onclick={removeLine}>&times;</button>
      </div>
    {/if}
  </div>
{/snippet}

{#snippet toolbar(block)}
  {@const name = label(block)}
  <div class="cv-toolbar row-actions" role="toolbar" aria-label={`${name} tools`}>
    <strong>{name}</strong>
    {#if 'align' in block}
      {#each ALIGNMENTS as [value, text] (value)}
        <button type="button" aria-label={`Align block ${text.toLowerCase()}`}
                title={`Align the block ${text.toLowerCase()} (in this document's layout)`}
                aria-pressed={block.align === value} onclick={() => update({ align: value })}>
          {text[0]}
        </button>
      {/each}
    {/if}
    {#if block.type === 'spacer'}
      {#each SPACER_KINDS as [value, text] (value)}
        <button type="button" aria-pressed={block.orientation === value}
                onclick={() => update({ orientation: value })}>{text}</button>
      {/each}
      {#if block.orientation === 'horizontal'}
        {#each SIDES as [value, text] (value)}
          <button type="button" aria-label={`${text} side`} title={`${text} side`}
                  aria-pressed={block.side === value} onclick={() => update({ side: value })}>
            {text[0]}
          </button>
        {/each}
      {/if}
    {/if}
    {#if block.type === 'image'}
      <select aria-label="Image" value={block.image}
              onchange={(e) => update({ image: e.currentTarget.value })}>
        <option value="">Choose an image…</option>
        {#each images as image (image.id)}
          <option value={image.id}>{image.name}</option>
        {/each}
      </select>
      <label class="cv-upload" title="Upload a PNG or JPEG (1 MB max) to the image library">
        {uploading ? 'Uploading…' : 'Upload…'}
        <input type="file" accept="image/png,image/jpeg" aria-label="Upload an image"
               disabled={uploading} onchange={(e) => uploadImage(e.currentTarget)}>
      </label>
      <select aria-label="Image size" value={block.size}
              onchange={(e) => update({ size: e.currentTarget.value })}>
        {#each IMAGE_SIZES as [value, text] (value)}
          <option {value}>{text}</option>
        {/each}
      </select>
      {#if uploadError}<small class="cv-upload-error" role="alert">{uploadError}</small>{/if}
    {/if}
    {#if block.type === 'spacer'}
      <select aria-label="Spacer size" value={block.size}
              onchange={(e) => update({ size: e.currentTarget.value })}>
        {#each SIZES as [value, text] (value)}
          <option {value}>{text}</option>
        {/each}
      </select>
    {/if}
    {#if layout.rows[selected.row].columns !== 'full'}
      <select aria-label="Column gap" title="Space between this row's columns"
              value={layout.rows[selected.row].gap ?? 'medium'}
              onchange={(e) => setRowGap(e.currentTarget.value)}>
        {#each SIZES as [value, text] (value)}
          <option {value}>Gap: {text}</option>
        {/each}
      </select>
    {/if}
    {#each [['up', '↑'], ['down', '↓'], ['left', '←'], ['right', '→']] as [dir, arrow] (dir)}
      <button type="button" aria-label={`Move ${name} ${dir}`} title={`Move ${dir}`}
              disabled={!moveBlock(layout, selected, dir)} onclick={() => move(dir)}>{arrow}</button>
    {/each}
    {#if block.type !== LINE_ITEMS}
      <button type="button" aria-label={`Remove ${name}`} title="Remove" onclick={remove}>&times;</button>
    {/if}
    {#if block.type === 'logo' || block.type.startsWith('company_')}
      <small>Edit under Company details</small>
    {/if}
  </div>
{/snippet}

<div class="cv-wrap">
  <aside class="cv-palette" aria-label="Blocks">
    <p><strong>Blocks</strong><br><small>Drag onto the page, or click to add at the end. A Divider drops onto a border.</small></p>
    {#each palette as entry (entry.type)}
      {@const used = entry.single && counts[entry.type] > 0}
      <button type="button" class="cv-palette-item" disabled={used}
              aria-label={`Add ${entry.label}`}
              onpointerdown={(e) => { if (!used) beginPress(e, { block: newBlock(entry), label: entry.label }); }}
              onclick={() => clickPalette(entry)}>
        {entry.label}
      </button>
    {/each}
    <button type="button" class="cv-palette-item" aria-label="Add Divider"
            title="A line on a border: between blocks, rows or columns"
            onpointerdown={(e) => beginPress(e, { divider: true, label: 'Divider' })}
            onclick={clickDivider}>
      Divider
    </button>
  </aside>

  <div class="cv-scroll">
    {@html `<style>${parts.stylesheet}</style>`}
    <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
    <div class="cv-sheet" class:dragging={drag}
         onclick={clickPage}>
      <div class="pdf-page" bind:this={pageEl} role="region" aria-label={`${kind} page`}>
        {#each layout.rows as row, r (r)}
          {#if row.columns === 'full'}
            <div class="layout-flow" class:row-line={row.line_below} data-row={r}>
              <div class="cv-cell" data-cell={0} style={cellStyle(row, 0)}>
                {#each row.cells[0] as block, i (i)}
                  {@render blockAt(block, r, 0, i)}
                {/each}
              </div>
              {#if row.line_below}
                {@render lineHandle({ kind: 'row', row: r }, 'h', `Line below row ${r + 1}`)}
              {/if}
            </div>
          {:else}
            <div class="cv-row" data-row={r}>
              <table class="layout-row" class:row-line={row.line_below}>
                <colgroup>
                  {#each widths[row.columns] ?? [] as width, w (w)}<col style:width={`${width}%`}>{/each}
                </colgroup>
                <tbody><tr>
                  {#each row.cells as cell, c (c)}
                    <td class="layout-cell" data-cell={c} style={cellStyle(row, c)}>
                      {#each cell as block, i (i)}
                        {@render blockAt(block, r, c, i)}
                      {/each}
                    </td>
                  {/each}
                </tr></tbody>
              </table>
              {#each row.column_lines ?? [] as on, boundary (boundary)}
                {#if on}
                  {@render lineHandle({ kind: 'column', row: r, boundary }, 'v',
                    `Line between columns ${boundary + 1} and ${boundary + 2} of row ${r + 1}`,
                    `left: ${boundaryAt(row, boundary)}%`)}
                {/if}
              {/each}
              {#if row.line_below}
                {@render lineHandle({ kind: 'row', row: r }, 'h', `Line below row ${r + 1}`)}
              {/if}
              {#if row.cells.length === 2}
                <div class="cv-divider" role="slider" tabindex="0"
                     aria-label={`Row ${r + 1} column split`}
                     aria-valuemin={33} aria-valuemax={67}
                     aria-valuenow={Math.round((widths[row.columns] ?? [50])[0])}
                     aria-valuetext={row.columns}
                     style:left={`${(widths[row.columns] ?? [50])[0]}%`}
                     onpointerdown={(e) => pressDivider(e, r)}
                     onclick={(e) => e.stopPropagation()}
                     onkeydown={(e) => dividerKey(e, r)}></div>
              {/if}
            </div>
          {/if}
        {/each}

        {#if drag?.indicator}
          <div class="cv-indicator" aria-hidden="true"
               style:left={`${drag.indicator.left}px`} style:top={`${drag.indicator.top}px`}
               style:width={`${drag.indicator.width}px`} style:height={`${drag.indicator.height}px`}></div>
        {/if}
        {#if drag}
          <div class="cv-ghost" aria-hidden="true"
               style:left={`${drag.x + 12}px`} style:top={`${drag.y + 12}px`}>{drag.label}</div>
        {/if}
      </div>

      <div class="cv-footer" class:cv-selected={editingFooter} role="group" aria-label="Page footer">
        {#if editingFooter}
          <div class="cv-text-editor">
            <RichTextEditor id={`${kind}-page-footer`} label="Page footer" focusAt={focusPoint}
                            bind:value={footer} />
          </div>
        {:else}
          <button type="button" class="cv-footer-edit" aria-label="Edit page footer"
                  onclick={(e) => {
                    e.stopPropagation();
                    selected = null;
                    selectedLine = null;
                    focusPoint = e.detail ? { x: e.clientX, y: e.clientY } : { end: true };
                    editingFooter = true;
                  }}>
            {#if (footer || '').replace(/<[^>]*>/g, '').trim()}
              <span class="rich">{@html footer}</span>
            {:else}
              <span class="cv-footer-empty">Page footer — click to add (e.g. Page {'{page}'} of {'{page_count}'})</span>
            {/if}
          </button>
        {/if}
      </div>
    </div>
  </div>
</div>

<style>
  .cv-wrap { display: flex; gap: 12px; align-items: flex-start; }
  .cv-palette {
    flex: 0 0 150px;
    position: sticky;
    top: 8px;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .cv-palette p { margin: 0 0 4px; }
  .cv-palette-item { text-align: left; cursor: grab; touch-action: none; }
  .cv-scroll { flex: 1; overflow-x: auto; padding: 36px 4px 8px; background: #e5e7eb; }
  /* A4 at 96 dpi with WeasyPrint's default 75px page margin. */
  .cv-sheet {
    position: relative;
    width: 794px;
    min-height: 1123px;
    box-sizing: border-box;
    padding: 75px 75px 90px;
    margin: 0 auto;
    background: #fff;
    box-shadow: 0 1px 4px rgba(0, 0, 0, 0.25);
  }
  .cv-sheet.dragging { cursor: grabbing; user-select: none; }
  .cv-sheet :global(.pdf-page) { position: relative; }
  .cv-row { position: relative; }
  .cv-cell { min-height: 1em; }
  .cv-sheet :global(td.layout-cell) { min-height: 2em; }
  .cv-sheet :global(.cv-block) {
    position: relative;
    cursor: grab;
    touch-action: none;
    user-select: none;
    outline: 1px solid transparent;
  }
  .cv-sheet :global(.cv-block:hover) { outline-color: #9ec3ec; }
  .cv-sheet :global(.cv-block.cv-selected) { outline: 2px solid #2a6ebb; cursor: default; user-select: text; }
  .cv-toolbar {
    position: absolute;
    bottom: 100%;
    left: -2px;
    z-index: 5;
    display: flex;
    align-items: center;
    gap: 2px;
    white-space: nowrap;
    padding: 2px 4px;
    background: #fff;
    border: 1px solid #2a6ebb;
    border-radius: 3px;
    font: 12px sans-serif;
    text-align: left;
    cursor: default;
  }
  .cv-toolbar strong { margin-right: 4px; }
  .cv-toolbar small { margin-left: 4px; color: #666; }
  /* The width grip: a small tab above the column boundary (the boundary
     itself is where a column line goes). */
  .cv-divider {
    position: absolute;
    top: -14px;
    height: 12px;
    width: 14px;
    margin-left: -7px;
    border-radius: 3px;
    background: #d6dbe1;
    cursor: col-resize;
    touch-action: none;
    z-index: 4;
  }
  .cv-divider::after {
    content: '';
    position: absolute;
    left: 4px;
    right: 4px;
    top: 3px;
    bottom: 3px;
    border-left: 2px dotted #666;
    border-right: 2px dotted #666;
  }
  .cv-divider:hover, .cv-divider:focus { background: #9ec3ec; }
  /* Divider lines: the PDF's own border draws the line (line-below,
     row-line, a cell's border-right); this is the grab / select handle
     laid over it. */
  .cv-sheet :global(.layout-flow) { position: relative; }
  .cv-line { position: absolute; z-index: 3; }
  .cv-line-h { left: 0; right: 0; bottom: -5px; height: 9px; }
  .cv-line-v { top: 0; bottom: 0; width: 9px; margin-left: -5px; }
  .cv-line-hit {
    display: block;
    width: 100%;
    height: 100%;
    padding: 0;
    border: none;
    background: transparent;
    cursor: grab;
    touch-action: none;
  }
  .cv-line-hit:hover, .cv-line-hit:focus, .cv-line-selected .cv-line-hit {
    background: rgba(42, 110, 187, 0.35);
    outline: none;
  }
  .cv-line-tools { bottom: 100%; }
  .cv-upload { position: relative; overflow: hidden; display: inline-block; cursor: pointer;
    border: 1px solid var(--border-control, #bbb); border-radius: 2px; padding: 0 4px; }
  .cv-upload input { position: absolute; inset: 0; opacity: 0; cursor: pointer; }
  .cv-upload-error { color: #a8071a; white-space: normal; }
  .cv-indicator { position: absolute; background: #2a6ebb; border-radius: 2px; z-index: 6; pointer-events: none; }
  .cv-ghost {
    position: absolute;
    z-index: 7;
    pointer-events: none;
    padding: 2px 6px;
    background: #2a6ebb;
    color: #fff;
    font: 12px sans-serif;
    border-radius: 3px;
    white-space: nowrap;
  }
  .cv-footer {
    position: absolute;
    left: 75px;
    right: 75px;
    bottom: 24px;
    font: 10px sans-serif;
    color: #555;
    text-align: center;
  }
  .cv-footer-edit {
    display: block;
    width: 100%;
    padding: 0;
    border: none;
    outline: 1px solid transparent;
    background: none;
    font: inherit;
    color: inherit;
    text-align: inherit;
    cursor: text;
  }
  .cv-footer-edit:hover, .cv-footer-edit:focus { outline-color: #9ec3ec; }
  .cv-footer.cv-selected { outline: 2px solid #2a6ebb; text-align: left; }
  .cv-footer :global(.rich p) { margin: 0; }
  .cv-footer-empty { color: #aaa; font-style: italic; }
  .cv-text-editor :global(.rich-label) {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip: rect(0 0 0 0);
  }
</style>

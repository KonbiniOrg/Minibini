<script>
  import RichTextEditor from '../RichTextEditor.svelte';

  // One block drawn on the PDF layout canvas, as it prints. Details and line
  // items are the server-rendered sample HTML (`parts.blocks`); the title's
  // number likewise, under a heading the canvas draws; shared blocks draw
  // from the layout, the company values and the image library. Blocks that
  // would print nothing show a placeholder that only the canvas draws. An
  // indent draws as a small marker: what it prints is its column's padding,
  // which the canvas applies to the column itself.
  //
  // `editing` (the block is selected) turns its text into an editor in
  // place — a text block's own text, a company field (the shared company
  // value, via onCompany), or the title's heading (onHeading) — focused at
  // `focusAt`, the click that selected it, so one click is enough to type.
  //
  // All HTML here is ours: the server's own template output, or rich text
  // limited to the editor's schema and re-sanitized server-side.
  let {
    block, parts, company, images = {}, defaultHeading = '', editing = false, focusAt = null,
    id, onText, onCompany, onHeading,
  } = $props();

  const COMPANY_FIELDS = {
    company_name: ['Company name', true],
    company_address: ['Company address', false],
    company_phone: ['Company phone', true],
    company_email: ['Company email', true],
  };
  const blank = (html) => !(html || '').replace(/<[^>]*>/g, '').replace(/&nbsp;/g, ' ').trim();

  // The heading input appears when the block is selected: focus it then.
  let headingInput = $state();
  $effect(() => {
    if (headingInput && focusAt) headingInput.focus();
  });
</script>

{#if block.type === 'logo'}
  {#if company.logo}
    <img class="logo" src={company.logo} alt="Logo">
  {:else}
    <span class="cv-placeholder">Logo — none uploaded</span>
  {/if}
{:else if block.type in COMPANY_FIELDS}
  {@const [label, singleLine] = COMPANY_FIELDS[block.type]}
  {#if editing}
    <div class="cv-text-editor">
      <RichTextEditor {id} {label} {singleLine} {focusAt}
                      bind:value={() => company[block.type], (html) => onCompany(block.type, html)} />
    </div>
  {:else if blank(company[block.type])}
    <span class="cv-placeholder">{label} — click to type</span>
  {:else}
    <div class="rich">{@html company[block.type]}</div>
  {/if}
{:else if block.type === 'text'}
  {#if editing}
    <div class="cv-text-editor">
      <RichTextEditor {id} label="Text" {focusAt}
                      bind:value={() => block.html, (html) => onText(html)} />
    </div>
  {:else if blank(block.html)}
    <span class="cv-placeholder">Text — click to type</span>
  {:else}
    <div class="rich">{@html block.html}</div>
  {/if}
{:else if block.type === 'title'}
  {#if editing}
    <!-- The heading's own text is the input (so it keeps the h1's look). -->
    <!-- svelte-ignore a11y_missing_content -->
    <h1><input class="cv-heading" aria-label="Title text" bind:this={headingInput}
               value={block.heading ?? ''} placeholder={defaultHeading} maxlength="80"
               oninput={(e) => onHeading(e.currentTarget.value)}></h1>
  {:else}
    <h1>{block.heading || defaultHeading}</h1>
  {/if}
  {@html parts.blocks.title_number ?? ''}
{:else if block.type === 'image'}
  {#if images[block.image]}
    <img class={`image image-${block.size}`} src={images[block.image].src} alt={images[block.image].name}>
  {:else}
    <span class="cv-placeholder">Image — choose or upload one in its tools</span>
  {/if}
{:else if block.type === 'spacer' && block.orientation === 'horizontal'}
  <span class="cv-marker">↔ Indent — {block.side}, {block.size}</span>
{:else if block.type === 'spacer'}
  <div class={`spacer-${block.size} cv-spacer`}></div>
{:else}
  {@html parts.blocks[block.type] ?? ''}
{/if}

<style>
  .cv-placeholder {
    display: inline-block;
    color: #999;
    font-style: italic;
    border: 1px dashed #ccc;
    padding: 2px 6px;
  }
  .cv-spacer { outline: 1px dashed #ddd; }
  .cv-marker {
    display: inline-block;
    color: #2a6ebb;
    font: 11px sans-serif;
    border: 1px dashed #9ec3ec;
    padding: 1px 5px;
    white-space: nowrap;
  }
  /* In place, the heading input reads as the heading it replaces. */
  .cv-heading {
    font: inherit;
    width: 100%;
    box-sizing: border-box;
    padding: 0 2px;
    border: 1px dashed #2a6ebb;
    background: #fff;
    text-align: inherit;
  }
  /* In place, the editor reads like the page text it replaces. */
  .cv-text-editor :global(.rich-label) {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip: rect(0 0 0 0);
  }
  .cv-text-editor :global(.rich-input) {
    font-size: inherit;
    line-height: inherit;
    min-height: 1.4em;
    padding: 0 2px;
    border: 1px dashed #2a6ebb;
    background: #fff;
  }
</style>

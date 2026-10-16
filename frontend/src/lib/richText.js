import { Mark } from '@tiptap/core';

// The rich-text format of the document-PDF branding fields — mirrors
// apps/core/rich_text.py, which re-sanitizes everything server-side. Sizes are
// span classes the PDF stylesheet maps to 0.85× / 1.25× / 1.5× of the
// surrounding text; Normal is no span.
export const SIZES = [
  ['size-small', 'Small'],
  ['', 'Normal'],
  ['size-large', 'Large'],
  ['size-xlarge', 'Extra large'],
];
const SIZE_CLASSES = SIZES.map(([cls]) => cls).filter(Boolean);

export const TextSize = Mark.create({
  name: 'textSize',

  addAttributes() {
    return {
      size: {
        default: null,
        parseHTML: (el) => el.getAttribute('class'),
        renderHTML: (attrs) => ({ class: attrs.size }),
      },
    };
  },

  parseHTML() {
    return [{
      tag: 'span',
      getAttrs: (el) => (SIZE_CLASSES.includes(el.getAttribute('class')) ? {} : false),
    }];
  },

  renderHTML({ HTMLAttributes }) {
    return ['span', HTMLAttributes, 0];
  },

  addCommands() {
    return {
      setTextSize: (size) => ({ commands }) => (
        size ? commands.setMark(this.name, { size }) : commands.unsetMark(this.name)
      ),
    };
  },
});

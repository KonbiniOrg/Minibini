import { Mark } from '@tiptap/core';
import { FontFamily } from '@tiptap/extension-text-style';

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

// The generic font families the server allows (apps/core/rich_text.py
// FONT_FAMILIES); '' is the document's own font.
export const FONT_FAMILIES = [
  ['', 'Default font'],
  ['sans-serif', 'Sans serif'],
  ['serif', 'Serif'],
  ['monospace', 'Monospace'],
];
export const ALIGNMENTS = [
  ['left', 'Align left', '⇤'],
  ['center', 'Align center', '↔'],
  ['right', 'Align right', '⇥'],
  ['justify', 'Justify', '☰'],
];

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
      // A sized span may also carry colour / font styles: let TextStyle
      // read the same span.
      consuming: false,
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

// FontFamily, but only reading the families the server keeps — so pasted
// text in, say, Calibri shows in the document's own font, as it will print.
export const AllowedFontFamily = FontFamily.extend({
  addGlobalAttributes() {
    const allowed = FONT_FAMILIES.map(([family]) => family).filter(Boolean);
    return [{
      types: this.options.types,
      attributes: {
        fontFamily: {
          default: null,
          parseHTML: (el) => {
            const family = el.style.fontFamily?.replace(/['"]+/g, '').trim();
            return allowed.includes(family) ? family : null;
          },
          renderHTML: (attrs) => (attrs.fontFamily ? { style: `font-family: ${attrs.fontFamily}` } : {}),
        },
      },
    }];
  },
});

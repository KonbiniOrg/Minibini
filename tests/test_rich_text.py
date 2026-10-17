"""Tests for the rich-text allowlist used by the document-PDF branding fields:
the sanitizer every stored value passes through (on save and on render), the
blank check, and placeholder substitution into sanitized HTML."""
from django.test import SimpleTestCase

from apps.core.rich_text import (
    is_blank, render_rich_text, sanitize_rich_text,
)


class SanitizeRichTextTests(SimpleTestCase):
    def assertClean(self, dirty, clean):
        self.assertEqual(sanitize_rich_text(dirty), clean)

    def test_allowed_formatting_is_kept(self):
        html = ('<p>a <strong>b</strong> <em>c</em> <u>d</u> '
                '<span class="size-small">e</span> <span class="size-large">f</span> '
                '<span class="size-xlarge">g</span><br>h</p>')
        self.assertClean(html, html)

    def test_b_and_i_become_strong_and_em(self):
        self.assertClean('<p><b>x</b> <i>y</i></p>', '<p><strong>x</strong> <em>y</em></p>')

    def test_attributes_are_stripped(self):
        self.assertClean(
            '<p style="color:red" onclick="steal()"><strong style="x">a</strong></p>',
            '<p><strong>a</strong></p>')

    def test_spans_without_a_known_size_are_unwrapped(self):
        for span in ('<span>x</span>', '<span class="size-huge">x</span>',
                     '<span class="size-large evil">x</span>',
                     '<span style="font-size: 72px">x</span>'):
            self.assertClean(f'<p>{span}</p>', '<p>x</p>')

    def test_an_unwrapped_span_does_not_close_an_outer_size(self):
        self.assertClean(
            '<span class="size-large">a<span style="x">b</span>c</span>',
            '<span class="size-large">abc</span>')

    def test_dangerous_elements_are_dropped_with_their_content(self):
        for tag in ('script', 'style', 'iframe', 'object', 'svg', 'template', 'title'):
            self.assertClean(f'<p>a<{tag}>evil()</{tag}>b</p>', '<p>ab</p>')

    def test_resource_fetching_elements_are_dropped(self):
        self.assertClean(
            '<p>a<img src="file:///etc/passwd">b<link rel="stylesheet" href="http://x/">c</p>',
            '<p>abc</p>')

    def test_links_and_unknown_inline_tags_keep_only_their_text(self):
        self.assertClean(
            '<p><a href="http://evil/">click</a> <font color="red">red</font></p>',
            '<p>click red</p>')

    def test_text_is_escaped(self):
        self.assertClean('<p>1 &lt; 2 &amp; 3 &gt; 0</p>', '<p>1 &lt; 2 &amp; 3 &gt; 0</p>')
        self.assertClean('a & b', 'a &amp; b')

    def test_quotes_are_left_readable(self):
        self.assertClean("<p>Neal's \"CNC\"</p>", "<p>Neal's \"CNC\"</p>")

    def test_block_tags_become_paragraphs(self):
        self.assertClean('<div>a</div><h1>b</h1><li>c</li>', '<p>a</p><p>b</p><p>c</p>')

    def test_a_nested_paragraph_closes_the_open_one(self):
        self.assertClean('<p>a<p>b</p></p>', '<p>a</p><p>b</p>')

    def test_unclosed_tags_are_closed(self):
        self.assertClean('<p><strong><em>x', '<p><strong><em>x</em></strong></p>')

    def test_misnested_tags_stay_balanced(self):
        self.assertClean('<strong><em>x</strong>y</em>', '<strong><em>x</em></strong>y')

    def test_stray_end_tags_are_ignored(self):
        self.assertClean('a</strong></p>b', 'ab')

    def test_comments_are_dropped(self):
        self.assertClean('<p>a<!-- <script>x</script> -->b</p>', '<p>ab</p>')

    def test_self_closing_br_is_normalized(self):
        self.assertClean('a<br/>b<br />c', 'a<br>b<br>c')

    def test_word_paste_markup_reduces_to_the_allowlist(self):
        word = ('<html><head><style>p.MsoNormal{margin:0}</style></head><body>'
                '<p class="MsoNormal" style="margin:0"><b><span style="font-family:Calibri">'
                'Terms</span></b><o:p></o:p></p></body></html>')
        self.assertClean(word, '<p><strong>Terms</strong></p>')

    def test_lists_are_kept(self):
        html = ('<ul><li><p>a</p></li><li><p><strong>b</strong></p></li></ul>'
                '<ol><li><p>c</p></li></ol>')
        self.assertClean(html, html)

    def test_nested_lists_are_kept(self):
        html = '<ul><li><p>a</p><ol><li><p>b</p></li></ol></li><li><p>c</p></li></ul>'
        self.assertClean(html, html)

    def test_a_numbered_list_keeps_a_sane_start(self):
        self.assertClean('<ol start="3"><li><p>c</p></li></ol>',
                         '<ol start="3"><li><p>c</p></li></ol>')
        for start in ('1', '0', '-2', 'x', '10000', '3; color:red'):
            self.assertClean(f'<ol start="{start}"><li>c</li></ol>', '<ol><li>c</li></ol>')

    def test_other_list_attributes_are_dropped(self):
        self.assertClean('<ul style="x" class="y"><li data-z="1" style="q">a</li></ul>',
                         '<ul><li>a</li></ul>')
        self.assertClean('<ol type="a" reversed><li>a</li></ol>', '<ol><li>a</li></ol>')

    def test_an_unclosed_item_is_closed_by_its_sibling(self):
        self.assertClean('<ul><li>a<li>b</ul>', '<ul><li>a</li><li>b</li></ul>')

    def test_a_paragraph_in_an_item_closes_with_the_item(self):
        self.assertClean('<ul><li><p>a</li></ul>', '<ul><li><p>a</p></li></ul>')

    def test_paragraphs_inside_one_item_stay_in_it(self):
        html = '<ul><li><p>a</p><p>b</p></li></ul>'
        self.assertClean(html, html)

    def test_block_tags_inside_an_item_become_its_paragraphs(self):
        self.assertClean('<ul><li><div>a</div></li></ul>', '<ul><li><p>a</p></li></ul>')

    def test_a_list_closes_an_open_paragraph(self):
        self.assertClean('<p>x<ul><li>y</li></ul>', '<p>x</p><ul><li>y</li></ul>')

    def test_an_item_outside_a_list_is_a_paragraph(self):
        self.assertClean('<li>a</li><li>b</li>', '<p>a</p><p>b</p>')

    def test_empty_and_none(self):
        self.assertEqual(sanitize_rich_text(''), '')
        self.assertEqual(sanitize_rich_text(None), '')

    def test_is_idempotent(self):
        for dirty in ('<p><b>x</b><span class="size-large">y</span></p>',
                      '<div>a<p>b</div>', 'a & <i>b', '<strong><em>x</strong>y</em>',
                      '<ul><li>a<li>b<ol start="2"><li><p>c</ul>', '<p>x<ol><li>y</p>'):
            once = sanitize_rich_text(dirty)
            self.assertEqual(sanitize_rich_text(once), once)


class RichFormattingTests(SimpleTestCase):
    """The editor's fuller toolbar: strikethrough, sub/superscript, text
    colour / highlight / font family on spans, paragraph alignment — each
    through a strict allowlist; nothing that could fetch, link or script."""

    def assertClean(self, dirty, clean):
        self.assertEqual(sanitize_rich_text(dirty), clean)

    def test_strike_sub_and_sup_are_kept(self):
        self.assertClean('<p><s>a</s> <sub>2</sub> <sup>3</sup></p>',
                         '<p><s>a</s> <sub>2</sub> <sup>3</sup></p>')
        self.assertClean('<p><strike>a</strike><del>b</del></p>', '<p><s>a</s><s>b</s></p>')

    def test_colour_highlight_and_font_family_spans_are_kept_normalized(self):
        self.assertClean(
            '<p><span style="color: #C00; background-color: rgb(255, 240, 0); '
            'font-family: serif">x</span></p>',
            '<p><span style="color: #c00; background-color: rgb(255, 240, 0); '
            'font-family: serif">x</span></p>')

    def test_a_span_keeps_its_size_class_and_its_style(self):
        self.assertClean('<span class="size-large" style="color:#123456">x</span>',
                         '<span class="size-large" style="color: #123456">x</span>')

    def test_paragraph_alignment_is_kept(self):
        for align in ('left', 'center', 'right', 'justify'):
            self.assertClean(f'<p style="text-align: {align}">x</p>',
                             f'<p style="text-align: {align}">x</p>')
        # A block tag turned paragraph keeps its alignment too.
        self.assertClean('<div style="text-align:center">x</div>', '<p style="text-align: center">x</p>')

    def test_anything_outside_the_allowlist_is_dropped(self):
        for style in ('color: #12', 'color: rgb(300, 0, 0)',
                      'background-color: url(http://evil/x.png)',
                      'background: url(file:///etc/passwd)',
                      'color: #fff; position: fixed',
                      'font-family: Comic Sans',
                      'font-size: 72px',
                      'color: expression(alert(1))'):
            out = sanitize_rich_text(f'<p><span style="{style}">x</span></p>')
            self.assertNotIn('url', out)
            self.assertNotIn('expression', out)
            self.assertNotIn('position', out)
            self.assertNotIn('font-size', out)
        self.assertClean('<p><span style="color: #12">x</span></p>', '<p>x</p>')
        self.assertClean('<p><span style="color: Red">x</span></p>',
                         '<p><span style="color: red">x</span></p>')
        self.assertClean('<p><span style="color: #fff; position: fixed">x</span></p>',
                         '<p><span style="color: #fff">x</span></p>')
        self.assertClean('<p style="text-align: middle; color: #000">x</p>', '<p>x</p>')

    def test_links_are_still_reduced_to_text(self):
        self.assertClean('<p><a href="javascript:alert(1)" style="color:#f00">x</a></p>', '<p>x</p>')

    def test_is_idempotent_with_styles(self):
        html = ('<p style="text-align: right"><span class="size-small" style="color: #abc; '
                'font-family: monospace">x</span><s>y</s><sup>z</sup></p>')
        self.assertEqual(sanitize_rich_text(sanitize_rich_text(html)), sanitize_rich_text(html))


class IsBlankTests(SimpleTestCase):
    def test_blank_values(self):
        for value in ('', None, '<p></p>', '<p> &nbsp; </p>', '<p><br></p>',
                      '<p><strong></strong></p>', '   ', '<ul><li><p></p></li></ul>'):
            self.assertTrue(is_blank(value), value)

    def test_non_blank_values(self):
        for value in ('<p>x</p>', 'x', '<p><strong>0</strong></p>', '<ul><li><p>a</p></li></ul>'):
            self.assertFalse(is_blank(value), value)


class RenderRichTextTests(SimpleTestCase):
    def test_substitutes_placeholders_with_escaped_values(self):
        self.assertEqual(
            render_rich_text('<p>Hi <strong>{contact_fname}</strong></p>',
                             {'contact_fname': '<b>Bob & Co'}),
            '<p>Hi <strong>&lt;b&gt;Bob &amp; Co</strong></p>')

    def test_unknown_placeholder_and_none(self):
        self.assertEqual(render_rich_text('<p>{nope} {x}</p>', {'x': None}), '<p>{nope} </p>')

    def test_placeholder_split_by_formatting_prints_as_typed(self):
        self.assertEqual(
            render_rich_text('<p>{contact_<strong>fname</strong>}</p>', {'contact_fname': 'Bob'}),
            '<p>{contact_<strong>fname</strong>}</p>')

    def test_substituted_values_are_not_substituted_again(self):
        self.assertEqual(
            render_rich_text('<p>{a}</p>', {'a': '{b}', 'b': 'no'}), '<p>{b}</p>')

    def test_safe_values_are_inserted_as_markup(self):
        self.assertEqual(
            render_rich_text('<p>Page {page}</p>', {}, safe_values={'page': '<span class="page-number"></span>'}),
            '<p>Page <span class="page-number"></span></p>')

    def test_sanitizes_before_substituting(self):
        self.assertEqual(
            render_rich_text('<p onclick="x">{a}<script>bad</script></p>', {'a': 'ok'}),
            '<p>ok</p>')

    def test_blank_renders_empty(self):
        self.assertEqual(render_rich_text('<p></p>', {}), '')
        self.assertEqual(render_rich_text(None, {}), '')

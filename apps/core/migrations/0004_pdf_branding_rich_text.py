"""Convert the document-PDF branding values from plain text to rich text.

The company fields and the per-document text slots became rich text (the
HTML subset of apps/core/rich_text.py). Each stored line becomes a paragraph,
text is escaped, and the company name is wrapped in bold + Large to keep the
bold, larger look the template used to force — so every PDF prints as before.

Self-contained on purpose: keys and conversion are spelled out here rather
than imported, so later changes to the app code can't change this migration.
"""
from html import escape, unescape
from html.parser import HTMLParser

from django.db import migrations

RICH_KEYS = (
    'pdf_company_name', 'pdf_company_address',
    'pdf_company_phone', 'pdf_company_email',
    *(f'{kind}_pdf_text_{slot}'
      for kind in ('estimate', 'change_order', 'po')
      for slot in ('below_header', 'above_lines', 'below_totals', 'page_footer')),
)


def plain_to_rich(key, value):
    text = (value or '').replace('\r\n', '\n').replace('\r', '\n').strip()
    if not text:
        return ''
    if key == 'pdf_company_name':
        return f'<p><strong><span class="size-large">{escape(text, quote=False)}</span></strong></p>'
    return ''.join(f'<p>{escape(line, quote=False)}</p>' for line in text.split('\n'))


class _PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lines = ['']
        self.in_paragraph = False

    def handle_starttag(self, tag, attrs):
        if tag == 'br':
            self.lines.append('')
        elif tag == 'p':
            if self.in_paragraph or self.lines[-1]:
                self.lines.append('')
            self.in_paragraph = True

    def handle_endtag(self, tag):
        if tag == 'p':
            self.in_paragraph = False
            self.lines.append('')

    def handle_data(self, data):
        self.lines[-1] += data


def rich_to_plain(value):
    if not value:
        return ''
    parser = _PlainText()
    parser.feed(value)
    parser.close()
    lines = parser.lines
    if lines and lines[-1] == '':
        lines = lines[:-1]
    return unescape('\n'.join(lines))


def forwards(apps, schema_editor):
    Configuration = apps.get_model('core', 'Configuration')
    for config in Configuration.objects.filter(key__in=RICH_KEYS):
        config.value = plain_to_rich(config.key, config.value)
        config.save()


def backwards(apps, schema_editor):
    Configuration = apps.get_model('core', 'Configuration')
    for config in Configuration.objects.filter(key__in=RICH_KEYS):
        config.value = rich_to_plain(config.value)
        config.save()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_seed_setup_defaults'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]

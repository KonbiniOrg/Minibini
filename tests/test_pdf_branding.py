"""Document-PDF branding: the shared company data (logo, name, address,
phone, email), the per-document page footer, and the per-document layouts
that place them (apps/core/pdf_branding.py, apps/core/pdf_layout.py)."""
import base64
import io
import json
from decimal import Decimal

from django.contrib.auth.models import Permission
from django.test import SimpleTestCase
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from rest_framework.test import APIClient

from tests.base import FixtureTestCase
from apps.contacts.models import Business, Contact
from apps.core.models import Configuration, User
from apps.core.pdf_branding import (
    LOGO_KEY, MAX_LOGO_BYTES, RICH_TEXT_KEYS, PdfBrandingService,
    footer_key, pdf_branding_context, pdf_page_images, preview_draft_keys,
)
from apps.core.pdf_layout import default_layout, layout_key, save_layout
from apps.estimates.models import Estimate, EstimateLineItem
from apps.estimates.pdf import (
    generate_estimate_pdf, render_change_order_html, render_estimate_html,
)
from apps.jobs.services import JobService
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem
from apps.purchasing.pdf import render_purchase_order_html


def _png_bytes(size=(4, 4)):
    buf = io.BytesIO()
    Image.new('RGB', size, (200, 30, 30)).save(buf, format='PNG')
    return buf.getvalue()


def _set(key, value):
    Configuration.objects.update_or_create(key=key, defaults={'value': value})


def _config_user(username='pdf_admin'):
    user = User.objects.create_user(username=username, password='pass')
    user.user_permissions.add(Permission.objects.get(codename='can_manage_config'))
    return User.objects.get(pk=user.pk)


def _row(columns, *cells):
    return {'columns': columns, 'cells': [list(cell) for cell in cells]}


def _text(html, align='left'):
    return {'type': 'text', 'html': html, 'align': align}


def _layout(*rows):
    return {'version': 1, 'rows': list(rows)}


LINES = _row('full', [{'type': 'line_items'}])


def _blocks(branding):
    return [b for row in branding['rows'] for cell in row['cells'] for b in cell['blocks']]


class BrandingContextTests(FixtureTestCase):
    def test_defaults_print_only_the_document(self):
        b = pdf_branding_context('estimate', {})['branding']
        self.assertEqual([x['type'] for x in _blocks(b)], ['title', 'details', 'line_items'])
        self.assertEqual(b['page_footer'], '')

    def test_uses_the_kinds_saved_layout(self):
        save_layout('po', _layout(_row('full', [_text('PO {document_number}')]), LINES))
        b = pdf_branding_context('po', {'document_number': 'PO-9'})['branding']
        self.assertEqual(_blocks(b)[0]['html'], 'PO PO-9')
        b = pdf_branding_context('estimate', {})['branding']
        self.assertEqual(_blocks(b)[0]['type'], 'title')

    def test_company_blocks_print_the_shared_values(self):
        _set('pdf_company_name', '<p>Neal CNC</p>')
        for kind in ('estimate', 'po'):
            blocks = _blocks(pdf_branding_context(kind, {})['branding'])
            name = next(x for x in blocks if x['type'] == 'company_name')
            self.assertEqual(name['html'], '<p>Neal CNC</p>')

    def test_page_footer_keeps_formatting_and_renders_page_tokens(self):
        _set(footer_key('po'),
             '<p><strong>A &lt;b&gt; &amp; Co</strong> — Page {page} of {page_count}</p>')
        footer = pdf_branding_context('po', {})['branding']['page_footer']
        self.assertIn('<strong>A &lt;b&gt; &amp; Co</strong>', footer)
        self.assertIn('<span class="page-number"></span>', footer)
        self.assertIn('<span class="page-count"></span>', footer)
        self.assertNotIn('{page', footer)

    def test_rich_fields_are_sanitized_when_rendered(self):
        # Rows written before the save-time sanitizer (or by hand) are still
        # cleaned: WeasyPrint would fetch an <img> / stylesheet reference.
        _set('pdf_company_name', '<p onclick="x"><b>Neal</b><img src="file:///etc/passwd"></p>')
        _set(layout_key('po'), json.dumps(_layout(
            _row('full', [_text('<p><span class="size-large">{po_number}</span><script>x</script></p>')]),
            LINES)))
        blocks = _blocks(pdf_branding_context('po', {'po_number': 'PO-1'})['branding'])
        self.assertEqual(blocks[0]['html'], '<p><span class="size-large">PO-1</span></p>')
        _set(layout_key('po'), json.dumps(default_layout('po')))
        blocks = _blocks(pdf_branding_context('po', {})['branding'])
        name = next(x for x in blocks if x['type'] == 'company_name')
        self.assertEqual(name['html'], '<p><strong>Neal</strong></p>')

    def test_placeholder_values_are_escaped_into_rich_text(self):
        save_layout('estimate', _layout(_row('full', [_text('<p>For {contact_fname}</p>')]), LINES))
        blocks = _blocks(pdf_branding_context('estimate', {'contact_fname': '<i>Pat</i>'})['branding'])
        self.assertEqual(blocks[0]['html'], '<p>For &lt;i&gt;Pat&lt;/i&gt;</p>')

    def test_blank_rich_fields_print_nothing(self):
        _set('pdf_company_name', '<p></p>')
        _set('pdf_company_email', '<p> <strong></strong></p>')
        types = [x['type'] for x in _blocks(pdf_branding_context('estimate', {})['branding'])]
        self.assertNotIn('company_name', types)
        self.assertNotIn('company_email', types)

    def test_rich_text_keys_are_the_company_text_and_each_footer(self):
        self.assertEqual(RICH_TEXT_KEYS, {
            'pdf_company_name', 'pdf_company_address', 'pdf_company_phone',
            'pdf_company_email', footer_key('estimate'), footer_key('change_order'),
            footer_key('po'),
        })
        self.assertEqual(footer_key('po'), 'po_pdf_text_page_footer')

    def test_draft_values_override_the_saved_ones(self):
        _set('pdf_company_name', 'Saved Co')
        _set(footer_key('estimate'), 'Saved footer')
        b = pdf_branding_context('estimate', {}, drafts={
            'pdf_company_name': 'Draft Co',
            footer_key('estimate'): '',
        })['branding']
        name = next(x for x in _blocks(b) if x['type'] == 'company_name')
        self.assertEqual(name['html'], 'Draft Co')
        # A blanked draft hides the saved value rather than falling back to it.
        self.assertEqual(b['page_footer'], '')

    def test_draft_layout_overrides_the_saved_one_without_saving(self):
        save_layout('estimate', _layout(_row('full', [_text('Saved')]), LINES))
        b = pdf_branding_context('estimate', {}, layout=_layout(
            LINES, _row('full', [_text('Draft')])))['branding']
        self.assertEqual(_blocks(b)[1]['html'], 'Draft')
        self.assertIn('Saved', Configuration.objects.get(key=layout_key('estimate')).value)

    def test_invalid_draft_layout_is_a_validation_error(self):
        with self.assertRaises(ValidationError):
            pdf_branding_context('estimate', {}, layout=_layout(_row('full', [_text('x')])))

    def test_draft_values_are_not_saved(self):
        _set('pdf_company_name', 'Saved Co')
        pdf_branding_context('po', {}, drafts={'pdf_company_name': 'Draft Co'})
        self.assertEqual(
            Configuration.objects.get(key='pdf_company_name').value, 'Saved Co')

    def test_preview_draft_keys_are_the_company_text_and_own_footer(self):
        keys = preview_draft_keys('po')
        self.assertIn('pdf_company_email', keys)
        self.assertIn(footer_key('po'), keys)
        self.assertNotIn(footer_key('estimate'), keys)
        # The logo is uploaded deliberately, never previewed from a draft.
        self.assertNotIn(LOGO_KEY, keys)


class PdfPageImagesTests(FixtureTestCase):
    def _pdf(self, pages):
        from weasyprint import HTML
        body = '<div style="page-break-after: always">x</div>' * (pages - 1) + '<div>x</div>'
        return HTML(string=f'<html><body>{body}</body></html>').write_pdf()

    def test_one_png_data_uri_per_page(self):
        images = pdf_page_images(self._pdf(2))
        self.assertEqual(len(images), 2)
        for uri in images:
            self.assertTrue(uri.startswith('data:image/png;base64,'))
            png = base64.b64decode(uri.split(',', 1)[1])
            self.assertEqual(Image.open(io.BytesIO(png)).format, 'PNG')

    def test_pdfium_is_never_entered_by_two_threads_at_once(self):
        # PDFium is not thread-safe, and the settings page fires three
        # previews at once into a threaded server: a concurrent render
        # crashed the whole process (core dump) in the e2e run.
        import threading
        import time
        from unittest.mock import patch

        state = {'inside': 0, 'peak': 0}
        guard = threading.Lock()

        class FakeDocument:
            def __init__(self, data):
                with guard:
                    state['inside'] += 1
                    state['peak'] = max(state['peak'], state['inside'])
                time.sleep(0.05)

            def __iter__(self):
                return iter(())

            def close(self):
                with guard:
                    state['inside'] -= 1

        with patch('pypdfium2.PdfDocument', FakeDocument):
            threads = [threading.Thread(target=pdf_page_images, args=(b'%PDF',))
                       for _ in range(3)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        self.assertEqual(state['peak'], 1)


class LogoServiceTests(FixtureTestCase):
    def test_set_logo_stores_a_data_uri(self):
        png = _png_bytes()
        uri = PdfBrandingService.set_logo(
            SimpleUploadedFile('logo.png', png, content_type='image/png'))
        self.assertTrue(uri.startswith('data:image/png;base64,'))
        self.assertEqual(base64.b64decode(uri.split(',', 1)[1]), png)
        self.assertEqual(Configuration.objects.get(key=LOGO_KEY).value, uri)

    def test_jpeg_is_accepted(self):
        buf = io.BytesIO()
        Image.new('RGB', (4, 4)).save(buf, format='JPEG')
        uri = PdfBrandingService.set_logo(
            SimpleUploadedFile('logo.jpg', buf.getvalue(), content_type='image/jpeg'))
        self.assertTrue(uri.startswith('data:image/jpeg;base64,'))

    def test_non_image_is_rejected(self):
        with self.assertRaises(ValidationError) as cm:
            PdfBrandingService.set_logo(
                SimpleUploadedFile('logo.png', b'not an image', content_type='image/png'))
        self.assertIn('logo', cm.exception.message_dict)
        self.assertFalse(Configuration.objects.filter(key=LOGO_KEY).exists())

    def test_unsupported_format_is_rejected(self):
        buf = io.BytesIO()
        Image.new('RGB', (4, 4)).save(buf, format='BMP')
        with self.assertRaises(ValidationError) as cm:
            PdfBrandingService.set_logo(
                SimpleUploadedFile('logo.bmp', buf.getvalue(), content_type='image/bmp'))
        self.assertIn('logo', cm.exception.message_dict)

    def test_oversize_is_rejected(self):
        big = SimpleUploadedFile(
            'logo.png', b'x' * (MAX_LOGO_BYTES + 1), content_type='image/png')
        with self.assertRaises(ValidationError) as cm:
            PdfBrandingService.set_logo(big)
        self.assertIn('logo', cm.exception.message_dict)

    def test_clear_logo(self):
        PdfBrandingService.set_logo(
            SimpleUploadedFile('logo.png', _png_bytes(), content_type='image/png'))
        PdfBrandingService.clear_logo()
        self.assertFalse(Configuration.objects.filter(key=LOGO_KEY).exists())
        PdfBrandingService.clear_logo()  # idempotent


class DocumentHtmlTests(FixtureTestCase):
    """The three document templates render their layout: rows of columns
    holding the shared company blocks, text, and the document's own title,
    details and line items."""

    def setUp(self):
        super().setUp()
        self.contact = Contact.objects.create(
            first_name='Pat', last_name='Customer', email='pat@acme.test')
        self.business = Business.objects.create(
            business_name='Acme Fab', default_contact=self.contact)
        self.contact.business = self.business
        self.contact.save()
        self.job = JobService.create_job(name='Bracket run', contact=self.contact)
        self.est = Estimate.objects.create(
            job=self.job, estimate_number='EST-BR-1', version=1)
        EstimateLineItem.objects.create(
            estimate=self.est, description='Cut brackets', qty=Decimal('2'),
            units='ea', price=Decimal('100.00'), line_number=1)
        self.po = PurchaseOrder.objects.create(
            business=self.business, po_number='PO-BR-1')
        PurchaseOrderLineItem.objects.create(
            purchase_order=self.po, description='Sheet steel',
            qty=Decimal('5.00'), price=Decimal('1.00'))

    def _company(self):
        PdfBrandingService.set_logo(
            SimpleUploadedFile('logo.png', _png_bytes(), content_type='image/png'))
        _set('pdf_company_name', '<p>Neal CNC</p>')
        _set('pdf_company_address', '<p>1 Mill Rd</p><p>Springfield</p>')
        _set('pdf_company_phone', '<p>555-0100</p>')
        _set('pdf_company_email', '<p>office@neal.test</p>')

    def test_unbranded_estimate_prints_just_the_document(self):
        html = render_estimate_html(self.est)
        self.assertNotIn('<table class="layout-row"', html)
        self.assertNotIn('class="block block-text', html)
        self.assertNotIn('class="page-footer', html)
        self.assertIn('EST-BR-1', html)
        self.assertIn('Cut brackets', html)

    def test_default_letterhead_puts_the_logo_left_and_the_company_right(self):
        self._company()
        html = render_estimate_html(self.est)
        row = html[html.index('<table class="layout-row"'):html.index('</table>')]
        self.assertIn('<col style="width: 50%">', row)
        logo_cell, company_cell = row.split('<td class="layout-cell"')[1:]
        self.assertIn('<img class="logo" src="data:image/png;base64,', logo_cell)
        self.assertIn('block-logo align-left', logo_cell)
        for expected in ('Neal CNC', '<p>1 Mill Rd</p><p>Springfield</p>', '555-0100',
                         'office@neal.test'):
            self.assertIn(expected, company_cell)
        self.assertIn('block-company_name align-right', company_cell)
        self.assertLess(html.index('Neal CNC'), html.index('EST-BR-1'))

    def test_blocks_render_in_layout_order(self):
        save_layout('estimate', _layout(
            _row('full', [_text('FIRST')]),
            LINES,
            _row('1/3-2/3', [{'type': 'details'}], [{'type': 'title', 'align': 'right'}]),
            dict(_row('full', [{'type': 'spacer', 'size': 'large'},
                               dict(_text('LAST'), line_below=True)]), line_below=True),
        ))
        html = render_estimate_html(self.est)
        order = [html.index(x) for x in (
            'FIRST', 'Cut brackets', 'Acme Fab', 'EST-BR-1',
            'class="spacer-large"', 'LAST')]
        self.assertEqual(order, sorted(order))
        self.assertIn('<col style="width: 33.333%"><col style="width: 66.667%">', html)
        self.assertIn('block-title align-right', html)
        self.assertIn('<div class="layout-flow row-line">', html)
        self.assertIn('block-text align-left line-below', html)

    def test_full_width_rows_flow_and_only_column_rows_are_tables(self):
        # Flowing rows split across pages like any text; a column row is a
        # table that is kept whole. The line items always flow.
        save_layout('estimate', _layout(
            _row('full', [_text('TOP')]),
            _row('1/2-1/2', [_text('LEFT')], [_text('RIGHT')]),
            LINES))
        html = render_estimate_html(self.est)
        body = html[html.index('<body>'):]
        self.assertEqual(body.count('<table class="layout-row"'), 1)
        self.assertLess(body.index('<div class="layout-flow"><div class="block block-text align-left">'),
                        body.index('<table class="layout-row"'))
        table_end = body.index('</table>')
        self.assertIn('LEFT', body[:table_end])
        self.assertLess(table_end, body.index('<table class="lines">'))

    def test_column_lines_indents_and_gap_frame_the_columns(self):
        self._company()
        save_layout('estimate', _layout(
            dict(_row('1/2-1/2', [{'type': 'logo'}],
                      [{'type': 'spacer', 'orientation': 'horizontal', 'side': 'left', 'size': 'medium'},
                       {'type': 'company_name'}]), gap='large', column_lines=[True], line_below=True),
            LINES))
        html = render_estimate_html(self.est)
        self.assertIn('<table class="layout-row row-line">', html)
        self.assertIn('<td class="layout-cell" style="border-right: 1px solid #333; '
                      'padding-right: 16px">', html)
        self.assertIn('<td class="layout-cell" style="padding-left: 40px">', html)   # 16 + 24
        self.assertTrue(generate_estimate_pdf(self.est).startswith(b'%PDF'))

    def test_text_placeholders(self):
        save_layout('estimate', _layout(LINES, _row('full', [_text(
            'Thanks {contact_fname} of {contact_business} — {estimate_number} / {job_name}')])))
        html = render_estimate_html(self.est)
        self.assertIn('Thanks Pat of Acme Fab — EST-BR-1 / Bracket run', html)

    def test_text_markup_is_sanitized(self):
        _set(layout_key('estimate'), json.dumps(_layout(LINES, _row('full', [_text(
            '<script>x</script><p>ok <img src="file:///etc/passwd"></p>')]))))
        html = render_estimate_html(self.est)
        self.assertNotIn('<script>x', html)
        self.assertNotIn('file:///', html)
        self.assertIn('<p>ok </p>', html)

    def test_size_steps_and_lists_are_styled(self):
        html = render_estimate_html(self.est)
        for rule in ('.size-small', '.size-large', '.size-xlarge', '.rich ul'):
            self.assertIn(rule, html)

    def test_layouts_are_per_document(self):
        save_layout('po', _layout(LINES, _row('full', [_text('PO ONLY')])))
        self.assertNotIn('PO ONLY', render_estimate_html(self.est))
        self.assertIn('PO ONLY', render_purchase_order_html(self.po))

    def test_purchase_order_layout(self):
        self._company()
        save_layout('po', _layout(
            _row('2/3-1/3', [{'type': 'company_name'}, {'type': 'title'}],
                 [{'type': 'logo', 'align': 'right'}]),
            _row('full', [{'type': 'details'}]),
            LINES,
            _row('full', [_text('Quote {po_number} to {vendor_name}')]),
        ))
        html = render_purchase_order_html(self.po)
        self.assertIn('Quote PO-BR-1 to Acme Fab', html)
        order = [html.index(x) for x in (
            'Neal CNC', 'PO-BR-1', '<img class="logo"', 'Vendor:', 'Sheet steel', 'Quote PO-BR-1')]
        self.assertEqual(order, sorted(order))

    def test_issued_purchase_order_shows_its_date(self):
        from datetime import datetime, timezone as dt_timezone
        self.po.issued_date = datetime(2026, 3, 5, 12, 0, tzinfo=dt_timezone.utc)
        self.po.save()
        html = render_purchase_order_html(self.po)
        self.assertIn('<strong>Date:</strong> March 5, 2026', html)

    def test_change_order_layout_and_footer(self):
        from apps.estimates.change_order_service import ChangeOrderService
        for status in (Estimate.STATUS_OPEN, Estimate.STATUS_ACCEPTED):
            self.est.status = status
            self.est.save()
        # Accepting the estimate approved the job; a CO is drafted on hold.
        JobService.hold_job(self.job.pk, 'CO editing')
        co = ChangeOrderService.create(job_id=self.job.pk)
        save_layout('change_order', _layout(
            _row('full', [{'type': 'title'}, _text('CO-TOP')]),
            _row('full', [{'type': 'details'}]),
            LINES,
            _row('full', [_text('CO-BOTTOM')]),
        ))
        _set(footer_key('change_order'), 'CO-FOOTER')
        html = render_change_order_html(co)
        order = [html.index(x) for x in (
            co.change_order_number, 'CO-TOP', 'Amends estimate', 'Line items', 'CO-BOTTOM')]
        self.assertEqual(order, sorted(order))
        self.assertIn('CO-FOOTER', html)

    def test_fully_branded_multipage_estimate_still_produces_a_pdf(self):
        self._company()
        for n in range(2, 80):
            EstimateLineItem.objects.create(
                estimate=self.est, description=f'Line {n}', qty=Decimal('1'),
                units='ea', price=Decimal('1.00'), line_number=n)
        save_layout('estimate', _layout(
            _row('1/3-1/3-1/3', [{'type': 'logo'}], [{'type': 'title', 'align': 'center'}],
                 [{'type': 'company_name', 'align': 'right'}]),
            _row('1/2-1/2', [{'type': 'details'}], [_text('<ol start="2"><li><p>Net 30</p></li></ol>')]),
            LINES,
            _row('1/2-1/2', [_text('<p><strong>Terms</strong></p>')], [_text('Signature')]),
        ))
        _set(footer_key('estimate'), 'Page {page} of {page_count}')
        pdf = generate_estimate_pdf(self.est)
        self.assertTrue(pdf.startswith(b'%PDF'))
        self.assertGreater(len(pdf_page_images(pdf, scale=0.2)), 1)


class PdfBrandingApiTests(FixtureTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=_config_user())

    def _upload(self, data=None, name='logo.png'):
        return self.client.post(
            '/api/settings/pdf-logo/',
            {'logo': SimpleUploadedFile(name, data or _png_bytes(), content_type='image/png')},
            format='multipart')

    def test_logo_upload_get_delete_roundtrip(self):
        resp = self.client.get('/api/settings/pdf-logo/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'logo': ''})

        resp = self._upload()
        self.assertEqual(resp.status_code, 200, resp.content)
        uri = resp.json()['logo']
        self.assertTrue(uri.startswith('data:image/png;base64,'))
        self.assertEqual(self.client.get('/api/settings/pdf-logo/').json(), {'logo': uri})

        resp = self.client.delete('/api/settings/pdf-logo/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('message', resp.json())
        self.assertEqual(self.client.get('/api/settings/pdf-logo/').json(), {'logo': ''})

    def test_bad_logo_is_a_field_error(self):
        resp = self._upload(data=b'nope')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('logo', resp.json())

    def test_missing_file_is_a_field_error(self):
        resp = self.client.post('/api/settings/pdf-logo/', {}, format='multipart')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('logo', resp.json())

    def test_settings_get_omits_the_logo_blob(self):
        self._upload()
        _set('pdf_company_name', 'Neal CNC')
        data = self.client.get('/api/settings/').json()
        self.assertNotIn(LOGO_KEY, data)
        self.assertEqual(data['pdf_company_name'], 'Neal CNC')

    def test_settings_patch_cannot_write_the_logo(self):
        resp = self.client.patch('/api/settings/', {LOGO_KEY: 'data:x'}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn(LOGO_KEY, resp.json())
        self.assertFalse(Configuration.objects.filter(key=LOGO_KEY).exists())

    def test_settings_patch_cannot_write_a_layout(self):
        resp = self.client.patch(
            '/api/settings/', {layout_key('po'): '{"version": 1}'}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn(layout_key('po'), resp.json())
        self.assertFalse(Configuration.objects.filter(key=layout_key('po')).exists())

    def test_settings_patch_sanitizes_rich_text_keys(self):
        resp = self.client.patch('/api/settings/', {
            'pdf_company_name': '<p onclick="x"><b>Neal</b><script>x</script></p>',
            footer_key('po'): '<p><span class="size-large" style="color:red; position:fixed; '
                              'background:url(file:///etc/passwd)">T</span></p>',
        }, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(Configuration.objects.get(key='pdf_company_name').value,
                         '<p><strong>Neal</strong></p>')
        # Colour is allowed formatting; position and url() never survive.
        self.assertEqual(Configuration.objects.get(key=footer_key('po')).value,
                         '<p><span class="size-large" style="color: red">T</span></p>')

    def test_settings_patch_leaves_other_keys_alone(self):
        resp = self.client.patch(
            '/api/settings/', {'email_retention_days': '<b>30</b>'}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(
            Configuration.objects.get(key='email_retention_days').value, '<b>30</b>')

    # --- layout endpoint ---------------------------------------------------

    def _layout_url(self, kind):
        return f'/api/settings/pdf-layout/{kind}/'

    def test_layout_get_returns_the_layout_the_default_and_the_catalog(self):
        data = self.client.get(self._layout_url('po')).json()
        self.assertEqual(data['layout'], default_layout('po'))
        self.assertEqual(data['default'], default_layout('po'))
        self.assertIn('line_items', [b['type'] for b in data['catalog']['blocks']])
        self.assertIn('1/2-1/2', [p['key'] for p in data['catalog']['presets']])

    def test_layout_put_stores_the_normalized_layout(self):
        layout = _layout(LINES, _row('full', [{'type': 'text', 'html': '<p>T<script>x</script></p>'}]))
        resp = self.client.put(self._layout_url('po'), {'layout': layout}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertEqual(data['default'], default_layout('po'))
        self.assertEqual(data['layout']['rows'][1]['cells'][0][0],
                         {'type': 'text', 'align': 'left', 'html': '<p>T</p>'})
        self.assertEqual(self.client.get(self._layout_url('po')).json()['layout'], data['layout'])
        self.assertEqual(self.client.get(self._layout_url('estimate')).json()['layout'],
                         default_layout('estimate'))

    def test_layout_put_rejects_an_invalid_layout(self):
        resp = self.client.put(
            self._layout_url('po'), {'layout': _layout(_row('full', [_text('x')]))}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('layout', resp.json())
        self.assertFalse(Configuration.objects.filter(key=layout_key('po')).exists())
        resp = self.client.put(self._layout_url('po'), {}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('layout', resp.json())

    def test_layout_unknown_document_is_404(self):
        self.assertEqual(self.client.get(self._layout_url('invoice')).status_code, 404)

    # --- preview -------------------------------------------------------------

    def _preview(self, document, values=None, layout=None):
        payload = {'document': document}
        if values is not None:
            payload['values'] = values
        if layout is not None:
            payload['layout'] = layout
        return self.client.post('/api/settings/pdf-preview/', payload, format='json')

    def test_preview_returns_page_images_and_the_pdf_for_each_document(self):
        _set('pdf_company_name', 'Neal CNC')
        for kind in ('estimate', 'change_order', 'po'):
            resp = self._preview(kind, {footer_key(kind): 'Footer {document_number}'},
                                 _layout(LINES, _row('1/2-1/2', [_text('A')], [_text('B')])))
            self.assertEqual(resp.status_code, 200, (kind, resp.content))
            data = resp.json()
            self.assertGreaterEqual(len(data['pages']), 1, kind)
            self.assertTrue(data['pages'][0].startswith('data:image/png;base64,'), kind)
            self.assertTrue(data['pdf'].startswith('data:application/pdf;base64,'), kind)
            pdf = base64.b64decode(data['pdf'].split(',', 1)[1])
            self.assertTrue(pdf.startswith(b'%PDF'), kind)

    def test_preview_renders_the_drafts_without_saving_them(self):
        from apps.estimates.pdf import preview_estimate_html
        save_layout('estimate', _layout(LINES, _row('full', [_text('Saved terms')])))
        _set('pdf_company_name', 'Saved Co')
        html = preview_estimate_html(
            {'pdf_company_name': 'Draft Co'},
            _layout(LINES, _row('full', [_text('Draft terms {document_number}'),
                                         {'type': 'company_name'}])))
        self.assertIn('Draft terms EST-0000', html)
        self.assertIn('Draft Co', html)
        self.assertNotIn('Saved terms', html)

        resp = self._preview('estimate', {'pdf_company_name': 'Draft Co'},
                             _layout(LINES, _row('full', [_text('Draft terms')])))
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertIn('Saved terms', Configuration.objects.get(key=layout_key('estimate')).value)
        self.assertEqual(Configuration.objects.get(key='pdf_company_name').value, 'Saved Co')

    def test_preview_without_a_draft_layout_uses_the_saved_one(self):
        from apps.purchasing.pdf import preview_purchase_order_html
        save_layout('po', _layout(LINES, _row('full', [_text('PO saved {vendor_name}')])))
        self.assertIn('PO saved Sample Vendor Inc.', preview_purchase_order_html())

    def test_each_preview_passes_its_drafts_to_the_template(self):
        from apps.estimates.pdf import preview_change_order_html
        co = preview_change_order_html(
            {'pdf_company_name': 'Draft Co'},
            _layout(LINES, _row('full', [_text('CO draft'), {'type': 'company_name'}])))
        self.assertIn('Draft Co', co)
        self.assertIn('CO draft', co)

    def test_preview_drafts_are_sanitized(self):
        from apps.estimates.pdf import preview_estimate_html
        html = preview_estimate_html(
            {'pdf_company_name': '<p>Co<img src="file:///etc/passwd"></p>'},
            _layout(LINES, _row('full', [_text('<p><u>Draft</u><script>x</script></p>'),
                                         {'type': 'company_name'}])))
        self.assertNotIn('file:///', html)
        self.assertNotIn('<script>x', html)
        self.assertIn('<p><u>Draft</u></p>', html)

    def test_preview_values_and_layout_are_optional(self):
        resp = self._preview('po')
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_preview_rejects_an_invalid_layout(self):
        resp = self._preview('po', layout=_layout(_row('full', [_text('x')])))
        self.assertEqual(resp.status_code, 400)
        self.assertIn('layout', resp.json())
        resp = self._preview('po', layout=['nope'])
        self.assertEqual(resp.status_code, 400)
        self.assertIn('layout', resp.json())

    def test_preview_rejects_an_unknown_document(self):
        for document in ('invoice', 'letterhead'):
            resp = self._preview(document)
            self.assertEqual(resp.status_code, 400, document)
            self.assertIn('detail', resp.json())

    def test_preview_rejects_keys_it_cannot_preview(self):
        for key in (LOGO_KEY, footer_key('estimate'), layout_key('po'), 'units_list'):
            resp = self._preview('po', {key: 'x'})
            self.assertEqual(resp.status_code, 400, key)
            self.assertIn('values', resp.json(), key)

    def test_preview_rejects_non_object_values(self):
        resp = self._preview('po', ['nope'])
        self.assertEqual(resp.status_code, 400)
        self.assertIn('values', resp.json())

    def test_preview_rejects_non_string_values(self):
        resp = self._preview('po', {'pdf_company_name': {'nested': 1}})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('values', resp.json())

    def test_preview_get_is_retired(self):
        resp = self.client.get('/api/settings/pdf-preview/?document=estimate')
        self.assertEqual(resp.status_code, 405)

    def test_endpoints_require_can_manage_config(self):
        plain = APIClient()
        plain.force_authenticate(
            user=User.objects.create_user(username='pdf_plain', password='pass'))
        self.assertEqual(plain.get('/api/settings/pdf-logo/').status_code, 403)
        self.assertEqual(plain.delete('/api/settings/pdf-logo/').status_code, 403)
        self.assertEqual(
            plain.post('/api/settings/pdf-preview/', {'document': 'estimate'},
                       format='json').status_code, 403)
        self.assertEqual(plain.get('/api/settings/pdf-layout/po/').status_code, 403)
        self.assertEqual(
            plain.put('/api/settings/pdf-layout/po/', {'layout': _layout(LINES)},
                      format='json').status_code, 403)


class CanvasApiTests(FixtureTestCase):
    """GET /api/settings/pdf-canvas/<kind>/ — the document's own blocks
    rendered with the preview's sample data, plus the PDF stylesheet, for
    the on-page layout canvas."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=_config_user('canvas_admin'))

    def test_returns_each_document_block_and_the_stylesheet(self):
        expected = {
            'estimate': ('EST-0000', 'Sample Customer Co.', 'Sample service line'),
            'change_order': ('CO-0000', 'Amends estimate', 'Sample added line'),
            'po': ('PO-0000', 'Sample Vendor Inc.', 'SAMPLE-01'),
        }
        for kind, (title, details, lines) in expected.items():
            resp = self.client.get(f'/api/settings/pdf-canvas/{kind}/')
            self.assertEqual(resp.status_code, 200, (kind, resp.content))
            data = resp.json()
            self.assertEqual(set(data['blocks']), {'title', 'title_number', 'details', 'line_items'}, kind)
            self.assertIn(title, data['blocks']['title'], kind)
            self.assertIn(details, data['blocks']['details'], kind)
            self.assertIn(lines, data['blocks']['line_items'], kind)
            self.assertNotIn(title, data['blocks']['line_items'], kind)
            css = data['stylesheet']
            self.assertIn('.pdf-page table.lines th', css, kind)
            self.assertIn('.pdf-page table.layout-row', css, kind)
            self.assertNotIn('<style', css, kind)

    def test_change_order_stylesheet_carries_its_row_colours(self):
        css = self.client.get('/api/settings/pdf-canvas/change_order/').json()['stylesheet']
        self.assertIn('.pdf-page tr.added', css)


    def test_unknown_document_is_404(self):
        self.assertEqual(self.client.get('/api/settings/pdf-canvas/invoice/').status_code, 404)

    def test_requires_can_manage_config(self):
        plain = APIClient()
        plain.force_authenticate(
            user=User.objects.create_user(username='canvas_plain', password='pass'))
        self.assertEqual(plain.get('/api/settings/pdf-canvas/po/').status_code, 403)

    def test_previews_are_unchanged_by_the_sample_refactor(self):
        from apps.estimates.pdf import preview_estimate_html
        from apps.purchasing.pdf import preview_purchase_order_html
        self.assertIn('Sample service line', preview_estimate_html())
        self.assertIn('Jordan Sample', preview_purchase_order_html())


class ScopeCssTests(SimpleTestCase):
    def test_rules_are_scoped_and_body_becomes_the_page(self):
        from apps.core.pdf_branding import scope_css
        css = scope_css(
            'body { margin: 40px; }\n'
            'table.lines th, table.lines td { border: 1px solid #333; }\n'
            '.rich p:empty::before { content: "\\00a0"; }\n'
            '@page { @bottom-center { content: element(page-footer); } }\n'
            '.size-small { font-size: 0.85em; }', '.pdf-page')
        self.assertIn('.pdf-page { margin: 40px; }', css)
        self.assertIn('.pdf-page table.lines th, .pdf-page table.lines td { border', css)
        self.assertIn('.pdf-page .rich p:empty::before { content: "\\00a0"; }', css)
        self.assertIn('.pdf-page .size-small {', css)
        self.assertNotIn('@page', css)
        self.assertNotIn('bottom-center', css)


class ImageLibraryTests(FixtureTestCase):
    """Images uploaded once and placed by image blocks in any layout."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=_config_user('image_admin'))

    def _upload(self, data=None, name='photo.png'):
        return self.client.post(
            '/api/settings/pdf-images/',
            {'image': SimpleUploadedFile(name, data or _png_bytes(), content_type='image/png')},
            format='multipart')

    def test_upload_list_delete_roundtrip(self):
        self.assertEqual(self.client.get('/api/settings/pdf-images/').json(), {'images': []})
        resp = self._upload(name='shop floor.png')
        self.assertEqual(resp.status_code, 200, resp.content)
        image = resp.json()
        self.assertRegex(image['id'], r'^[0-9a-f]{32}$')
        self.assertEqual(image['name'], 'shop floor.png')
        self.assertTrue(image['src'].startswith('data:image/png;base64,'))
        self._upload(name='second.png')
        listed = self.client.get('/api/settings/pdf-images/').json()['images']
        self.assertEqual([i['name'] for i in listed], ['shop floor.png', 'second.png'])

        resp = self.client.delete(f'/api/settings/pdf-images/{image["id"]}/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('message', resp.json())
        self.assertEqual(len(self.client.get('/api/settings/pdf-images/').json()['images']), 1)
        self.assertEqual(self.client.delete(f'/api/settings/pdf-images/{image["id"]}/').status_code, 404)

    def test_bad_uploads_are_field_errors(self):
        for data in (b'nope',):
            resp = self._upload(data=data)
            self.assertEqual(resp.status_code, 400)
            self.assertIn('image', resp.json())
        resp = self.client.post('/api/settings/pdf-images/', {}, format='multipart')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('image', resp.json())

    def test_settings_api_never_carries_or_writes_images(self):
        image = self._upload().json()
        self.assertFalse(any(k.startswith('pdf_image_')
                             for k in self.client.get('/api/settings/').json()))
        resp = self.client.patch('/api/settings/', {f'pdf_image_{image["id"]}': 'x'}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_an_image_block_prints_its_library_image(self):
        from apps.estimates.pdf import preview_estimate_html
        image = self._upload().json()
        html = preview_estimate_html(None, _layout(
            _row('1/2-1/2', [{'type': 'image', 'image': image['id'], 'size': 'small', 'align': 'right'}],
                 [{'type': 'title', 'heading': 'Quotation'}]),
            LINES))
        self.assertIn(f'<img class="image image-small" src="{image["src"]}" alt="">', html)
        self.assertIn('block-image align-right', html)
        self.assertIn('<h1>Quotation</h1>', html)

    def test_requires_can_manage_config(self):
        plain = APIClient()
        plain.force_authenticate(user=User.objects.create_user(username='img_plain', password='p'))
        self.assertEqual(plain.get('/api/settings/pdf-images/').status_code, 403)
        self.assertEqual(plain.post('/api/settings/pdf-images/', {}, format='multipart').status_code, 403)

    def test_canvas_parts_carry_the_title_number_alone(self):
        data = self.client.get('/api/settings/pdf-canvas/po/').json()
        self.assertIn('PO-0000', data['blocks']['title_number'])
        self.assertNotIn('<h1>', data['blocks']['title_number'])

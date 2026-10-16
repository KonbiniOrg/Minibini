"""Tests for customizable document-PDF branding: the shared logo / company
letterhead, the per-document text slots, the logo upload, and the settings
endpoints that drive them."""
import base64
import io
from decimal import Decimal

from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from rest_framework.test import APIClient

from tests.base import FixtureTestCase
from apps.contacts.models import Business, Contact
from apps.core.models import Configuration, User
from apps.core.pdf_branding import (
    LOGO_KEY, MAX_LOGO_BYTES, RICH_TEXT_KEYS, PdfBrandingService,
    pdf_branding_context, pdf_page_images, preview_draft_keys, text_key,
)
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


class BrandingContextTests(FixtureTestCase):
    def test_defaults_are_empty(self):
        b = pdf_branding_context('estimate', {})['branding']
        self.assertEqual(b['logo'], '')
        self.assertEqual(b['logo_position'], 'left')
        self.assertEqual(b['company_name'], '')
        self.assertFalse(b['has_letterhead'])
        self.assertEqual(b['text']['below_header'], '')
        self.assertEqual(b['page_footer'], '')

    def test_reads_shared_and_per_document_keys(self):
        _set('pdf_company_name', 'Neal\'s CNC')
        _set('pdf_logo_position', 'right')
        _set(text_key('estimate', 'below_totals'), 'Valid 30 days. Ref {document_number}.')
        _set(text_key('po', 'below_totals'), 'PO terms')
        b = pdf_branding_context('estimate', {'document_number': 'EST-9'})['branding']
        self.assertEqual(b['company_name'], "Neal's CNC")
        self.assertEqual(b['logo_position'], 'right')
        self.assertTrue(b['has_letterhead'])
        self.assertEqual(b['text']['below_totals'], 'Valid 30 days. Ref EST-9.')

    def test_unknown_stored_position_falls_back_to_left(self):
        _set('pdf_logo_position', 'diagonal')
        b = pdf_branding_context('po', {})['branding']
        self.assertEqual(b['logo_position'], 'left')

    def test_page_footer_keeps_formatting_and_renders_page_tokens(self):
        _set(text_key('po', 'page_footer'),
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
        _set(text_key('po', 'below_totals'),
             '<p><span class="size-large">{po_number}</span><script>x</script></p>')
        b = pdf_branding_context('po', {'po_number': 'PO-1'})['branding']
        self.assertEqual(b['company_name'], '<p><strong>Neal</strong></p>')
        self.assertEqual(b['text']['below_totals'], '<p><span class="size-large">PO-1</span></p>')

    def test_placeholder_values_are_escaped_into_rich_text(self):
        _set(text_key('estimate', 'below_header'), '<p>For {contact_fname}</p>')
        b = pdf_branding_context('estimate', {'contact_fname': '<i>Pat</i>'})['branding']
        self.assertEqual(b['text']['below_header'], '<p>For &lt;i&gt;Pat&lt;/i&gt;</p>')

    def test_blank_rich_fields_print_nothing(self):
        _set('pdf_company_name', '<p></p>')
        _set('pdf_company_email', '<p> <strong></strong></p>')
        _set(text_key('estimate', 'below_totals'), '<p><br></p>')
        b = pdf_branding_context('estimate', {})['branding']
        self.assertEqual(b['company_name'], '')
        self.assertFalse(b['has_letterhead'])
        self.assertEqual(b['text']['below_totals'], '')

    def test_rich_text_keys_are_the_letterhead_text_and_every_slot(self):
        self.assertIn('pdf_company_name', RICH_TEXT_KEYS)
        self.assertIn('pdf_company_address', RICH_TEXT_KEYS)
        self.assertIn(text_key('change_order', 'page_footer'), RICH_TEXT_KEYS)
        self.assertNotIn('pdf_logo_position', RICH_TEXT_KEYS)
        self.assertNotIn(LOGO_KEY, RICH_TEXT_KEYS)
        self.assertEqual(len(RICH_TEXT_KEYS), 4 + 3 * 4)

    def test_draft_values_override_the_saved_ones(self):
        _set('pdf_company_name', 'Saved Co')
        _set('pdf_logo_position', 'left')
        _set(text_key('estimate', 'below_totals'), 'Saved terms')
        _set(text_key('estimate', 'page_footer'), 'Saved footer')
        b = pdf_branding_context('estimate', {'document_number': 'EST-9'}, drafts={
            'pdf_company_name': 'Draft Co',
            'pdf_logo_position': 'right',
            text_key('estimate', 'below_totals'): 'Draft terms {document_number}',
            text_key('estimate', 'page_footer'): '',
        })['branding']
        self.assertEqual(b['company_name'], 'Draft Co')
        self.assertEqual(b['logo_position'], 'right')
        self.assertEqual(b['text']['below_totals'], 'Draft terms EST-9')
        # A blanked draft hides the saved value rather than falling back to it.
        self.assertEqual(b['page_footer'], '')

    def test_draft_values_are_not_saved(self):
        _set('pdf_company_name', 'Saved Co')
        pdf_branding_context('po', {}, drafts={'pdf_company_name': 'Draft Co'})
        self.assertEqual(
            Configuration.objects.get(key='pdf_company_name').value, 'Saved Co')

    def test_preview_draft_keys_are_the_letterhead_text_and_own_slots(self):
        keys = preview_draft_keys('po')
        self.assertIn('pdf_logo_position', keys)
        self.assertIn('pdf_company_email', keys)
        self.assertIn(text_key('po', 'below_header'), keys)
        self.assertNotIn(text_key('estimate', 'below_header'), keys)
        # The logo is uploaded deliberately, never previewed from a draft.
        self.assertNotIn(LOGO_KEY, keys)


class LetterheadPreviewTests(FixtureTestCase):
    def test_letterhead_draft_keys_are_the_letterhead_only(self):
        keys = preview_draft_keys('letterhead')
        self.assertIn('pdf_logo_position', keys)
        self.assertIn('pdf_company_name', keys)
        self.assertFalse(any('_pdf_text_' in k for k in keys))
        self.assertNotIn(LOGO_KEY, keys)

    def test_letterhead_preview_is_the_letterhead_alone(self):
        from apps.core.pdf_branding import preview_letterhead_html
        _set(text_key('estimate', 'page_footer'), 'Saved footer')
        html = preview_letterhead_html({
            'pdf_company_name': '<p><strong>Draft Co</strong></p>',
            'pdf_logo_position': 'right',
        })
        self.assertIn('class="letterhead logo-right"', html)
        self.assertIn('<p><strong>Draft Co</strong></p>', html)
        # Same stylesheet as the documents, but no document and no footer.
        self.assertIn('.letterhead .company:first-child', html)
        self.assertNotIn('Saved footer', html)
        self.assertNotIn('<h1>', html)

    def test_letterhead_preview_without_a_letterhead_is_empty(self):
        from apps.core.pdf_branding import preview_letterhead_html
        self.assertNotIn('class="letterhead', preview_letterhead_html({}))


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

    def test_crop_keeps_the_page_width_and_ends_below_the_content(self):
        from weasyprint import HTML
        pdf = HTML(string='<html><body style="margin:40px"><p>Top line</p></body></html>').write_pdf()
        full = Image.open(io.BytesIO(base64.b64decode(pdf_page_images(pdf)[0].split(',', 1)[1])))
        [uri] = pdf_page_images(pdf, crop=True)
        cropped = Image.open(io.BytesIO(base64.b64decode(uri.split(',', 1)[1])))
        self.assertEqual(cropped.width, full.width)
        self.assertLess(cropped.height, full.height / 4)
        # The text itself is inside the crop, not cut off.
        self.assertIsNotNone(cropped.convert('L').point(lambda p: 255 if p < 200 else 0).getbbox())

    def test_crop_of_a_blank_page_is_nothing(self):
        from weasyprint import HTML
        pdf = HTML(string='<html><body></body></html>').write_pdf()
        self.assertEqual(pdf_page_images(pdf, crop=True), [])

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
    """The three document templates render the letterhead and each text slot
    in its fixed position."""

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

    def _fill_slots(self, kind):
        for slot in ('below_header', 'above_lines', 'below_totals', 'page_footer'):
            _set(text_key(kind, slot), f'{kind}-{slot}-TEXT')

    def test_unbranded_estimate_has_no_letterhead_or_slots(self):
        html = render_estimate_html(self.est)
        self.assertNotIn('class="letterhead', html)
        self.assertNotIn('class="doc-text', html)
        self.assertNotIn('class="page-footer', html)
        self.assertIn('EST-BR-1', html)
        self.assertIn('Cut brackets', html)

    def test_estimate_letterhead(self):
        PdfBrandingService.set_logo(
            SimpleUploadedFile('logo.png', _png_bytes(), content_type='image/png'))
        _set('pdf_company_name', 'Neal CNC')
        _set('pdf_company_address', '1 Mill Rd\nSpringfield')
        _set('pdf_company_phone', '555-0100')
        _set('pdf_company_email', 'office@neal.test')
        _set('pdf_logo_position', 'center')
        html = render_estimate_html(self.est)
        self.assertIn('class="letterhead logo-center"', html)
        self.assertIn('<img class="logo" src="data:image/png;base64,', html)
        for expected in ('Neal CNC', '1 Mill Rd', '555-0100', 'office@neal.test'):
            self.assertIn(expected, html)
        self.assertLess(html.index('Neal CNC'), html.index('EST-BR-1'))

    def test_estimate_slots_render_in_order(self):
        self._fill_slots('estimate')
        html = render_estimate_html(self.est)
        order = [
            html.index('estimate-page_footer-TEXT'),
            html.index('EST-BR-1'),
            html.index('estimate-below_header-TEXT'),
            html.index('Acme Fab'),
            html.index('estimate-above_lines-TEXT'),
            html.index('Cut brackets'),
            html.index('estimate-below_totals-TEXT'),
        ]
        self.assertEqual(order, sorted(order))

    def test_estimate_text_placeholders(self):
        _set(text_key('estimate', 'below_totals'),
             'Thanks {contact_fname} of {contact_business} — {estimate_number} / {job_name}')
        html = render_estimate_html(self.est)
        self.assertIn('Thanks Pat of Acme Fab — EST-BR-1 / Bracket run', html)

    def test_slot_markup_is_sanitized(self):
        _set(text_key('estimate', 'above_lines'),
             '<script>x</script><p>ok <img src="file:///etc/passwd"></p>')
        html = render_estimate_html(self.est)
        self.assertNotIn('<script>x', html)
        self.assertNotIn('file:///', html)
        self.assertIn('<div class="doc-text"><p>ok </p></div>', html)

    def test_size_steps_are_styled_and_the_name_is_not_forced_bold(self):
        _set('pdf_company_name', '<p><em>Neal CNC</em></p>')
        html = render_estimate_html(self.est)
        for rule in ('.size-small', '.size-large', '.size-xlarge', '.doc-text ul'):
            self.assertIn(rule, html)
        # The company name's look is the user's formatting now.
        self.assertNotIn('.company-name { font-size: 14px; font-weight: bold; }', html)
        self.assertIn('<p><em>Neal CNC</em></p>', html)

    def test_slots_are_per_document(self):
        self._fill_slots('po')
        self.assertNotIn('po-below_totals-TEXT', render_estimate_html(self.est))

    def test_purchase_order_slots_and_letterhead(self):
        self._fill_slots('po')
        _set('pdf_company_name', 'Neal CNC')
        _set(text_key('po', 'below_totals'), 'Quote {po_number} to {vendor_name}')
        html = render_purchase_order_html(self.po)
        self.assertIn('class="letterhead logo-left"', html)
        self.assertIn('Quote PO-BR-1 to Acme Fab', html)
        order = [
            html.index('Neal CNC'),
            html.index('PO-BR-1'),
            html.index('po-below_header-TEXT'),
            html.index('po-above_lines-TEXT'),
            html.index('Sheet steel'),
            html.index('Quote PO-BR-1'),
        ]
        self.assertEqual(order, sorted(order))

    def test_company_block_without_logo_is_left_aligned(self):
        """Guard for the stylesheet rule: with no logo the company block is
        the letterhead's first child, which the CSS left-aligns."""
        _set('pdf_company_name', 'Neal CNC')
        html = render_purchase_order_html(self.po)
        self.assertIn('.letterhead .company:first-child { text-align: left; }', html)
        self.assertNotIn('<img class="logo"', html)

    def test_issued_purchase_order_shows_its_date(self):
        from datetime import datetime, timezone as dt_timezone
        self.po.issued_date = datetime(2026, 3, 5, 12, 0, tzinfo=dt_timezone.utc)
        self.po.save()
        html = render_purchase_order_html(self.po)
        self.assertIn('<strong>Date:</strong> March 5, 2026', html)

    def test_change_order_slots(self):
        from apps.estimates.change_order_service import ChangeOrderService
        for status in (Estimate.STATUS_OPEN, Estimate.STATUS_ACCEPTED):
            self.est.status = status
            self.est.save()
        # Accepting the estimate approved the job; a CO is drafted on hold.
        JobService.hold_job(self.job.pk, 'CO editing')
        co = ChangeOrderService.create(job_id=self.job.pk)
        self._fill_slots('change_order')
        html = render_change_order_html(co)
        order = [
            html.index(co.change_order_number),
            html.index('change_order-below_header-TEXT'),
            html.index('change_order-above_lines-TEXT'),
            html.index('Line items'),
            html.index('change_order-below_totals-TEXT'),
        ]
        self.assertEqual(order, sorted(order))
        self.assertIn('change_order-page_footer-TEXT', html)

    def test_fully_branded_estimate_still_produces_a_pdf(self):
        PdfBrandingService.set_logo(
            SimpleUploadedFile('logo.png', _png_bytes(), content_type='image/png'))
        _set('pdf_company_name', 'Neal CNC')
        self._fill_slots('estimate')
        _set(text_key('estimate', 'page_footer'), 'Page {page} of {page_count}')
        _set(text_key('estimate', 'below_totals'),
             '<p><strong>Terms</strong></p><ol start="2"><li><p>Net 30</p>'
             '<ul><li><p><span class="size-small">fine print</span></p></li></ul></li></ol>')
        pdf = generate_estimate_pdf(self.est)
        self.assertTrue(pdf.startswith(b'%PDF'))


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

    def test_settings_patch_validates_logo_position(self):
        resp = self.client.patch(
            '/api/settings/', {'pdf_logo_position': 'diagonal'}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('pdf_logo_position', resp.json())
        resp = self.client.patch(
            '/api/settings/', {'pdf_logo_position': 'center'}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertNotIn(LOGO_KEY, resp.json())

    def _preview(self, document, values=None):
        payload = {'document': document}
        if values is not None:
            payload['values'] = values
        return self.client.post('/api/settings/pdf-preview/', payload, format='json')

    def test_preview_returns_page_images_and_the_pdf_for_each_document(self):
        _set('pdf_company_name', 'Neal CNC')
        for kind in ('estimate', 'change_order', 'po'):
            resp = self._preview(kind, {text_key(kind, 'below_totals'): 'Terms {document_number}'})
            self.assertEqual(resp.status_code, 200, (kind, resp.content))
            data = resp.json()
            self.assertGreaterEqual(len(data['pages']), 1, kind)
            self.assertTrue(data['pages'][0].startswith('data:image/png;base64,'), kind)
            self.assertTrue(data['pdf'].startswith('data:application/pdf;base64,'), kind)
            pdf = base64.b64decode(data['pdf'].split(',', 1)[1])
            self.assertTrue(pdf.startswith(b'%PDF'), kind)

    def test_preview_renders_the_drafts_without_saving_them(self):
        from apps.estimates.pdf import preview_estimate_html
        _set(text_key('estimate', 'below_totals'), 'Saved terms')
        html = preview_estimate_html(
            {text_key('estimate', 'below_totals'): 'Draft terms {document_number}'})
        self.assertIn('Draft terms EST-0000', html)
        self.assertNotIn('Saved terms', html)

        resp = self._preview('estimate', {text_key('estimate', 'below_totals'): 'Draft terms'})
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(
            Configuration.objects.get(key=text_key('estimate', 'below_totals')).value,
            'Saved terms')

    def test_each_preview_passes_its_drafts_to_the_template(self):
        from apps.estimates.pdf import preview_change_order_html
        from apps.purchasing.pdf import preview_purchase_order_html
        co = preview_change_order_html({'pdf_company_name': 'Draft Co',
                                        text_key('change_order', 'above_lines'): 'CO draft'})
        self.assertIn('Draft Co', co)
        self.assertIn('CO draft', co)
        po = preview_purchase_order_html({text_key('po', 'below_header'): 'PO draft {vendor_name}'})
        self.assertIn('PO draft Sample Vendor Inc.', po)

    def test_preview_drafts_are_sanitized(self):
        from apps.estimates.pdf import preview_estimate_html
        html = preview_estimate_html({
            'pdf_company_name': '<p>Co<img src="file:///etc/passwd"></p>',
            text_key('estimate', 'below_totals'): '<p><u>Draft</u><script>x</script></p>',
        })
        self.assertNotIn('file:///', html)
        self.assertNotIn('<script>x', html)
        self.assertIn('<p><u>Draft</u></p>', html)

    def test_settings_patch_sanitizes_rich_text_keys(self):
        resp = self.client.patch('/api/settings/', {
            'pdf_company_name': '<p onclick="x"><b>Neal</b><script>x</script></p>',
            text_key('po', 'below_totals'): '<p><span class="size-large" style="color:red">T</span></p>',
        }, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(Configuration.objects.get(key='pdf_company_name').value,
                         '<p><strong>Neal</strong></p>')
        self.assertEqual(Configuration.objects.get(key=text_key('po', 'below_totals')).value,
                         '<p><span class="size-large">T</span></p>')

    def test_settings_patch_leaves_other_keys_alone(self):
        resp = self.client.patch(
            '/api/settings/', {'email_retention_days': '<b>30</b>'}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(
            Configuration.objects.get(key='email_retention_days').value, '<b>30</b>')

    def test_preview_values_are_optional(self):
        resp = self._preview('po')
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_preview_rejects_an_unknown_document(self):
        resp = self._preview('invoice')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('detail', resp.json())

    def test_letterhead_preview_endpoint_returns_the_cropped_band(self):
        resp = self._preview('letterhead', {'pdf_company_name': '<p>Draft Co</p>'})
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertEqual(len(data['pages']), 1)
        band = Image.open(io.BytesIO(base64.b64decode(data['pages'][0].split(',', 1)[1])))
        self.assertGreater(band.width, band.height)
        self.assertTrue(data['pdf'].startswith('data:application/pdf;base64,'))

    def test_letterhead_preview_endpoint_with_nothing_set_has_no_pages(self):
        resp = self._preview('letterhead', {})
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()['pages'], [])

    def test_letterhead_preview_rejects_document_text(self):
        resp = self._preview('letterhead', {text_key('estimate', 'below_header'): 'x'})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('values', resp.json())

    def test_preview_rejects_keys_it_cannot_preview(self):
        for key in (LOGO_KEY, text_key('estimate', 'below_header'), 'units_list'):
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

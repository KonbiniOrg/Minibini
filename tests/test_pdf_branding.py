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
    LOGO_KEY, MAX_LOGO_BYTES, PdfBrandingService, pdf_branding_context,
    render_pdf_text, text_key,
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


class RenderPdfTextTests(FixtureTestCase):
    def test_substitutes_known_placeholders(self):
        self.assertEqual(
            render_pdf_text('Estimate {document_number} for {job_name}',
                            {'document_number': 'EST-1', 'job_name': 'Shelf'}),
            'Estimate EST-1 for Shelf')

    def test_unknown_placeholder_renders_literally(self):
        self.assertEqual(render_pdf_text('Hi {nobody}', {}), 'Hi {nobody}')

    def test_none_value_renders_empty(self):
        self.assertEqual(render_pdf_text('[{job_name}]', {'job_name': None}), '[]')

    def test_stray_braces_never_raise(self):
        """Boilerplate is free text — an unbalanced brace must not block a
        send (str.format would raise here)."""
        for text in ('a { b', '50% } off', '{0}', '{a.b}', '{{x}}'):
            self.assertEqual(render_pdf_text(text, {}), text)

    def test_empty_template(self):
        self.assertEqual(render_pdf_text('', {'a': 'b'}), '')
        self.assertEqual(render_pdf_text(None, {'a': 'b'}), '')


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

    def test_page_footer_escapes_and_renders_page_tokens(self):
        _set(text_key('po', 'page_footer'), 'A <b> & Co — Page {page} of {page_count}')
        footer = pdf_branding_context('po', {})['branding']['page_footer']
        self.assertIn('A &lt;b&gt; &amp; Co', footer)
        self.assertIn('<span class="page-number"></span>', footer)
        self.assertIn('<span class="page-count"></span>', footer)
        self.assertNotIn('{page', footer)


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

    def test_slot_text_is_html_escaped(self):
        _set(text_key('estimate', 'above_lines'), '<script>x</script>')
        html = render_estimate_html(self.est)
        self.assertNotIn('<script>x</script>', html)
        self.assertIn('&lt;script&gt;', html)

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

    def test_preview_returns_a_pdf_for_each_document(self):
        _set('pdf_company_name', 'Neal CNC')
        for kind in ('estimate', 'change_order', 'po'):
            _set(text_key(kind, 'below_totals'), 'Terms for {document_number}')
            resp = self.client.get(f'/api/settings/pdf-preview/?document={kind}')
            self.assertEqual(resp.status_code, 200, kind)
            self.assertEqual(resp['Content-Type'], 'application/pdf')
            self.assertTrue(resp.content.startswith(b'%PDF'), kind)

    def test_preview_rejects_an_unknown_document(self):
        resp = self.client.get('/api/settings/pdf-preview/?document=invoice')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('detail', resp.json())

    def test_endpoints_require_can_manage_config(self):
        plain = APIClient()
        plain.force_authenticate(
            user=User.objects.create_user(username='pdf_plain', password='pass'))
        self.assertEqual(plain.get('/api/settings/pdf-logo/').status_code, 403)
        self.assertEqual(plain.delete('/api/settings/pdf-logo/').status_code, 403)
        self.assertEqual(
            plain.get('/api/settings/pdf-preview/?document=estimate').status_code, 403)

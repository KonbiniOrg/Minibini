from decimal import Decimal
from unittest.mock import patch, MagicMock
from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User, EmailRecord
from apps.estimates.models import Estimate, EstimateLineItem
from apps.jobs.models import Job


class EstimateAPITest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)

    def test_list_estimates(self):
        response = self.client.get('/api/estimates/')
        self.assertEqual(response.status_code, 200)

    def test_estimate_payload_carries_authoritative_total(self):
        """The job-overview Scope block reads estimate.total; the serializer
        must supply the summed line total (qty*price, matching the PDF and
        financials._estimated), not leave the SPA to recompute it."""
        from decimal import Decimal
        from apps.contacts.models import Contact
        contact = Contact.objects.create(first_name='T', last_name='Otal',
                                         email='total@est.com')
        job = Job.objects.create(contact=contact, job_number='JOB-EST-TOTAL-1')
        est = Estimate.objects.create(
            job=job, estimate_number='EST-TOTAL-1', version=1,
            status=Estimate.STATUS_DRAFT,
        )
        EstimateLineItem.objects.create(
            estimate=est, description='One', qty=Decimal('2'),
            units='ea', price=Decimal('100.00'), line_number=1,
        )
        EstimateLineItem.objects.create(
            estimate=est, description='Two', qty=Decimal('1'),
            units='ea', price=Decimal('50.00'), line_number=2,
        )
        response = self.client.get(f'/api/estimates/?job={job.pk}')
        self.assertEqual(response.status_code, 200)
        row = next(r for r in response.data['results']
                   if r['estimate_id'] == est.pk)
        self.assertEqual(str(row['total']), '250.00')

    def test_create_rejected_when_job_already_has_estimate(self):
        """One estimate tree per job: a second create is refused (400), not a
        500 from the unique (job-derived) number collision."""
        from apps.contacts.models import Contact
        contact = Contact.objects.create(first_name='E', last_name='X', email='ex@dup.com')
        job = Job.objects.create(contact=contact, job_number='JOB-EST-DUP-1')
        first = self.client.post('/api/estimates/', {'job': job.pk}, format='json')
        self.assertIn(first.status_code, [200, 201])
        second = self.client.post('/api/estimates/', {'job': job.pk}, format='json')
        self.assertEqual(second.status_code, 400)

    def test_retrieve_estimate(self):
        estimate = Estimate.objects.first()
        response = self.client.get(f'/api/estimates/{estimate.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('line_items', response.data)

    def test_update_estimate(self):
        estimate = Estimate.objects.filter(status=Estimate.STATUS_DRAFT).first()
        if estimate:
            response = self.client.patch(f'/api/estimates/{estimate.pk}/', {
                'status': Estimate.STATUS_DRAFT,
            }, format='json')
            self.assertEqual(response.status_code, 200)

    def _draft_estimate(self):
        est = Estimate.objects.filter(status=Estimate.STATUS_DRAFT).first()
        if est is None:
            est = Estimate.objects.create(
                job=Job.objects.first(),
                estimate_number='EST-ADDLINE-1',
                status=Estimate.STATUS_DRAFT,
            )
        return est

    def test_manual_line_item_create_succeeds(self):
        # Add Line Item is back: a hand-line with an accounting category creates (201).
        from apps.core.models import AccountingCategory
        cat = AccountingCategory.objects.first() or AccountingCategory.objects.create(name='c')
        estimate = self._draft_estimate()
        response = self.client.post(f'/api/estimates/{estimate.pk}/line-items/', {
            'qty': '2.00',
            'units': 'ea',
            'description': 'API test item',
            'price': '100.00',
            'accounting_category': cat.pk,
        }, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['description'], 'API test item')

    def test_manual_line_item_create_requires_accounting_category(self):
        # Hand-line AC rule (Decision 1): a line with no atom source needs an AC.
        estimate = self._draft_estimate()
        response = self.client.post(f'/api/estimates/{estimate.pk}/line-items/', {
            'qty': '2.00', 'units': 'ea', 'description': 'no cat', 'price': '5.00',
        }, format='json')
        self.assertEqual(response.status_code, 400)

    def test_manual_line_item_create_rejected_on_non_draft(self):
        from apps.core.models import AccountingCategory
        cat = AccountingCategory.objects.first() or AccountingCategory.objects.create(name='c')
        estimate = self._draft_estimate()
        Estimate.objects.filter(pk=estimate.pk).update(status=Estimate.STATUS_OPEN)
        response = self.client.post(f'/api/estimates/{estimate.pk}/line-items/', {
            'qty': '1.00', 'units': 'ea', 'description': 'x', 'price': '5.00',
            'accounting_category': cat.pk,
        }, format='json')
        self.assertEqual(response.status_code, 400)

    def test_list_line_items(self):
        estimate = Estimate.objects.first()
        response = self.client.get(f'/api/estimates/{estimate.pk}/line-items/')
        self.assertEqual(response.status_code, 200)

    def test_delete_line_item(self):
        line_item = EstimateLineItem.objects.first()
        if line_item:
            estimate = line_item.estimate
            response = self.client.delete(
                f'/api/estimates/{estimate.pk}/line-items/{line_item.pk}/'
            )
            self.assertEqual(response.status_code, 200)

    def test_discard_draft_returns_200_with_message(self):
        job = Job.objects.first()
        estimate = Estimate.objects.create(
            job=job,
            estimate_number='EST-DISCARD-001',
            status=Estimate.STATUS_DRAFT,
        )
        pk = estimate.pk
        response = self.client.delete(f'/api/estimates/{pk}/?confirm=true')
        self.assertEqual(response.status_code, 200)
        self.assertIn('message', response.data)
        self.assertFalse(Estimate.objects.filter(pk=pk).exists())

    def test_discard_non_draft_returns_400(self):
        job = Job.objects.first()
        estimate = Estimate.objects.create(
            job=job,
            estimate_number='EST-DISCARD-002',
            status=Estimate.STATUS_DRAFT,
        )
        Estimate.objects.filter(pk=estimate.pk).update(status=Estimate.STATUS_OPEN)
        response = self.client.delete(f'/api/estimates/{estimate.pk}/?confirm=true')
        self.assertEqual(response.status_code, 400)
        self.assertTrue(Estimate.objects.filter(pk=estimate.pk).exists())


class EstimateSendTest(BaseTestCase):
    """The new /api/estimates/{id}/send-defaults/ + /send/ endpoints."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)
        self.job = Job.objects.first()
        self.estimate = Estimate.objects.create(
            job=self.job,
            estimate_number='EST-SEND-001',
            status=Estimate.STATUS_DRAFT,
        )
        from apps.core.models import AccountingCategory
        cat = AccountingCategory.objects.first() or AccountingCategory.objects.create(name='c')
        EstimateLineItem.objects.create(
            estimate=self.estimate,
            line_number=1,
            qty='1.00', units='ea',
            description='Bracket assembly',
            price='100.00',
            accounting_category=cat,  # hand-lines need an AC before send
        )

    def test_send_defaults_returns_to_subject_body_and_attachment_preview(self):
        response = self.client.get(f'/api/estimates/{self.estimate.pk}/send-defaults/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('to', response.data)
        self.assertIn('subject', response.data)
        self.assertIn('body', response.data)
        self.assertIn('attachments_preview', response.data)
        # Default contact email should be in the To field
        self.assertEqual(response.data['to'], self.job.contact.email)
        # Subject template default mentions the estimate number
        self.assertIn(self.estimate.estimate_number, response.data['subject'])
        # Attachment preview names the auto-attached PDF
        self.assertEqual(len(response.data['attachments_preview']), 1)
        self.assertEqual(
            response.data['attachments_preview'][0]['filename'],
            f'Estimate-{self.estimate.estimate_number}.pdf',
        )

    @patch('apps.estimates.pdf.generate_estimate_pdf')
    @patch('django.core.mail.EmailMessage')
    def test_send_happy_path_persists_outbound_and_transitions_status(
        self, MockEmailMessage, mock_pdf,
    ):
        MockEmailMessage.return_value = MagicMock()
        mock_pdf.return_value = b'%PDF-estimate'

        response = self.client.post(
            f'/api/estimates/{self.estimate.pk}/send/',
            {
                'to': 'jane@example.com',
                'subject': 'Estimate ' + self.estimate.estimate_number,
                'body': 'Hi Jane, please review.',
                'cc': '',
                'bcc': '',
            },
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)

        self.estimate.refresh_from_db()
        self.assertEqual(self.estimate.status, Estimate.STATUS_OPEN)

        # An outbound EmailRecord exists, linked to this Estimate's job.
        outbound = EmailRecord.objects.get(
            direction=EmailRecord.OUTBOUND, job=self.job,
        )
        self.assertIsNotNone(outbound.sent_at)
        self.assertEqual(outbound.last_send_error, '')

    @patch('apps.estimates.pdf.generate_estimate_pdf')
    @patch('django.core.mail.EmailMessage')
    def test_send_smtp_failure_returns_error_and_keeps_status(
        self, MockEmailMessage, mock_pdf,
    ):
        fail_msg = MagicMock()
        fail_msg.send.side_effect = RuntimeError('SMTP unreachable')
        MockEmailMessage.return_value = fail_msg
        mock_pdf.return_value = b'%PDF-estimate'

        response = self.client.post(
            f'/api/estimates/{self.estimate.pk}/send/',
            {'to': 'jane@example.com', 'subject': 'Test', 'body': 'Test'},
            format='json',
        )
        self.assertEqual(response.status_code, 502)
        self.estimate.refresh_from_db()
        # Status NOT advanced because SMTP failed.
        self.assertEqual(self.estimate.status, Estimate.STATUS_DRAFT)
        # Failure persisted on the EmailRecord.
        outbound = EmailRecord.objects.get(
            direction=EmailRecord.OUTBOUND, job=self.job,
        )
        self.assertIsNone(outbound.sent_at)
        self.assertIn('SMTP unreachable', outbound.last_send_error)

    def test_send_missing_to_returns_400(self):
        response = self.client.post(
            f'/api/estimates/{self.estimate.pk}/send/',
            {'subject': 'X', 'body': 'X'},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_send_defaults_resolves_object_url_placeholder(self):
        """Body templates can include {object_url} — for an estimate it resolves
        to the customer portal token URL (<base>/portal/?token=<token>)."""
        from apps.core.models import Configuration
        Configuration.objects.update_or_create(
            key='our_public_url',
            defaults={'value': 'https://customer.nealscnc.com'},
        )
        Configuration.objects.update_or_create(
            key='estimate_email_body_template',
            defaults={'value': 'Hi {contact_fname}, see {object_url}'},
        )
        response = self.client.get(f'/api/estimates/{self.estimate.pk}/send-defaults/')
        self.assertEqual(response.status_code, 200)
        self.estimate.refresh_from_db()
        expected_url = (
            f'https://customer.nealscnc.com/portal/?token={self.estimate.public_token}'
            '&doc=estimate'
        )
        self.assertIn(expected_url, response.data['body'])

    def test_send_defaults_object_url_defaults_to_example_com(self):
        """Without an our_public_url Config row, fall back to example.com."""
        from apps.core.models import Configuration
        Configuration.objects.filter(key='our_public_url').delete()
        Configuration.objects.update_or_create(
            key='estimate_email_body_template',
            defaults={'value': '{object_url}'},
        )
        response = self.client.get(f'/api/estimates/{self.estimate.pk}/send-defaults/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('https://example.com/portal/?token=', response.data['body'])


class EstimateAdjustmentLineAPITest(BaseTestCase):
    """Tests for POST /api/estimates/{id}/adjustment-lines/ and auto-recompute."""

    def setUp(self):
        super().setUp()
        from rest_framework.test import APIClient
        from decimal import Decimal
        from apps.core.models import AccountingCategory
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)
        self.labor = AccountingCategory.objects.get(pk=901)
        self.job = Job.objects.first()
        self.est = Estimate.objects.create(
            job=self.job,
            estimate_number='EST-ADJ-001',
            status=Estimate.STATUS_DRAFT,
        )
        EstimateLineItem.objects.create(
            estimate=self.est, line_number=1, qty=Decimal('1'),
            units='ea', description='Line A', price=Decimal('100.00'),
            accounting_category=self.labor,
        )
        EstimateLineItem.objects.create(
            estimate=self.est, line_number=2, qty=Decimal('1'),
            units='ea', description='Line B', price=Decimal('40.00'),
            accounting_category=self.labor,
        )

    def test_adjustment_line_created_with_correct_price(self):
        from decimal import Decimal
        from apps.jobs.models import RateScheme
        rush = RateScheme.objects.create(
            name='Rush', algorithm=RateScheme.PERCENTAGE,
            rate=Decimal('15.00'), unit_label='%',
            accounting_category=self.labor,
        )
        resp = self.client.post(
            f'/api/estimates/{self.est.pk}/adjustment-lines/',
            {'adjustment_service': rush.pk, 'target_category_ids': []},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 201)
        # 15% of (100 + 40) = 21.00
        self.assertEqual(resp.json()['price'], '21.00')

    def test_recalculate_endpoint_removed(self):
        """The recalculate endpoint no longer exists (adjustments auto-recompute)."""
        from decimal import Decimal
        from apps.jobs.models import RateScheme
        rush = RateScheme.objects.create(
            name='Rush5', algorithm=RateScheme.PERCENTAGE,
            rate=Decimal('10.00'), unit_label='%',
            accounting_category=self.labor,
        )
        resp = self.client.post(
            f'/api/estimates/{self.est.pk}/adjustment-lines/',
            {'adjustment_service': rush.pk, 'target_category_ids': []},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 201)
        lid = resp.json()['line_item_id']
        r2 = self.client.post(
            f'/api/estimates/{self.est.pk}/line-items/{lid}/recalculate/',
            content_type='application/json',
        )
        self.assertEqual(r2.status_code, 404)


class EstimateLineBackingAPITest(BaseTestCase):
    """derive_estimate_backing / backing_total on
    GET /api/estimates/{id}/line-items/ (EstimateLineItemSerializer)."""

    def setUp(self):
        super().setUp()
        from decimal import Decimal
        from apps.core.models import AccountingCategory
        from apps.contacts.models import Contact
        from apps.jobs.models import RateScheme

        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)

        self.cat = AccountingCategory.objects.create(
            code='LAB-EBACK', name='Labor-EstBacking', taxable=False,
        )
        self.contact = Contact.objects.create(
            first_name='Est', last_name='Backing',
            email='estbacking@test.com', mobile_number='555-0400',
        )
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_DRAFT,
            job_number='JOB-EBACK-0001',
        )
        self.scheme = RateScheme.objects.create(
            name='Hourly-EBack', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('100.00'), unit_label='hour',
            accounting_category=self.cat,
        )
        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-EBACK-1', version=1,
            status=Estimate.STATUS_DRAFT,
        )

    def _row(self, line_item):
        resp = self.client.get(f'/api/estimates/{self.estimate.pk}/line-items/')
        self.assertEqual(resp.status_code, 200, resp.data)
        data = resp.data
        items = data.get('results', data) if isinstance(data, dict) else data
        return next(r for r in items if r['line_item_id'] == line_item.pk)

    def _task(self, name, est_qty):
        from decimal import Decimal
        from apps.jobs.models import Task
        task = Task(job=self.job, name=name, est_qty=Decimal(est_qty))
        task.stamp_from_scheme(self.scheme)
        task.save()
        return task

    def _material(self, description, quantity, sell_price):
        from decimal import Decimal
        from apps.inventory.models import Material
        return Material.objects.create(
            job=self.job, description=description,
            quantity=Decimal(quantity), sell_price=Decimal(sell_price),
            accounting_category=self.cat,
        )

    def test_backing_planned_work_on_task_sourced_line(self):
        """A wizard line composed from a single task, still in sync ->
        'planned_work'; backing_total mirrors compute_estimate_amount."""
        from apps.estimates.services import EstimateWizardService

        task = self._task('Build-EBack', est_qty='2')
        li = EstimateWizardService.add_atoms_to_new_line_item(
            self.estimate, [{'type': 'task', 'id': task.pk}])

        row = self._row(li)
        self.assertEqual(row['backing'], 'planned_work')
        self.assertEqual(Decimal(row['backing_total']), Decimal('200.00'))

    def test_backing_planned_materials_on_materials_only_line(self):
        """A wizard line composed only from materials -> 'planned_materials'."""
        from apps.estimates.services import EstimateWizardService

        m1 = self._material('Steel', '2', '5.00')
        m2 = self._material('Bolts', '3', '1.00')
        li = EstimateWizardService.add_atoms_to_new_line_item(
            self.estimate,
            [{'type': 'material', 'id': m1.pk}, {'type': 'material', 'id': m2.pk}])

        row = self._row(li)
        self.assertEqual(row['backing'], 'planned_materials')
        self.assertEqual(Decimal(row['backing_total']), Decimal('13.00'))

    def test_backing_planned_work_on_mixed_task_and_material_line(self):
        """A wizard line with a task AND a material among its sources ->
        'planned_work' (any task among sources wins over materials-only)."""
        from apps.estimates.services import EstimateWizardService

        task = self._task('Build-Mix', est_qty='1')
        material = self._material('Mix-Steel', '2', '5.00')
        li = EstimateWizardService.add_atoms_to_new_line_item(
            self.estimate,
            [{'type': 'task', 'id': task.pk}, {'type': 'material', 'id': material.pk}])

        row = self._row(li)
        self.assertEqual(row['backing'], 'planned_work')

    def test_backing_edited_when_sourced_line_out_of_sync(self):
        """A sourced line whose stored price no longer matches the source
        sum -> 'edited', regardless of source kind (materials-only here)."""
        from apps.estimates.services import EstimateWizardService

        m1 = self._material('Edited-Steel', '2', '5.00')
        li = EstimateWizardService.add_atoms_to_new_line_item(
            self.estimate, [{'type': 'material', 'id': m1.pk}])
        li.price = Decimal('999.00')
        li.save()

        row = self._row(li)
        self.assertEqual(row['backing'], 'edited')

    def test_backing_from_catalog_on_service_item_line(self):
        """A line pointing at a ServiceItem (deferred service descriptor) ->
        'from_catalog'."""
        from apps.estimates.models import ServiceItem

        si = ServiceItem.objects.create(
            template_name='Catalog Service', rate_scheme=self.scheme,
        )
        li = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=1, qty=Decimal('1'),
            units='hour', description='Catalog service', price=Decimal('100.00'),
            accounting_category=self.cat, service_item=si,
        )

        row = self._row(li)
        self.assertEqual(row['backing'], 'from_catalog')

    def test_backing_stays_from_catalog_after_service_line_acceptance(self):
        """Consequence (1) of the precedence order (see derive_estimate_backing's
        docstring): a service-item line keeps 'from_catalog' even after
        acceptance crystallizes it into a live Task source on that same line
        — rule 2 (catalog ref) fires before the sources rules, for the
        line's whole life, not just pre-crystallization."""
        from apps.estimates.models import ServiceItem
        from apps.estimates.services import EstimateService
        from apps.estimates.acceptance import EstimateAcceptanceService

        si = ServiceItem.objects.create(
            template_name='Accept-Catalog Service', rate_scheme=self.scheme,
        )
        li = EstimateService.add_line_item_from_service(self.estimate.pk, si.pk, qty=2)

        EstimateAcceptanceService.on_accept(self.estimate)
        li.refresh_from_db()
        self.assertTrue(li.sources.exists())  # now crystallized to a Task source

        row = self._row(li)
        self.assertEqual(row['backing'], 'from_catalog')

    def test_backing_from_catalog_on_inventory_item_line(self):
        """A line pointing at a catalog InventoryItem -> 'from_catalog'."""
        from apps.inventory.models import InventoryItem

        item = InventoryItem.objects.create(
            code='EBACK-ITEM', accounting_category=self.cat,
            qty_on_hand=Decimal('10'),
        )
        li = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=1, qty=Decimal('1'),
            units='each', description='Catalog item', price=Decimal('25.00'),
            accounting_category=self.cat, inventory_item=item,
        )

        row = self._row(li)
        self.assertEqual(row['backing'], 'from_catalog')

    def test_backing_hand_on_bare_material_line(self):
        """A bare `is_material=True` line with no inventory_item is NOT
        'from_catalog' — it stays 'hand' until crystallization narrows it
        (spec clarification, task-6 brief)."""
        li = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=1, qty=Decimal('1'),
            units='each', description='Bare material', price=Decimal('12.00'),
            accounting_category=self.cat, is_material=True,
        )

        row = self._row(li)
        self.assertEqual(row['backing'], 'hand')
        self.assertIsNone(row['backing_total'])

    def test_backing_adjustment_on_adjustment_line(self):
        """An adjustment line (adjustment_service set) -> 'adjustment', even
        though it carries no sources and no catalog reference."""
        from apps.jobs.models import RateScheme

        rush = RateScheme.objects.create(
            name='Rush-EBack', algorithm=RateScheme.PERCENTAGE,
            rate=Decimal('10.00'), unit_label='%',
            accounting_category=self.cat,
        )
        li = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=1, qty=Decimal('1'),
            units='%', description='Rush', price=Decimal('10.00'),
            accounting_category=self.cat, adjustment_service=rush,
            adjustment_percent=Decimal('10.00'),
        )

        row = self._row(li)
        self.assertEqual(row['backing'], 'adjustment')
        self.assertIsNone(row['backing_total'])

    def test_backing_hand_and_null_total_on_plain_hand_line(self):
        """A bare hand line — no sources, no catalog ref, not an adjustment
        -> 'hand'; backing_total null."""
        li = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=1, qty=Decimal('1'),
            units='each', description='Misc', price=Decimal('20.00'),
            accounting_category=self.cat,
        )

        row = self._row(li)
        self.assertEqual(row['backing'], 'hand')
        self.assertIsNone(row['backing_total'])

    def test_backing_falls_through_to_hand_when_all_sources_dangling(self):
        """A line's sources ALL dangling (their atoms already deleted, a
        legal pre-purge state) is treated as having no sources at all —
        GET succeeds (200, not 500) and backing falls through to 'hand',
        with a null backing_total and null per-row detail fields."""
        from apps.estimates.services import EstimateWizardService
        from apps.inventory.models import Material

        m1 = self._material('Dangle-Steel', '2', '5.00')
        li = EstimateWizardService.add_atoms_to_new_line_item(
            self.estimate, [{'type': 'material', 'id': m1.pk}])
        self.assertEqual(li.sources.count(), 1)

        # Simulate pre-purge dangling data: bulk-delete bypasses
        # Material.delete()'s source-row purge (CLAUDE.md's own warning
        # against QuerySet.delete() bypassing custom delete() — used here
        # deliberately to reproduce the dangling state).
        Material.objects.filter(pk=m1.pk).delete()

        row = self._row(li)
        self.assertEqual(row['backing'], 'hand')
        self.assertIsNone(row['backing_total'])
        src_row = row['sources'][0]
        self.assertIsNone(src_row['description'])
        self.assertIsNone(src_row['computed_amount'])
        self.assertIsNone(src_row['qty'])
        self.assertIsNone(src_row['units'])
        self.assertIsNone(src_row['rate'])

    def test_backing_total_and_edited_when_sources_partially_dangling(self):
        """A partially-dangling line sums/classifies only what still
        resolves: with one of two material sources deleted, backing_total
        reflects only the survivor and the now-stale stored price reads
        as 'edited' rather than crashing."""
        from apps.estimates.services import EstimateWizardService
        from apps.inventory.models import Material

        m1 = self._material('Dangle-Steel-1', '2', '5.00')  # 10.00
        m2 = self._material('Dangle-Bolts-1', '3', '1.00')  # 3.00
        li = EstimateWizardService.add_atoms_to_new_line_item(
            self.estimate,
            [{'type': 'material', 'id': m1.pk}, {'type': 'material', 'id': m2.pk}])
        self.assertEqual(li.sources.count(), 2)

        Material.objects.filter(pk=m2.pk).delete()

        row = self._row(li)
        self.assertEqual(row['backing'], 'edited')
        self.assertEqual(Decimal(row['backing_total']), Decimal('10.00'))


class EstimateLineNeedsWorkDecisionAPITest(BaseTestCase):
    """needs_work_decision on GET /api/estimates/{id}/line-items/
    (EstimateLineItemSerializer) — the server-computed single source of
    truth for the checklist's mint/decline affordances (final-review fix,
    finding 1: kills the client-side predicate duplication that used to
    live in EstimateEditView.svelte's needsWorkDecision(li))."""

    def setUp(self):
        super().setUp()
        from apps.core.models import AccountingCategory
        from apps.contacts.models import Contact
        from apps.jobs.models import RateScheme

        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)

        self.cat = AccountingCategory.objects.create(
            code='LAB-NWD', name='Labor-NeedsWorkDecision', taxable=False,
        )
        self.deposit_cat = AccountingCategory.objects.create(
            code='DEP-NWD', name='Deposit-NeedsWorkDecision', taxable=False,
            is_deposit=True,
        )
        self.contact = Contact.objects.create(
            first_name='Nwd', last_name='Test',
            email='nwd@test.com', mobile_number='555-0401',
        )
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_APPROVED,
            job_number='JOB-NWD-0001',
        )
        self.scheme = RateScheme.objects.create(
            name='Hourly-NWD', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('100.00'), unit_label='hour',
            accounting_category=self.cat,
        )
        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-NWD-1', version=1,
            status=Estimate.STATUS_ACCEPTED,
        )

    def _row(self, line_item):
        resp = self.client.get(f'/api/estimates/{self.estimate.pk}/line-items/')
        self.assertEqual(resp.status_code, 200, resp.data)
        data = resp.data
        items = data.get('results', data) if isinstance(data, dict) else data
        return next(r for r in items if r['line_item_id'] == line_item.pk)

    def test_plain_unanswered_hand_line_needs_a_decision(self):
        li = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=1, description='Plain hand line',
            qty=Decimal('1'), price=Decimal('50.00'), accounting_category=self.cat,
        )
        self.assertTrue(self._row(li)['needs_work_decision'])

    def test_sourced_line_does_not_need_a_decision(self):
        from apps.jobs.models import Task
        li = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=1, description='Sourced line',
            qty=Decimal('2'), price=Decimal('200.00'), accounting_category=self.cat,
        )
        task = Task(job=self.job, name='Build-NWD', est_qty=Decimal('2'))
        task.stamp_from_scheme(self.scheme)
        task.save()
        from apps.estimates.models import EstimateLineItemSource
        EstimateLineItemSource.objects.create(
            estimate_line_item=li, source_type=EstimateLineItemSource.SOURCE_TASK,
            source_pk=task.pk,
        )
        self.assertFalse(self._row(li)['needs_work_decision'])

    def test_declined_line_does_not_need_a_decision(self):
        li = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=1, description='Declined line',
            qty=Decimal('1'), price=Decimal('50.00'), accounting_category=self.cat,
            work_declined=True,
        )
        self.assertFalse(self._row(li)['needs_work_decision'])

    def test_deposit_line_does_not_need_a_decision(self):
        li = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=1, description='Deposit',
            qty=Decimal('1'), price=Decimal('500.00'), accounting_category=self.deposit_cat,
        )
        self.assertFalse(self._row(li)['needs_work_decision'])

    def test_adjustment_line_does_not_need_a_decision(self):
        from apps.jobs.models import RateScheme
        adj_scheme = RateScheme.objects.create(
            name='Rush-NWD', algorithm=RateScheme.PERCENTAGE,
            rate=Decimal('10'), unit_label='%', accounting_category=self.cat,
        )
        li = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=1, description='Rush surcharge',
            qty=Decimal('1'), price=Decimal('50.00'),
            adjustment_service=adj_scheme, adjustment_percent=adj_scheme.rate,
        )
        self.assertFalse(self._row(li)['needs_work_decision'])

    def test_catalog_identity_line_does_not_need_a_decision(self):
        """Defensive belt: a bare-sourced catalog-identity line (shouldn't
        normally happen post-accept — crystallization always leaves a
        source — but the serializer must not depend on that)."""
        from apps.estimates.models import ServiceItem
        service_item = ServiceItem.objects.create(
            template_name='NWD service', rate_scheme=self.scheme,
        )
        li = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=1, description='NWD service',
            qty=Decimal('1'), price=Decimal('100.00'), accounting_category=self.cat,
            service_item=service_item,
        )
        self.assertFalse(self._row(li)['needs_work_decision'])


class EstimateUnexpireAPITest(BaseTestCase):
    """POST /api/estimates/{id}/unexpire/ — in-place reactivation, gated on
    can_manage_jobs OR can_manage_financials (not the usual CanManageJobOrPM
    per-job scope)."""

    def setUp(self):
        super().setUp()
        from decimal import Decimal
        from tests.base import grant_atoms
        from apps.contacts.models import Contact
        from apps.core.models import AccountingCategory
        from apps.deliverables.models import Deliverable
        from apps.estimates.services import EstimateService
        from apps.jobs.services import JobService

        self.client = APIClient()
        self.contact = Contact.objects.create(
            first_name='Ex', last_name='Piree', email='ex@piree.com',
            mobile_number='555-0199',
        )
        cat = AccountingCategory.objects.first() or AccountingCategory.objects.create(
            code='SVC', name='Services')
        self.job = JobService.create_job(name='Lapsed Job', contact=self.contact)
        Deliverable.objects.create(
            job=self.job, description='One thing',
            qty_ordered=Decimal('1'), units='each')
        self.est = EstimateService.create_for_job(self.job.pk)
        EstimateLineItem.objects.create(
            estimate=self.est, description='Do the thing',
            qty=Decimal('1'), units='each', price=Decimal('75.00'),
            accounting_category=cat,
        )
        EstimateService.mark_open(self.est.pk)
        self.est.refresh_from_db()
        self.est.status = Estimate.STATUS_EXPIRED
        self.est.save()

        self.jobs_user = grant_atoms(
            User.objects.create_user(username='unexp_jobs', password='x'),
            'can_manage_jobs',
        )
        self.fin_user = grant_atoms(
            User.objects.create_user(username='unexp_fin', password='x'),
            'can_manage_financials',
        )
        self.plain_user = User.objects.create_user(username='unexp_plain', password='x')

    def test_unexpire_with_can_manage_jobs_succeeds(self):
        self.client.force_authenticate(user=self.jobs_user)
        response = self.client.post(f'/api/estimates/{self.est.pk}/unexpire/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], Estimate.STATUS_OPEN)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_SUBMITTED)

    def test_unexpire_with_can_manage_financials_succeeds(self):
        self.client.force_authenticate(user=self.fin_user)
        response = self.client.post(f'/api/estimates/{self.est.pk}/unexpire/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], Estimate.STATUS_OPEN)

    def test_unexpire_without_either_atom_is_forbidden(self):
        self.client.force_authenticate(user=self.plain_user)
        response = self.client.post(f'/api/estimates/{self.est.pk}/unexpire/')
        self.assertEqual(response.status_code, 403)
        self.est.refresh_from_db()
        self.assertEqual(self.est.status, Estimate.STATUS_EXPIRED)

    def test_unexpire_job_pm_without_atom_is_forbidden(self):
        """Unlike every other estimate action, this is NOT PM-scoped — being
        the job's own project_manager isn't enough without the atom."""
        pm = User.objects.create_user(username='unexp_pm', password='x')
        self.job.refresh_from_db()
        self.job.project_manager = pm
        self.job.save()
        self.client.force_authenticate(user=pm)
        response = self.client.post(f'/api/estimates/{self.est.pk}/unexpire/')
        self.assertEqual(response.status_code, 403)

    def test_unexpire_non_expired_returns_400(self):
        self.client.force_authenticate(user=self.jobs_user)
        Estimate.objects.filter(pk=self.est.pk).update(status=Estimate.STATUS_OPEN)
        response = self.client.post(f'/api/estimates/{self.est.pk}/unexpire/')
        self.assertEqual(response.status_code, 400)

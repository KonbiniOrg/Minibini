"""One-click "send all" on the source-pull (wizard) pages.

`send_all_atoms` projects every currently-available atom onto the document,
one line per atom. Claimed atoms are skipped (the pool's state already
excludes them), so unlike the invoice's fresh-document seed_all_atoms it
composes with lines already present. Draft-only, like every wizard write.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, AppState, Configuration, User
from apps.estimates.models import Estimate, EstimateLineItem
from apps.estimates.services import EstimateWizardService
from apps.inventory.models import Material
from apps.invoicing.models import Invoice, InvoiceLineItem
from apps.invoicing.services import InvoiceWizardService
from apps.jobs.models import Blep, Job, RateScheme, Task


class SendAllAtomsBase(TestCase):
    def setUp(self):
        Configuration.objects.create(
            key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        AppState.objects.create(key='invoice_counter', value='0')
        self.cat = AccountingCategory.objects.create(name='saa', code='SAA')
        self.scheme = RateScheme.objects.create(
            name='S-saa', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('10'), unit_label='ea', accounting_category=self.cat,
        )
        self.contact = Contact.objects.create(
            first_name='Send', last_name='All', email='saa@test.com',
        )
        self.job = Job.objects.create(
            job_number='JOB-SAA-1', contact=self.contact,
            status=Job.STATUS_IN_PROGRESS,
        )
        self.task_a = Task(
            job=self.job, name='A',
            est_qty=Decimal('2'), actual_qty=Decimal('2'),
            status=Task.STATUS_COMPLETE,
        )
        self.task_a.stamp_from_scheme(self.scheme)
        self.task_a.save()
        self.task_b = Task(
            job=self.job, name='B',
            est_qty=Decimal('3'), actual_qty=Decimal('3'),
            status=Task.STATUS_COMPLETE,
        )
        self.task_b.stamp_from_scheme(self.scheme)
        self.task_b.save()
        self.material = Material.objects.create(
            job=self.job, description='loose sheet',
            quantity=Decimal('1'), sell_price=Decimal('20.00'),
            accounting_category=self.cat,
            consumption_state=Material.CONSUMPTION_STATE_CONSUMED,
        )


class EstimateSendAllTest(SendAllAtomsBase):
    def setUp(self):
        super().setUp()
        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-SAA-1',
            status=Estimate.STATUS_DRAFT,
        )

    def test_projects_every_available_atom_one_line_each(self):
        created = EstimateWizardService.send_all_atoms(self.estimate)
        self.assertEqual(created, 3)  # two tasks + one material
        self.assertEqual(
            EstimateLineItem.objects.filter(estimate=self.estimate).count(), 3)

    def test_skips_claimed_atoms_and_composes_with_existing_lines(self):
        EstimateWizardService.add_atoms_to_new_line_item(
            self.estimate, [{'type': 'task', 'id': self.task_a.pk}])
        created = EstimateWizardService.send_all_atoms(self.estimate)
        self.assertEqual(created, 2)  # task_b + material; task_a already claimed
        self.assertEqual(
            EstimateLineItem.objects.filter(estimate=self.estimate).count(), 3)

    def test_rejects_non_draft(self):
        EstimateWizardService.add_atoms_to_new_line_item(
            self.estimate, [{'type': 'task', 'id': self.task_a.pk}])
        Estimate.objects.filter(pk=self.estimate.pk).update(
            status=Estimate.STATUS_OPEN)
        self.estimate.refresh_from_db()
        with self.assertRaises(ValidationError):
            EstimateWizardService.send_all_atoms(self.estimate)

    def test_api_endpoint(self):
        from tests.base import grant_atoms
        client = APIClient()
        client.force_authenticate(user=grant_atoms(
            User.objects.create_user(username='saa_mgr', password='x'),
            'can_manage_jobs'))
        resp = client.post(
            f'/api/estimates/{self.estimate.pk}/send-all-atoms/')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['created'], 3)


class InvoiceSendAllTest(SendAllAtomsBase):
    def setUp(self):
        super().setUp()
        self.invoice = Invoice.objects.create(
            job=self.job, status=Invoice.STATUS_DRAFT)

    def test_projects_every_available_atom_one_line_each(self):
        created = InvoiceWizardService.send_all_atoms(self.invoice)
        self.assertEqual(created, 3)
        self.assertEqual(
            InvoiceLineItem.objects.filter(invoice=self.invoice).count(), 3)

    def test_composes_with_existing_lines_unlike_seed(self):
        InvoiceWizardService.add_atoms_to_new_line_item(
            self.invoice, [{'type': 'task', 'id': self.task_a.pk}])
        created = InvoiceWizardService.send_all_atoms(self.invoice)
        self.assertEqual(created, 2)
        self.assertEqual(
            InvoiceLineItem.objects.filter(invoice=self.invoice).count(), 3)

    def test_rejects_non_draft(self):
        Invoice.objects.filter(pk=self.invoice.pk).update(
            status=Invoice.STATUS_OPEN)
        self.invoice.refresh_from_db()
        with self.assertRaises(ValidationError):
            InvoiceWizardService.send_all_atoms(self.invoice)

    def test_api_endpoint(self):
        from tests.base import grant_atoms
        client = APIClient()
        client.force_authenticate(user=grant_atoms(
            User.objects.create_user(username='saa_fin', password='x'),
            'can_manage_financials'))
        resp = client.post(
            f'/api/invoices/{self.invoice.pk}/send-all-atoms/')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['created'], 3)

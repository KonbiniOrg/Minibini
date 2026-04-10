from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.invoicing.models import Invoice, InvoiceLineItem, InvoiceLineItemSource
from apps.invoicing.services import InvoiceWizardService, ClaimConflict
from apps.jobs.models import Job, WorkOrder, Task, Blep
from apps.contacts.models import Contact, Business
from apps.core.models import Configuration, AccountingCategory
from apps.inventory.models import Material, PriceListItem


class OpenForJobTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        self.contact = Contact.objects.create(
            first_name='Jane', last_name='Doe',
            email='jane@example.com', mobile_number='555-0000',
        )
        self.approved_job = Job.objects.create(contact=self.contact, status=Job.STATUS_APPROVED, job_number='JOB-2026-0001')
        self.draft_job = Job.objects.create(contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0002')
        self.rejected_job = Job.objects.create(contact=self.contact, status=Job.STATUS_REJECTED, job_number='JOB-2026-0003')
        self.completed_job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_APPROVED, job_number='JOB-2026-0004'
        )
        self.completed_job.status = Job.STATUS_COMPLETED
        self.completed_job.save()

    def test_creates_draft_when_none_exists(self):
        invoice = InvoiceWizardService.open_for_job(self.approved_job)
        self.assertEqual(invoice.status, Invoice.STATUS_DRAFT)
        self.assertEqual(invoice.job, self.approved_job)

    def test_returns_existing_draft(self):
        first = InvoiceWizardService.open_for_job(self.approved_job)
        second = InvoiceWizardService.open_for_job(self.approved_job)
        self.assertEqual(first.pk, second.pk)

    def test_creates_new_draft_alongside_sent_invoice(self):
        # A non-draft invoice on the job doesn't block creating a new draft
        Invoice.objects.create(job=self.approved_job, status=Invoice.STATUS_OPEN)
        draft = InvoiceWizardService.open_for_job(self.approved_job)
        self.assertEqual(draft.status, Invoice.STATUS_DRAFT)
        self.assertEqual(Invoice.objects.filter(job=self.approved_job).count(), 2)

    def test_refuses_draft_job(self):
        with self.assertRaises(ValidationError):
            InvoiceWizardService.open_for_job(self.draft_job)

    def test_allows_completed_job(self):
        invoice = InvoiceWizardService.open_for_job(self.completed_job)
        self.assertEqual(invoice.status, Invoice.STATUS_DRAFT)
        self.assertEqual(invoice.job, self.completed_job)

    def test_refuses_rejected_job(self):
        with self.assertRaises(ValidationError):
            InvoiceWizardService.open_for_job(self.rejected_job)


class GetSourcePoolTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')

        self.category = AccountingCategory.objects.create(name='Labor', is_active=True)
        self.contact = Contact.objects.create(
            first_name='Jane', last_name='Doe',
            email='jane@example.com', mobile_number='555-0000',
        )
        self.job = Job.objects.create(contact=self.contact, status=Job.STATUS_APPROVED, job_number='JOB-2026-0001')
        self.wo = WorkOrder.objects.create(job=self.job)

        self.task_billable = Task.objects.create(
            work_order=self.wo, name='Site demo',
            rate=Decimal('25.00'), accounting_category=self.category,
        )
        self.task_empty = Task.objects.create(
            work_order=self.wo, name='Inspection',
            rate=Decimal('50.00'), accounting_category=self.category,
        )
        self.task_cancelled = Task.objects.create(
            work_order=self.wo, name='Cancelled work',
            rate=Decimal('25.00'), accounting_category=self.category,
        )
        self.task_cancelled.status = Task.STATUS_CANCELLED
        self.task_cancelled.save()

        # Complete blep (billable)
        self.blep_complete = Blep.objects.create(
            task=self.task_billable,
            start_time=timezone.now() - timezone.timedelta(hours=2),
            end_time=timezone.now(),
        )
        # Incomplete blep (should be filtered out)
        self.blep_incomplete = Blep.objects.create(
            task=self.task_billable,
            start_time=timezone.now(),
            end_time=None,
        )

        self.pli = PriceListItem.objects.create(
            code='PLYWOOD', description='Plywood 4x8',
            selling_price=Decimal('25.00'),
            accounting_category=self.category,
        )
        self.material = Material.objects.create(
            task=self.task_billable,
            description='Plywood 4x8',
            quantity=Decimal('1.00'),
            sell_price=Decimal('25.00'),
            price_list_item=self.pli,
            accounting_category=self.category,
        )

        self.invoice = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)

    def test_tree_includes_work_orders_and_tasks(self):
        pool = InvoiceWizardService.get_source_pool(self.invoice)
        self.assertEqual(len(pool['work_orders']), 1)
        task_names = [t['name'] for t in pool['work_orders'][0]['tasks']]
        self.assertIn('Site demo', task_names)
        self.assertIn('Inspection', task_names)
        self.assertNotIn('Cancelled work', task_names)

    def test_incomplete_bleps_are_excluded(self):
        pool = InvoiceWizardService.get_source_pool(self.invoice)
        site_demo = next(
            t for t in pool['work_orders'][0]['tasks'] if t['name'] == 'Site demo'
        )
        blep_atoms = [a for a in site_demo['atoms'] if a['atom_type'] == 'blep']
        self.assertEqual(len(blep_atoms), 1)
        self.assertEqual(blep_atoms[0]['atom_id'], self.blep_complete.pk)

    def test_empty_task_has_flag_set(self):
        pool = InvoiceWizardService.get_source_pool(self.invoice)
        inspection = next(
            t for t in pool['work_orders'][0]['tasks'] if t['name'] == 'Inspection'
        )
        self.assertFalse(inspection['has_billable_atoms'])
        self.assertEqual(inspection['atoms'], [])

    def test_atom_state_available(self):
        pool = InvoiceWizardService.get_source_pool(self.invoice)
        site_demo = next(
            t for t in pool['work_orders'][0]['tasks'] if t['name'] == 'Site demo'
        )
        for atom in site_demo['atoms']:
            self.assertEqual(atom['state'], 'available')

    def test_atom_state_claimed_by_current(self):
        line_item = InvoiceLineItem.objects.create(
            invoice=self.invoice,
            description='Test',
            qty=Decimal('1'),
            price=Decimal('50.00'),
            accounting_category=self.category,
        )
        InvoiceLineItemSource.objects.create(
            invoice_line_item=line_item,
            source_type=InvoiceLineItemSource.SOURCE_BLEP,
            source_pk=self.blep_complete.pk,
        )
        pool = InvoiceWizardService.get_source_pool(self.invoice)
        site_demo = next(
            t for t in pool['work_orders'][0]['tasks'] if t['name'] == 'Site demo'
        )
        claimed = next(a for a in site_demo['atoms'] if a['atom_id'] == self.blep_complete.pk)
        self.assertEqual(claimed['state'], 'claimed_by_current')
        self.assertEqual(claimed['claiming_line_item_id'], line_item.pk)

    def test_atom_state_claimed_by_other_invoice(self):
        other_invoice = Invoice.objects.create(job=self.job, status=Invoice.STATUS_OPEN)
        other_li = InvoiceLineItem.objects.create(
            invoice=other_invoice,
            description='Prior',
            qty=Decimal('1'),
            price=Decimal('50.00'),
            accounting_category=self.category,
        )
        InvoiceLineItemSource.objects.create(
            invoice_line_item=other_li,
            source_type=InvoiceLineItemSource.SOURCE_BLEP,
            source_pk=self.blep_complete.pk,
        )
        pool = InvoiceWizardService.get_source_pool(self.invoice)
        site_demo = next(
            t for t in pool['work_orders'][0]['tasks'] if t['name'] == 'Site demo'
        )
        claimed = next(a for a in site_demo['atoms'] if a['atom_id'] == self.blep_complete.pk)
        self.assertEqual(claimed['state'], 'claimed_by_other')
        self.assertEqual(claimed['claiming_invoice_id'], other_invoice.pk)
        self.assertEqual(claimed['claiming_invoice_number'], other_invoice.invoice_number)

    def test_atoms_on_cancelled_invoice_are_available(self):
        other_invoice = Invoice.objects.create(job=self.job, status=Invoice.STATUS_CANCELLED)
        other_li = InvoiceLineItem.objects.create(
            invoice=other_invoice,
            description='Prior',
            qty=Decimal('1'),
            price=Decimal('50.00'),
            accounting_category=self.category,
        )
        InvoiceLineItemSource.objects.create(
            invoice_line_item=other_li,
            source_type=InvoiceLineItemSource.SOURCE_BLEP,
            source_pk=self.blep_complete.pk,
        )
        pool = InvoiceWizardService.get_source_pool(self.invoice)
        site_demo = next(
            t for t in pool['work_orders'][0]['tasks'] if t['name'] == 'Site demo'
        )
        claimed_blep = next(a for a in site_demo['atoms'] if a['atom_id'] == self.blep_complete.pk)
        self.assertEqual(claimed_blep['state'], 'available')

    def test_material_atoms_included(self):
        pool = InvoiceWizardService.get_source_pool(self.invoice)
        site_demo = next(
            t for t in pool['work_orders'][0]['tasks'] if t['name'] == 'Site demo'
        )
        materials = [a for a in site_demo['atoms'] if a['atom_type'] == 'material']
        self.assertEqual(len(materials), 1)
        self.assertEqual(materials[0]['atom_id'], self.material.pk)
        self.assertEqual(materials[0]['computed_amount'], Decimal('25.00'))


class AddAtomsToNewLineItemTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')

        self.cat_labor = AccountingCategory.objects.create(code='LBR', name='Labor', is_active=True)
        self.cat_materials = AccountingCategory.objects.create(code='MAT', name='Materials', is_active=True)
        self.contact = Contact.objects.create(
            first_name='Jane', last_name='Doe',
            email='jane@example.com', mobile_number='555-0000',
        )
        self.job = Job.objects.create(contact=self.contact, status=Job.STATUS_APPROVED, job_number='JOB-2026-0001')
        self.wo = WorkOrder.objects.create(job=self.job)
        self.task = Task.objects.create(
            work_order=self.wo, name='Labor',
            rate=Decimal('25.00'), accounting_category=self.cat_labor,
        )
        start = timezone.now() - timezone.timedelta(hours=2)
        self.blep1 = Blep.objects.create(
            task=self.task, start_time=start, end_time=start + timezone.timedelta(hours=2),
        )
        self.blep2 = Blep.objects.create(
            task=self.task,
            start_time=start + timezone.timedelta(hours=3),
            end_time=start + timezone.timedelta(hours=4),
        )
        self.pli = PriceListItem.objects.create(
            code='PLY', description='Plywood',
            selling_price=Decimal('25.00'),
            accounting_category=self.cat_materials,
        )
        self.material = Material.objects.create(
            task=self.task, description='Plywood',
            quantity=Decimal('1.00'), sell_price=Decimal('25.00'),
            price_list_item=self.pli, accounting_category=self.cat_materials,
        )
        self.invoice = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)

    def test_creates_line_item_and_sources(self):
        atoms = [
            {'type': 'blep', 'id': self.blep1.pk},
            {'type': 'blep', 'id': self.blep2.pk},
        ]
        line_item = InvoiceWizardService.add_atoms_to_new_line_item(self.invoice, atoms)
        self.assertEqual(line_item.sources.count(), 2)
        self.assertEqual(line_item.invoice, self.invoice)

    def test_default_price_is_sum_of_atoms(self):
        atoms = [
            {'type': 'blep', 'id': self.blep1.pk},  # 2h * $25 = $50
            {'type': 'blep', 'id': self.blep2.pk},  # 1h * $25 = $25
        ]
        line_item = InvoiceWizardService.add_atoms_to_new_line_item(self.invoice, atoms)
        self.assertEqual(line_item.price, Decimal('75.00'))

    def test_default_qty_and_units(self):
        atoms = [{'type': 'blep', 'id': self.blep1.pk}]
        line_item = InvoiceWizardService.add_atoms_to_new_line_item(self.invoice, atoms)
        self.assertEqual(line_item.qty, Decimal('1'))
        self.assertEqual(line_item.units, 'each')

    def test_default_description_is_blank(self):
        atoms = [{'type': 'blep', 'id': self.blep1.pk}]
        line_item = InvoiceWizardService.add_atoms_to_new_line_item(self.invoice, atoms)
        self.assertEqual(line_item.description, '')

    def test_category_set_when_all_atoms_share_one(self):
        atoms = [
            {'type': 'blep', 'id': self.blep1.pk},
            {'type': 'blep', 'id': self.blep2.pk},
        ]
        line_item = InvoiceWizardService.add_atoms_to_new_line_item(self.invoice, atoms)
        self.assertEqual(line_item.accounting_category, self.cat_labor)

    def test_category_null_when_atoms_mixed(self):
        atoms = [
            {'type': 'blep', 'id': self.blep1.pk},       # labor
            {'type': 'material', 'id': self.material.pk}, # materials
        ]
        line_item = InvoiceWizardService.add_atoms_to_new_line_item(self.invoice, atoms)
        self.assertIsNone(line_item.accounting_category)

    def test_concurrent_claim_raises_claim_conflict(self):
        # Pre-claim blep1 via another line item
        prior_li = InvoiceLineItem.objects.create(
            invoice=self.invoice,
            description='Prior',
            qty=Decimal('1'),
            price=Decimal('50.00'),
            accounting_category=self.cat_labor,
        )
        InvoiceLineItemSource.objects.create(
            invoice_line_item=prior_li,
            source_type=InvoiceLineItemSource.SOURCE_BLEP,
            source_pk=self.blep1.pk,
        )
        atoms = [{'type': 'blep', 'id': self.blep1.pk}]
        with self.assertRaises(ClaimConflict) as ctx:
            InvoiceWizardService.add_atoms_to_new_line_item(self.invoice, atoms)
        self.assertIn(
            {'type': 'blep', 'id': self.blep1.pk},
            ctx.exception.atom_ids,
        )

    def test_concurrent_claim_rolls_back_fully(self):
        # If any atom conflicts, the whole operation is rolled back -- no new line item.
        prior_li = InvoiceLineItem.objects.create(
            invoice=self.invoice,
            description='Prior',
            qty=Decimal('1'),
            price=Decimal('50.00'),
            accounting_category=self.cat_labor,
        )
        InvoiceLineItemSource.objects.create(
            invoice_line_item=prior_li,
            source_type=InvoiceLineItemSource.SOURCE_BLEP,
            source_pk=self.blep1.pk,
        )
        initial_count = InvoiceLineItem.objects.filter(invoice=self.invoice).count()
        atoms = [
            {'type': 'blep', 'id': self.blep1.pk},  # conflict
            {'type': 'blep', 'id': self.blep2.pk},  # would be fine
        ]
        try:
            InvoiceWizardService.add_atoms_to_new_line_item(self.invoice, atoms)
        except ClaimConflict:
            pass
        self.assertEqual(
            InvoiceLineItem.objects.filter(invoice=self.invoice).count(),
            initial_count,
        )

    def test_refuses_mutation_on_non_draft_invoice(self):
        # Need a line item to allow status change from draft
        InvoiceLineItem.objects.create(
            invoice=self.invoice, description='Filler',
            qty=Decimal('1'), price=Decimal('10.00'),
            accounting_category=self.cat_labor,
        )
        self.invoice.status = Invoice.STATUS_OPEN
        self.invoice.save()
        atoms = [{'type': 'blep', 'id': self.blep1.pk}]
        with self.assertRaises(ValidationError):
            InvoiceWizardService.add_atoms_to_new_line_item(self.invoice, atoms)


class AddAtomsToExistingLineItemTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')

        self.category = AccountingCategory.objects.create(name='Labor', is_active=True)
        self.contact = Contact.objects.create(
            first_name='Jane', last_name='Doe',
            email='jane@example.com', mobile_number='555-0000',
        )
        self.job = Job.objects.create(contact=self.contact, status=Job.STATUS_APPROVED, job_number='JOB-2026-0001')
        self.wo = WorkOrder.objects.create(job=self.job)
        self.task = Task.objects.create(
            work_order=self.wo, name='Labor',
            rate=Decimal('25.00'), accounting_category=self.category,
        )
        start = timezone.now() - timezone.timedelta(hours=4)
        self.blep1 = Blep.objects.create(
            task=self.task, start_time=start, end_time=start + timezone.timedelta(hours=2),
        )
        self.blep2 = Blep.objects.create(
            task=self.task,
            start_time=start + timezone.timedelta(hours=3),
            end_time=start + timezone.timedelta(hours=4),
        )
        self.invoice = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)

        # Start with one atom on the line item
        self.line_item = InvoiceWizardService.add_atoms_to_new_line_item(
            self.invoice,
            [{'type': 'blep', 'id': self.blep1.pk}],
        )
        # price is $50 at this point

    def test_appends_sources(self):
        InvoiceWizardService.add_atoms_to_line_item(
            self.line_item,
            [{'type': 'blep', 'id': self.blep2.pk}],
        )
        self.line_item.refresh_from_db()
        self.assertEqual(self.line_item.sources.count(), 2)

    def test_recomputes_price_when_in_sync(self):
        # Line item is in sync: price $50, single atom totaling $50
        InvoiceWizardService.add_atoms_to_line_item(
            self.line_item,
            [{'type': 'blep', 'id': self.blep2.pk}],  # another $25
        )
        self.line_item.refresh_from_db()
        self.assertEqual(self.line_item.price, Decimal('75.00'))

    def test_preserves_price_when_overridden(self):
        # Override the price
        self.line_item.price = Decimal('100.00')
        self.line_item.save()

        InvoiceWizardService.add_atoms_to_line_item(
            self.line_item,
            [{'type': 'blep', 'id': self.blep2.pk}],
        )
        self.line_item.refresh_from_db()
        # Price is unchanged (not $75, not $100 + $25, just $100)
        self.assertEqual(self.line_item.price, Decimal('100.00'))

    def test_refuses_mutation_on_non_draft_invoice(self):
        self.invoice.status = Invoice.STATUS_OPEN
        self.invoice.save()
        with self.assertRaises(ValidationError):
            InvoiceWizardService.add_atoms_to_line_item(
                self.line_item,
                [{'type': 'blep', 'id': self.blep2.pk}],
            )

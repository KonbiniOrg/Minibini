from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.invoicing.models import Invoice, InvoiceLineItem, InvoiceLineItemSource
from apps.invoicing.services import InvoiceService, InvoiceWizardService, ClaimConflict
from apps.jobs.models import Job, Task, Blep, RateScheme
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
        self.completed_job.status = Job.STATUS_IN_PROGRESS
        self.completed_job.save()
        self.completed_job.status = Job.STATUS_WORK_COMPLETE
        self.completed_job.save()
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

    def test_allows_in_progress_job(self):
        in_progress_job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0099',
        )
        in_progress_job.status = Job.STATUS_SUBMITTED
        in_progress_job.save()
        in_progress_job.status = Job.STATUS_APPROVED
        in_progress_job.save()
        in_progress_job.status = Job.STATUS_IN_PROGRESS
        in_progress_job.save()

        invoice = InvoiceWizardService.open_for_job(in_progress_job)
        self.assertEqual(invoice.status, Invoice.STATUS_DRAFT)


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

        self.scheme = RateScheme.objects.create(
            name='Hourly-gsp', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('25.00'), unit_label='hours',
            accounting_category=self.category,
        )

        self.task_billable = Task.objects.create(
            job=self.job, name='Site demo', rate_scheme=self.scheme,
        )

        self.task_empty = Task.objects.create(
            job=self.job, name='Inspection', rate_scheme=self.scheme,
        )

        self.task_cancelled = Task.objects.create(
            job=self.job, name='Cancelled work', rate_scheme=self.scheme,
        )
        self.task_cancelled.status = Task.STATUS_CANCELLED
        self.task_cancelled.save()

        # Complete blep (informational only post-A16; the task atom is the billable unit)
        self.blep_complete = Blep.objects.create(
            task=self.task_billable,
            start_time=timezone.now() - timezone.timedelta(hours=2),
            end_time=timezone.now(),
        )
        # Incomplete blep (filtered out of the read-only blep detail array)
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
            job=self.job,
            task=self.task_billable,
            description='Plywood 4x8',
            quantity=Decimal('1.00'),
            sell_price=Decimal('25.00'),
            price_list_item=self.pli,
            accounting_category=self.category,
        )

        self.invoice = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)

    def test_tree_includes_tasks(self):
        pool = InvoiceWizardService.get_source_pool(self.invoice)
        self.assertIn('tasks', pool)
        task_names = [t['name'] for t in pool['tasks']]
        self.assertIn('Site demo', task_names)
        self.assertIn('Inspection', task_names)
        self.assertNotIn('Cancelled work', task_names)

    def test_empty_task_has_flag_set(self):
        # Every Task has a rate_scheme, so every task always has at least the
        # per-task billable atom. The "empty task" concept no longer exists —
        # this test now verifies the inspection task surfaces its per-task atom.
        pool = InvoiceWizardService.get_source_pool(self.invoice)
        inspection = next(
            t for t in pool['tasks'] if t['name'] == 'Inspection'
        )
        self.assertTrue(inspection['has_billable_atoms'])
        self.assertEqual(len(inspection['atoms']), 1)
        self.assertEqual(inspection['atoms'][0]['type'], 'task')

    def test_atom_state_available(self):
        pool = InvoiceWizardService.get_source_pool(self.invoice)
        site_demo = next(
            t for t in pool['tasks'] if t['name'] == 'Site demo'
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
        # Claim the per-task atom for task_billable
        InvoiceLineItemSource.objects.create(
            invoice_line_item=line_item,
            source_type=InvoiceLineItemSource.SOURCE_TASK,
            source_pk=self.task_billable.pk,
        )
        pool = InvoiceWizardService.get_source_pool(self.invoice)
        site_demo = next(
            t for t in pool['tasks'] if t['name'] == 'Site demo'
        )
        claimed = next(
            a for a in site_demo['atoms']
            if a['type'] == 'task' and a['id'] == self.task_billable.pk
        )
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
            source_type=InvoiceLineItemSource.SOURCE_TASK,
            source_pk=self.task_billable.pk,
        )
        pool = InvoiceWizardService.get_source_pool(self.invoice)
        site_demo = next(
            t for t in pool['tasks'] if t['name'] == 'Site demo'
        )
        claimed = next(
            a for a in site_demo['atoms']
            if a['type'] == 'task' and a['id'] == self.task_billable.pk
        )
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
            source_type=InvoiceLineItemSource.SOURCE_TASK,
            source_pk=self.task_billable.pk,
        )
        pool = InvoiceWizardService.get_source_pool(self.invoice)
        site_demo = next(
            t for t in pool['tasks'] if t['name'] == 'Site demo'
        )
        claimed_atom = next(
            a for a in site_demo['atoms']
            if a['type'] == 'task' and a['id'] == self.task_billable.pk
        )
        self.assertEqual(claimed_atom['state'], 'available')

    def test_material_atoms_included(self):
        pool = InvoiceWizardService.get_source_pool(self.invoice)
        site_demo = next(
            t for t in pool['tasks'] if t['name'] == 'Site demo'
        )
        materials = [a for a in site_demo['atoms'] if a['type'] == 'material']
        self.assertEqual(len(materials), 1)
        self.assertEqual(materials[0]['id'], self.material.pk)
        self.assertEqual(materials[0]['amount'], Decimal('25.00'))


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
        self.scheme = RateScheme.objects.create(
            name='Hourly-aatn', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('25.00'), unit_label='hours',
            accounting_category=self.cat_labor,
        )
        self.task = Task.objects.create(
            job=self.job, name='Labor', rate_scheme=self.scheme,
        )
        start = timezone.now() - timezone.timedelta(hours=2)
        # Two bleps on self.task — task atom rolls up to 3h * $25 = $75
        self.blep1 = Blep.objects.create(
            task=self.task, start_time=start, end_time=start + timezone.timedelta(hours=2),
        )
        self.blep2 = Blep.objects.create(
            task=self.task,
            start_time=start + timezone.timedelta(hours=3),
            end_time=start + timezone.timedelta(hours=4),
        )
        # Second task with its own bleps — task atom rolls up to 1h * $25 = $25
        self.task2 = Task.objects.create(
            job=self.job, name='Cleanup', rate_scheme=self.scheme,
        )
        Blep.objects.create(
            task=self.task2,
            start_time=start + timezone.timedelta(hours=5),
            end_time=start + timezone.timedelta(hours=6),
        )
        self.pli = PriceListItem.objects.create(
            code='PLY', description='Plywood',
            selling_price=Decimal('25.00'),
            accounting_category=self.cat_materials,
        )
        self.material = Material.objects.create(
            job=self.job, task=self.task, description='Plywood',
            quantity=Decimal('1.00'), sell_price=Decimal('25.00'),
            price_list_item=self.pli, accounting_category=self.cat_materials,
        )
        self.invoice = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)

    def test_creates_line_item_and_sources(self):
        atoms = [
            {'type': 'task', 'id': self.task.pk},
            {'type': 'task', 'id': self.task2.pk},
        ]
        line_item = InvoiceWizardService.add_atoms_to_new_line_item(self.invoice, atoms)
        self.assertEqual(line_item.sources.count(), 2)
        self.assertEqual(line_item.invoice, self.invoice)

    def test_fallback_bundle_price_is_sum_of_atoms(self):
        # A non-uniform bundle (task + material) falls back: qty=1, price=sum.
        atoms = [
            {'type': 'task', 'id': self.task.pk},          # 3h * $25 = $75
            {'type': 'material', 'id': self.material.pk},  # $25
        ]
        line_item = InvoiceWizardService.add_atoms_to_new_line_item(self.invoice, atoms)
        self.assertEqual(line_item.qty, Decimal('1'))
        self.assertEqual(line_item.price, Decimal('100.00'))

    def test_single_task_atom_copy_over(self):
        # task1 has bleps totalling 3h at $25/hr.  Task atom: qty=1, price=total,
        # units track the scheme.
        atoms = [{'type': 'task', 'id': self.task.pk}]
        line_item = InvoiceWizardService.add_atoms_to_new_line_item(self.invoice, atoms)
        self.assertEqual(line_item.qty, Decimal('1'))
        self.assertEqual(line_item.price, Decimal('75.00'))
        self.assertEqual(line_item.units, 'hours')

    def test_single_material_atom_copy_over(self):
        # material has quantity=1.00, sell_price=25.00, linked to a PriceListItem
        # whose units default to 'none' -> qty=1, price=25, units='none'
        atoms = [{'type': 'material', 'id': self.material.pk}]
        line_item = InvoiceWizardService.add_atoms_to_new_line_item(self.invoice, atoms)
        self.assertEqual(line_item.qty, Decimal('1.00'))
        self.assertEqual(line_item.price, Decimal('25.00'))
        self.assertEqual(line_item.units, 'none')

    def test_single_material_atom_with_qty_3_copy_over(self):
        # Explicit non-1 quantity case
        mat3 = Material.objects.create(
            job=self.job, task=self.task, description='3-pack',
            quantity=Decimal('3.00'), sell_price=Decimal('5.00'),
            accounting_category=self.cat_materials,
        )
        atoms = [{'type': 'material', 'id': mat3.pk}]
        line_item = InvoiceWizardService.add_atoms_to_new_line_item(self.invoice, atoms)
        self.assertEqual(line_item.qty, Decimal('3.00'))
        self.assertEqual(line_item.price, Decimal('5.00'))

    def test_single_task_atom_units_pulled_from_scheme(self):
        atoms = [{'type': 'task', 'id': self.task.pk}]
        line_item = InvoiceWizardService.add_atoms_to_new_line_item(self.invoice, atoms)
        # Task atom: qty/price decomposition isn't generally clean across rate
        # algorithms, so qty stays at 1 and price=total. Units track the scheme.
        self.assertEqual(line_item.units, 'hours')
        self.assertEqual(line_item.qty, Decimal('1'))

    def test_multi_atom_line_qty_1_units_none(self):
        atoms = [
            {'type': 'task', 'id': self.task.pk},
            {'type': 'material', 'id': self.material.pk},
        ]
        line_item = InvoiceWizardService.add_atoms_to_new_line_item(self.invoice, atoms)
        self.assertEqual(line_item.qty, Decimal('1'))
        self.assertEqual(line_item.units, 'none')

    def test_default_description_pre_filled_for_single_atom(self):
        # Single task atom: description is pre-filled with the task's name
        atoms = [{'type': 'task', 'id': self.task.pk}]
        line_item = InvoiceWizardService.add_atoms_to_new_line_item(self.invoice, atoms)
        self.assertEqual(line_item.description, 'Labor')

    def test_category_set_when_all_atoms_share_one(self):
        atoms = [
            {'type': 'task', 'id': self.task.pk},
            {'type': 'task', 'id': self.task2.pk},
        ]
        line_item = InvoiceWizardService.add_atoms_to_new_line_item(self.invoice, atoms)
        self.assertEqual(line_item.accounting_category, self.cat_labor)

    def test_category_null_when_atoms_mixed(self):
        atoms = [
            {'type': 'task', 'id': self.task.pk},         # labor
            {'type': 'material', 'id': self.material.pk}, # materials
        ]
        line_item = InvoiceWizardService.add_atoms_to_new_line_item(self.invoice, atoms)
        self.assertIsNone(line_item.accounting_category)

    def test_concurrent_claim_raises_claim_conflict(self):
        # Pre-claim the task atom via another line item
        prior_li = InvoiceLineItem.objects.create(
            invoice=self.invoice,
            description='Prior',
            qty=Decimal('1'),
            price=Decimal('50.00'),
            accounting_category=self.cat_labor,
        )
        InvoiceLineItemSource.objects.create(
            invoice_line_item=prior_li,
            source_type=InvoiceLineItemSource.SOURCE_TASK,
            source_pk=self.task.pk,
        )
        atoms = [{'type': 'task', 'id': self.task.pk}]
        with self.assertRaises(ClaimConflict) as ctx:
            InvoiceWizardService.add_atoms_to_new_line_item(self.invoice, atoms)
        self.assertIn(
            {'type': 'task', 'id': self.task.pk},
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
            source_type=InvoiceLineItemSource.SOURCE_TASK,
            source_pk=self.task.pk,
        )
        initial_count = InvoiceLineItem.objects.filter(invoice=self.invoice).count()
        atoms = [
            {'type': 'task', 'id': self.task.pk},   # conflict
            {'type': 'task', 'id': self.task2.pk},  # would be fine
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
        atoms = [{'type': 'task', 'id': self.task.pk}]
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
        self.scheme = RateScheme.objects.create(
            name='Hourly-aate', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('25.00'), unit_label='hours',
            accounting_category=self.category,
        )
        # task1 with a 2h blep — task atom rolls up to $50
        self.task = Task.objects.create(
            job=self.job, name='Labor', rate_scheme=self.scheme,
        )
        start = timezone.now() - timezone.timedelta(hours=4)
        Blep.objects.create(
            task=self.task, start_time=start, end_time=start + timezone.timedelta(hours=2),
        )
        # task2 with a 1h blep — task atom rolls up to $25
        self.task2 = Task.objects.create(
            job=self.job, name='Cleanup', rate_scheme=self.scheme,
        )
        Blep.objects.create(
            task=self.task2,
            start_time=start + timezone.timedelta(hours=3),
            end_time=start + timezone.timedelta(hours=4),
        )
        self.invoice = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)

        # Start with one atom on the line item — task atom for task1.
        # Single-atom copy-over: qty=1, price=$50, units='hours'.
        self.line_item = InvoiceWizardService.add_atoms_to_new_line_item(
            self.invoice,
            [{'type': 'task', 'id': self.task.pk}],
        )

    def test_appends_sources(self):
        InvoiceWizardService.add_atoms_to_line_item(
            self.line_item,
            [{'type': 'task', 'id': self.task2.pk}],
        )
        self.line_item.refresh_from_db()
        self.assertEqual(self.line_item.sources.count(), 2)

    def test_add_makes_uniform_bundle_resummarized(self):
        # Line item starts as a single-atom task copy-over (qty=1, price=$50).
        # Adding task2 makes {task, task2} a uniform same-scheme bundle, so the
        # line item is re-summarized: qty = summed hours, price = scheme rate.
        InvoiceWizardService.add_atoms_to_line_item(
            self.line_item,
            [{'type': 'task', 'id': self.task2.pk}],
        )
        self.line_item.refresh_from_db()
        self.assertEqual(self.line_item.qty, Decimal('3'))
        self.assertEqual(self.line_item.price, Decimal('25.00'))
        self.assertEqual(self.line_item.units, 'hours')

    def test_preserves_price_when_overridden(self):
        # Override the price
        self.line_item.price = Decimal('100.00')
        self.line_item.save()

        InvoiceWizardService.add_atoms_to_line_item(
            self.line_item,
            [{'type': 'task', 'id': self.task2.pk}],
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
                [{'type': 'task', 'id': self.task2.pk}],
            )

    def test_add_to_in_sync_uniform_bundle_resummarizes_over_manual_qty(self):
        # A manually-set qty on an in-sync line item is replaced by the
        # re-summarization when the result is a uniform same-scheme bundle.
        self.line_item.qty = Decimal('2')
        self.line_item.price = Decimal('25.00')
        self.line_item.save()

        InvoiceWizardService.add_atoms_to_line_item(
            self.line_item,
            [{'type': 'task', 'id': self.task2.pk}],
        )
        self.line_item.refresh_from_db()
        self.assertEqual(self.line_item.qty, Decimal('3'))
        self.assertEqual(self.line_item.price, Decimal('25.00'))

    def test_preserves_price_when_overridden_with_qty_gt_1(self):
        # Set qty=2, price=$40 — overridden (qty*price=$80, sum=$50)
        self.line_item.qty = Decimal('2')
        self.line_item.price = Decimal('40.00')
        self.line_item.save()

        InvoiceWizardService.add_atoms_to_line_item(
            self.line_item,
            [{'type': 'task', 'id': self.task2.pk}],
        )
        self.line_item.refresh_from_db()
        self.assertEqual(self.line_item.price, Decimal('40.00'))


class RemoveAtomsFromLineItemTest(TestCase):
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
        self.scheme = RateScheme.objects.create(
            name='Hourly-rafl', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('25.00'), unit_label='hours',
            accounting_category=self.category,
        )
        # Three tasks, each with one blep, producing task atoms of $50/$25/$37.50
        start = timezone.now() - timezone.timedelta(hours=6)
        self.task1 = Task.objects.create(job=self.job, name='Labor 1', rate_scheme=self.scheme)
        Blep.objects.create(
            task=self.task1, start_time=start, end_time=start + timezone.timedelta(hours=2),
        )
        self.task2 = Task.objects.create(job=self.job, name='Labor 2', rate_scheme=self.scheme)
        Blep.objects.create(
            task=self.task2,
            start_time=start + timezone.timedelta(hours=3),
            end_time=start + timezone.timedelta(hours=4),
        )
        self.task3 = Task.objects.create(job=self.job, name='Labor 3', rate_scheme=self.scheme)
        Blep.objects.create(
            task=self.task3,
            start_time=start + timezone.timedelta(hours=4, minutes=30),
            end_time=start + timezone.timedelta(hours=6),
        )
        self.invoice = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)

        self.line_item = InvoiceWizardService.add_atoms_to_new_line_item(
            self.invoice,
            [
                {'type': 'task', 'id': self.task1.pk},  # $50
                {'type': 'task', 'id': self.task2.pk},  # $25
                {'type': 'task', 'id': self.task3.pk},  # $37.50
            ],
        )
        # price is $112.50 with 3 sources (qty=1, multi-atom default)

    def test_removes_partial_subset(self):
        source_ids = list(
            self.line_item.sources
            .filter(source_pk=self.task1.pk)
            .values_list('source_id', flat=True)
        )
        result = InvoiceWizardService.remove_atoms_from_line_item(
            self.line_item, source_ids,
        )
        self.line_item.refresh_from_db()
        self.assertEqual(self.line_item.sources.count(), 2)
        self.assertFalse(result['line_item_deleted'])

    def test_recomputes_price_when_in_sync(self):
        # 3-task uniform bundle, created summarized (qty=4.5h, price=$25).
        # Removing task1 (2h) leaves a uniform {task2, task3} bundle that is
        # re-summarized: qty = 1h + 1.5h = 2.5, price = scheme rate.
        source_ids = list(
            self.line_item.sources
            .filter(source_pk=self.task1.pk)  # remove the 2h atom
            .values_list('source_id', flat=True)
        )
        InvoiceWizardService.remove_atoms_from_line_item(self.line_item, source_ids)
        self.line_item.refresh_from_db()
        self.assertEqual(self.line_item.qty, Decimal('2.5'))
        self.assertEqual(self.line_item.price, Decimal('25.00'))

    def test_preserves_price_when_overridden(self):
        # Override the price
        self.line_item.price = Decimal('200.00')
        self.line_item.save()

        source_ids = list(
            self.line_item.sources
            .filter(source_pk=self.task1.pk)
            .values_list('source_id', flat=True)
        )
        InvoiceWizardService.remove_atoms_from_line_item(self.line_item, source_ids)
        self.line_item.refresh_from_db()
        self.assertEqual(self.line_item.price, Decimal('200.00'))

    def test_deletes_line_item_when_all_atoms_removed_in_sync(self):
        source_ids = list(
            self.line_item.sources.values_list('source_id', flat=True)
        )
        line_item_pk = self.line_item.pk
        result = InvoiceWizardService.remove_atoms_from_line_item(
            self.line_item, source_ids,
        )
        self.assertTrue(result['line_item_deleted'])
        self.assertFalse(
            InvoiceLineItem.objects.filter(pk=line_item_pk).exists()
        )

    def test_deletes_line_item_when_all_atoms_removed_even_if_overridden(self):
        self.line_item.price = Decimal('200.00')
        self.line_item.save()
        source_ids = list(
            self.line_item.sources.values_list('source_id', flat=True)
        )
        line_item_pk = self.line_item.pk
        result = InvoiceWizardService.remove_atoms_from_line_item(
            self.line_item, source_ids,
        )
        self.assertTrue(result['line_item_deleted'])
        self.assertFalse(
            InvoiceLineItem.objects.filter(pk=line_item_pk).exists()
        )

    def test_refuses_mutation_on_non_draft_invoice(self):
        self.invoice.status = Invoice.STATUS_OPEN
        self.invoice.save()
        source_ids = list(
            self.line_item.sources.values_list('source_id', flat=True)
        )[:1]
        with self.assertRaises(ValidationError):
            InvoiceWizardService.remove_atoms_from_line_item(
                self.line_item, source_ids,
            )

    def test_remove_from_in_sync_uniform_bundle_resummarizes(self):
        # Manual qty/price on an in-sync line item is replaced by
        # re-summarization when removal leaves a uniform same-scheme bundle.
        self.line_item.qty = Decimal('3')
        self.line_item.price = Decimal('37.50')
        self.line_item.save()

        source_ids = list(
            self.line_item.sources
            .filter(source_pk=self.task1.pk)  # remove the 2h atom
            .values_list('source_id', flat=True)
        )
        InvoiceWizardService.remove_atoms_from_line_item(self.line_item, source_ids)
        self.line_item.refresh_from_db()
        self.assertEqual(self.line_item.qty, Decimal('2.5'))
        self.assertEqual(self.line_item.price, Decimal('25.00'))

    def test_preserves_price_when_overridden_with_qty_gt_1(self):
        # qty=2, price=$100 (overridden — qty*price=$200, sum=$112.50)
        self.line_item.qty = Decimal('2')
        self.line_item.price = Decimal('100.00')
        self.line_item.save()

        source_ids = list(
            self.line_item.sources
            .filter(source_pk=self.task1.pk)
            .values_list('source_id', flat=True)
        )
        InvoiceWizardService.remove_atoms_from_line_item(self.line_item, source_ids)
        self.line_item.refresh_from_db()
        self.assertEqual(self.line_item.price, Decimal('100.00'))

    def test_renumbers_siblings_when_auto_delete_fires(self):
        """When all atoms are removed and the line item auto-deletes, the
        remaining siblings must be renumbered to close the gap."""
        # self.line_item is line 1 (from setUp). Add two more line items, each
        # backed by a fresh task atom.
        start = timezone.now() - timezone.timedelta(hours=12)
        task4 = Task.objects.create(job=self.job, name='Labor 4', rate_scheme=self.scheme)
        Blep.objects.create(
            task=task4, start_time=start, end_time=start + timezone.timedelta(hours=1),
        )
        task5 = Task.objects.create(job=self.job, name='Labor 5', rate_scheme=self.scheme)
        Blep.objects.create(
            task=task5,
            start_time=start + timezone.timedelta(hours=2),
            end_time=start + timezone.timedelta(hours=3),
        )
        li2 = InvoiceWizardService.add_atoms_to_new_line_item(
            self.invoice, [{'type': 'task', 'id': task4.pk}],
        )
        li3 = InvoiceWizardService.add_atoms_to_new_line_item(
            self.invoice, [{'type': 'task', 'id': task5.pk}],
        )
        self.assertEqual(self.line_item.line_number, 1)
        self.assertEqual(li2.line_number, 2)
        self.assertEqual(li3.line_number, 3)

        # Remove all atoms from line 1 → auto-delete fires
        all_ids = list(self.line_item.sources.values_list('source_id', flat=True))
        result = InvoiceWizardService.remove_atoms_from_line_item(
            self.line_item, all_ids,
        )
        self.assertTrue(result['line_item_deleted'])

        li2.refresh_from_db()
        li3.refresh_from_db()
        self.assertEqual(li2.line_number, 1)
        self.assertEqual(li3.line_number, 2)


class DiscardDraftTest(TestCase):
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
        self.scheme = RateScheme.objects.create(
            name='Hourly-dd', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('25.00'), unit_label='hours',
            accounting_category=self.category,
        )
        self.task = Task.objects.create(
            job=self.job, name='Labor', rate_scheme=self.scheme,
        )
        start = timezone.now() - timezone.timedelta(hours=2)
        self.blep = Blep.objects.create(
            task=self.task, start_time=start, end_time=start + timezone.timedelta(hours=2),
        )
        self.invoice = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)
        # Claim the per-task atom directly (atom helper migration is A17)
        self.line_item = InvoiceLineItem.objects.create(
            invoice=self.invoice, description='Labor',
            qty=Decimal('1'), price=Decimal('50.00'),
            accounting_category=self.category,
        )
        InvoiceLineItemSource.objects.create(
            invoice_line_item=self.line_item,
            source_type=InvoiceLineItemSource.SOURCE_TASK,
            source_pk=self.task.pk,
        )

    def test_deletes_draft_invoice(self):
        invoice_pk = self.invoice.pk
        InvoiceService.discard_draft(self.invoice)
        self.assertFalse(Invoice.objects.filter(pk=invoice_pk).exists())

    def test_cascades_to_line_items_and_sources(self):
        line_item_pk = self.line_item.pk
        InvoiceService.discard_draft(self.invoice)
        self.assertFalse(InvoiceLineItem.objects.filter(pk=line_item_pk).exists())
        self.assertFalse(
            InvoiceLineItemSource.objects.filter(invoice_line_item_id=line_item_pk).exists()
        )

    def test_atoms_become_available_again(self):
        # Sanity: while the draft exists, the per-task atom is claimed.
        pool_before = InvoiceWizardService.get_source_pool(self.invoice)
        labor_before = next(t for t in pool_before['tasks'] if t['name'] == 'Labor')
        atom_before = next(
            a for a in labor_before['atoms']
            if a['type'] == 'task' and a['id'] == self.task.pk
        )
        self.assertEqual(atom_before['state'], 'claimed_by_current')

        InvoiceService.discard_draft(self.invoice)
        # Create a fresh draft and check the source pool
        fresh_invoice = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)
        pool = InvoiceWizardService.get_source_pool(fresh_invoice)
        labor_task = next(t for t in pool['tasks'] if t['name'] == 'Labor')
        task_atom = next(
            a for a in labor_task['atoms']
            if a['type'] == 'task' and a['id'] == self.task.pk
        )
        self.assertEqual(task_atom['state'], 'available')

    def test_refuses_non_draft_invoice(self):
        self.invoice.status = Invoice.STATUS_OPEN
        self.invoice.save()
        with self.assertRaises(ValidationError):
            InvoiceService.discard_draft(self.invoice)


class SourcePoolLooseMaterialsTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        self.contact = Contact.objects.create(
            first_name='Jane', last_name='Doe',
            email='jane@example.com', mobile_number='555-0000',
        )

    def test_taskless_materials_group_appears_with_quantity_filter(self):
        from decimal import Decimal
        from apps.core.models import AccountingCategory, User
        from apps.jobs.models import Job
        from apps.invoicing.models import Invoice
        from apps.invoicing.services import InvoiceWizardService
        from apps.inventory.models import PriceListItem
        from apps.inventory.services import MaterialService
        from apps.expenses.models import Expense
        cat = AccountingCategory.objects.create(name='c', code='IWL1')
        pli = PriceListItem.objects.create(
            code='I-IWL', accounting_category=cat, is_inventoried=True,
            qty_on_hand=Decimal('10'),
        )
        job = Job.objects.create(contact=self.contact, job_number='JOB-IW-1')
        m1 = MaterialService.create_on_job(
            job=job, task=None, description='m1',
            quantity=Decimal('3'), sell_price=Decimal('2'),
            price_list_item=pli,
        )
        m2 = MaterialService.create_on_job(
            job=job, task=None, description='fully restocked',
            quantity=Decimal('2'), sell_price=Decimal('2'),
            price_list_item=pli,
        )
        user = User.objects.create(username='iwl_user')
        Expense.objects.create(
            entered_by=user, purchased_by=user, amount=Decimal('4'),
            purchased_on='2026-04-14',
            accounting_category=cat,
            payment_method=Expense.PAYMENT_METHOD_PERSONAL,
            material=m2,
        )
        MaterialService.restock(m2, Decimal('2'))
        inv = Invoice.objects.create(job=job, status=Invoice.STATUS_DRAFT)
        pool = InvoiceWizardService.get_source_pool(inv)

        loose = [g for g in pool['tasks'] if g['task_id'] is None]
        self.assertEqual(len(loose), 1)
        atoms = loose[0]['atoms']
        self.assertEqual([a['id'] for a in atoms], [m1.pk])
        self.assertEqual(atoms[0]['amount'], Decimal('6.00'))

    def test_partial_restock_bills_reduced_quantity(self):
        from decimal import Decimal
        from apps.core.models import AccountingCategory
        from apps.jobs.models import Job
        from apps.invoicing.services import InvoiceWizardService
        from apps.inventory.models import PriceListItem
        from apps.inventory.services import MaterialService
        cat = AccountingCategory.objects.create(name='c', code='IWL2')
        pli = PriceListItem.objects.create(
            code='I-IWL2', accounting_category=cat, is_inventoried=True,
            qty_on_hand=Decimal('10'),
        )
        job = Job.objects.create(contact=self.contact, job_number='JOB-IW-2')
        m = MaterialService.create_on_job(
            job=job, task=None, description='m',
            quantity=Decimal('5'), sell_price=Decimal('2'),
            price_list_item=pli,
        )
        MaterialService.restock(m, Decimal('2'))
        amount = InvoiceWizardService._atom_computed_amount(m)
        self.assertEqual(amount, Decimal('6.00'))


class TaskAttachedPartialRestockTest(TestCase):
    """Gap 12: task-attached material with partial restock shows reduced quantity in source pool."""

    def setUp(self):
        from apps.core.models import Configuration
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        self.cat = AccountingCategory.objects.create(name='tapr', code='TAPR1')
        self.contact = Contact.objects.create(
            first_name='TP', last_name='R',
            email='tpr@test.com',
        )

    def test_partial_restock_task_attached_bills_reduced_quantity(self):
        from apps.invoicing.services import InvoiceWizardService
        from apps.inventory.services import MaterialService
        job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_APPROVED,
            job_number='JOB-TAPR-1',
        )
        scheme = RateScheme.objects.create(
            name='Hourly-tapr', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('25.00'), unit_label='hours',
            accounting_category=self.cat,
        )
        task = Task.objects.create(job=job, name='work', rate_scheme=scheme)
        pli = PriceListItem.objects.create(
            code='I-TAPR', accounting_category=self.cat,
            is_inventoried=True, selling_price=Decimal('3.00'),
            qty_on_hand=Decimal('20'),
        )
        # qty=5, sell=2 per unit; restock 2 → quantity=3, amount=3*2=6
        m = MaterialService.create_on_job(
            job=job, task=task, description='bolts',
            quantity=Decimal('5'), sell_price=Decimal('2.00'),
            price_list_item=pli,
        )
        MaterialService.restock(m, Decimal('2'))
        invoice = Invoice.objects.create(job=job, status=Invoice.STATUS_DRAFT)
        pool = InvoiceWizardService.get_source_pool(invoice)
        # Find the task group
        task_group = next((g for g in pool['tasks'] if g['task_id'] == task.pk), None)
        self.assertIsNotNone(task_group, 'Task should appear in source pool')
        mat_atoms = [a for a in task_group['atoms'] if a['type'] == 'material']
        self.assertEqual(len(mat_atoms), 1)
        self.assertEqual(
            mat_atoms[0]['amount'], Decimal('6.00'),
            'computed_amount should be quantity(3) * sell_price(2) = 6.00',
        )


class AddAtomsToNewLineItemDescriptionTest(TestCase):
    """Description is pre-filled from the source atom when exactly one atom is added."""

    def setUp(self):
        super().setUp()
        from django.utils import timezone

        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')

        self.cat = AccountingCategory.objects.create(code='ID', name='ID')
        self.scheme = RateScheme.objects.create(
            name='Hourly-id', algorithm='elapsed_time', rate=Decimal('60'),
            unit_label='hour', accounting_category=self.cat,
        )
        contact = Contact.objects.create(
            first_name='F', last_name='L', email='f-id@l.test',
            mobile_number='555-2',
        )
        self.job = Job.objects.create(job_number='J-id', contact=contact)
        self.invoice = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)
        self.task = Task.objects.create(
            job=self.job, name='Setup', rate_scheme=self.scheme,
        )
        now = timezone.now()
        self.blep = Blep.objects.create(
            task=self.task,
            start_time=now - timezone.timedelta(hours=1),
            end_time=now,
        )
        self.material = Material.objects.create(
            job=self.job, description='Acrylic 1/4"',
            quantity=Decimal('1'), unit_cost=Decimal('20'),
            sell_price=Decimal('40'), accounting_category=self.cat,
        )

    def test_single_task_atom_seeds_description_from_name(self):
        atoms = [{'type': 'task', 'id': self.task.pk}]
        li = InvoiceWizardService.add_atoms_to_new_line_item(self.invoice, atoms)
        self.assertEqual(li.description, 'Setup')

    def test_single_material_atom_seeds_description(self):
        atoms = [{'type': 'material', 'id': self.material.pk}]
        li = InvoiceWizardService.add_atoms_to_new_line_item(self.invoice, atoms)
        self.assertEqual(li.description, 'Acrylic 1/4"')

    def test_multiple_atoms_leaves_description_blank(self):
        atoms = [
            {'type': 'task', 'id': self.task.pk},
            {'type': 'material', 'id': self.material.pk},
        ]
        li = InvoiceWizardService.add_atoms_to_new_line_item(self.invoice, atoms)
        self.assertEqual(li.description, '')

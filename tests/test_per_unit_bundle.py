from datetime import timedelta
from decimal import Decimal

from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, Configuration, AppState
from apps.estimates.models import Estimate, EstimateLineItem
from apps.estimates.services import EstimateWizardService
from apps.inventory.models import Material
from apps.invoicing.models import Invoice
from apps.invoicing.services import InvoiceWizardService
from apps.jobs.models import Job, RateScheme, Task


class PerUnitBundleTest(TestCase):
    """Per-unit-lines spec Task 3: `add_atoms_to_new_line_item(..., per_unit=True)`
    snapshots each atom's CURRENT per-unit values onto its claim row, then
    stamps the atom itself to the whole-job total for the override qty —
    atoms always store totals; the per-unit agreement lives only on the
    claim rows (spec §2).
    """

    def setUp(self):
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.update_or_create(
            key='job_number_sequence', defaults={'value': 'JOB-{year}-{counter:04d}'})
        AppState.objects.update_or_create(key='job_counter', defaults={'value': '0'})
        self.cat = AccountingCategory.objects.create(name='Labor', is_active=True)
        self.contact = Contact.objects.create(
            first_name='Jane', last_name='Doe',
            email='j@example.com', mobile_number='555-0001',
        )
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0001')
        self.estimate = Estimate.objects.create(
            job=self.job, status=Estimate.STATUS_DRAFT, estimate_number='EST-2026-0001')
        self.scheme = RateScheme.objects.create(
            name='Hourly', algorithm=RateScheme.ELAPSED_TIME, rate=Decimal('60'),
            unit_label='hour', accounting_category=self.cat,
        )

    def _task(self, est_qty=None, est_worker_time=None):
        t = Task(job=self.job, name='Setup')
        t.stamp_from_scheme(self.scheme)
        t.est_qty = est_qty
        t.est_worker_time = est_worker_time
        t.save()
        return t

    def _material(self, quantity):
        return Material.objects.create(
            job=self.job, description='Steel', quantity=quantity,
            sell_price=Decimal('2.50'), accounting_category=self.cat,
        )

    def test_per_unit_bundle_stamps_task_and_material(self):
        task = self._task(est_qty=Decimal('0.75'), est_worker_time=timedelta(minutes=45))
        material = self._material(Decimal('4'))
        atoms = [
            {'type': 'task', 'id': task.pk},
            {'type': 'material', 'id': material.pk},
        ]
        overrides = {
            'description': 'Per unit bundle', 'qty': Decimal('10'),
            'units': 'each', 'price': Decimal('55.00'),
        }
        li = EstimateWizardService.add_atoms_to_new_line_item(
            self.estimate, atoms, overrides=overrides, per_unit=True)

        self.assertTrue(li.per_unit)
        self.assertEqual(li.qty, Decimal('10'))
        self.assertEqual(li.price, Decimal('55.00'))

        task.refresh_from_db()
        material.refresh_from_db()
        self.assertEqual(task.est_qty, Decimal('7.50'))
        self.assertEqual(task.est_worker_time, timedelta(hours=7, minutes=30))
        self.assertEqual(material.quantity, Decimal('40.00'))

        task_src = li.sources.get(source_type='task', source_pk=task.pk)
        material_src = li.sources.get(source_type='material', source_pk=material.pk)
        self.assertEqual(task_src.per_unit_qty, Decimal('0.75'))
        self.assertEqual(task_src.per_unit_worker_time, timedelta(minutes=45))
        self.assertEqual(material_src.per_unit_qty, Decimal('4.00'))

    def test_per_unit_bundle_without_worker_time_leaves_null(self):
        task = self._task(est_qty=Decimal('1'), est_worker_time=None)
        atoms = [{'type': 'task', 'id': task.pk}]
        overrides = {
            'description': 'No worker time', 'qty': Decimal('5'),
            'units': 'each', 'price': Decimal('10.00'),
        }
        li = EstimateWizardService.add_atoms_to_new_line_item(
            self.estimate, atoms, overrides=overrides, per_unit=True)

        task.refresh_from_db()
        self.assertIsNone(task.est_worker_time)
        src = li.sources.get(source_type='task', source_pk=task.pk)
        self.assertIsNone(src.per_unit_worker_time)

    def test_per_unit_bundle_atom_supplied_worker_time(self):
        task = self._task(est_qty=Decimal('1'), est_worker_time=None)
        atoms = [{'type': 'task', 'id': task.pk, 'per_unit_worker_time': 'PT20M'}]
        overrides = {
            'description': 'Atom-supplied worker time', 'qty': Decimal('10'),
            'units': 'each', 'price': Decimal('10.00'),
        }
        li = EstimateWizardService.add_atoms_to_new_line_item(
            self.estimate, atoms, overrides=overrides, per_unit=True)

        task.refresh_from_db()
        self.assertEqual(task.est_worker_time, timedelta(hours=3, minutes=20))
        src = li.sources.get(source_type='task', source_pk=task.pk)
        self.assertEqual(src.per_unit_worker_time, timedelta(minutes=20))

    def test_per_unit_bundle_requires_qty(self):
        task = self._task(est_qty=Decimal('1'), est_worker_time=None)
        atoms = [{'type': 'task', 'id': task.pk}]

        with self.assertRaises(Exception) as ctx:
            EstimateWizardService.add_atoms_to_new_line_item(
                self.estimate, atoms, overrides={'price': Decimal('10.00')}, per_unit=True)
        exc = ctx.exception
        self.assertTrue(hasattr(exc, 'message_dict') or hasattr(exc, 'error_dict'))
        message_dict = exc.message_dict
        self.assertIn('qty', message_dict)
        self.assertEqual(
            message_dict['qty'], ['A quantity is required for per-unit lines.'])

    def test_invoice_wizard_rejects_per_unit(self):
        from apps.core.models import User
        user = User.objects.create_user(username='per_unit_invoice_user')
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{counter:04d}')
        AppState.objects.update_or_create(key='invoice_counter', defaults={'value': '0'})
        job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_APPROVED, job_number='JOB-INV-1')
        invoice = Invoice.objects.create(job=job, status=Invoice.STATUS_DRAFT)
        scheme = RateScheme.objects.create(
            name='Inv-Hourly', algorithm=RateScheme.ELAPSED_TIME, rate=Decimal('60'),
            unit_label='hour', accounting_category=self.cat,
        )
        task = Task(job=job, name='Billable')
        task.stamp_from_scheme(scheme)
        task.save()
        task.status = Task.STATUS_COMPLETE
        task.save()
        atoms = [{'type': 'task', 'id': task.pk}]

        with self.assertRaises(Exception) as ctx:
            InvoiceWizardService.add_atoms_to_new_line_item(
                invoice, atoms, overrides={'qty': Decimal('1'), 'price': Decimal('60.00')},
                per_unit=True)
        self.assertIn(
            'This document does not support per-unit lines.', str(ctx.exception))

    def test_per_unit_bundle_requires_description(self):
        task = self._task(est_qty=Decimal('1'), est_worker_time=None)
        atoms = [{'type': 'task', 'id': task.pk}]

        with self.assertRaises(Exception) as ctx:
            EstimateWizardService.add_atoms_to_new_line_item(
                self.estimate, atoms,
                overrides={'qty': Decimal('5'), 'units': 'each', 'price': Decimal('10.00')},
                per_unit=True)
        message_dict = ctx.exception.message_dict
        self.assertIn('description', message_dict)

    def test_per_unit_bundle_requires_units_and_price(self):
        # The modal always sends all four fields (WYSIWYG) — description/qty
        # present, units/price missing must both surface, field-shaped.
        task = self._task(est_qty=Decimal('1'), est_worker_time=None)
        atoms = [{'type': 'task', 'id': task.pk}]

        with self.assertRaises(Exception) as ctx:
            EstimateWizardService.add_atoms_to_new_line_item(
                self.estimate, atoms,
                overrides={'description': 'Setup x10', 'qty': Decimal('5')},
                per_unit=True)
        message_dict = ctx.exception.message_dict
        self.assertIn('units', message_dict)
        self.assertIn('price', message_dict)

    def test_append_to_per_unit_line_rejected(self):
        # Task 3/4 plan-gap ruling: an appended claim gets no per_unit_qty
        # snapshot (only the per_unit path of add_atoms_to_new_line_item
        # stamps one), so it would silently contribute $0 to the line's
        # per-unit sum. Appending must be rejected outright until the
        # modal-restructure phase adds real append semantics (spec §10).
        task = self._task(est_qty=Decimal('0.75'), est_worker_time=timedelta(minutes=45))
        task2 = self._task(est_qty=Decimal('1'), est_worker_time=None)
        overrides = {
            'description': 'Per unit bundle', 'qty': Decimal('10'),
            'units': 'each', 'price': Decimal('55.00'),
        }
        li = EstimateWizardService.add_atoms_to_new_line_item(
            self.estimate, [{'type': 'task', 'id': task.pk}],
            overrides=overrides, per_unit=True)

        with self.assertRaises(Exception) as ctx:
            EstimateWizardService.add_atoms_to_line_item(
                li, [{'type': 'task', 'id': task2.pk}])
        self.assertIn(
            'Tasks and materials cannot be added to a per-unit line yet.',
            str(ctx.exception),
        )
        self.assertEqual(li.sources.count(), 1)

    def test_whole_line_bundle_unchanged(self):
        # Regression: a non-per-unit bundle call stamps nothing on the atoms
        # and leaves the claim rows' per_unit_qty/per_unit_worker_time null.
        task = self._task(est_qty=Decimal('0.75'), est_worker_time=timedelta(minutes=45))
        material = self._material(Decimal('4'))
        atoms = [
            {'type': 'task', 'id': task.pk},
            {'type': 'material', 'id': material.pk},
        ]
        li = EstimateWizardService.add_atoms_to_new_line_item(self.estimate, atoms)

        self.assertFalse(li.per_unit)
        task.refresh_from_db()
        material.refresh_from_db()
        self.assertEqual(task.est_qty, Decimal('0.75'))
        self.assertEqual(task.est_worker_time, timedelta(minutes=45))
        self.assertEqual(material.quantity, Decimal('4'))

        task_src = li.sources.get(source_type='task', source_pk=task.pk)
        material_src = li.sources.get(source_type='material', source_pk=material.pk)
        self.assertIsNone(task_src.per_unit_qty)
        self.assertIsNone(task_src.per_unit_worker_time)
        self.assertIsNone(material_src.per_unit_qty)

    # Final-review Finding 2: a task with est_qty=None (legal — e.g. a
    # checklist-plan task that hasn't been quantified yet) must never reach
    # `_stamp_atom_per_unit`'s per_unit_qty = instance.est_qty line and mint
    # a NULL-snapshot claim — that claim would be permanently invisible to
    # `_sum_per_unit_sources`, drift, and Revert. Mint already rejects this
    # ('A per-unit quantity is required for this line.'); the bundle path
    # must reject it too, before anything is created.

    def test_per_unit_bundle_est_qty_none_task_rejected(self):
        task = self._task(est_qty=None, est_worker_time=None)
        atoms = [{'type': 'task', 'id': task.pk}]
        overrides = {
            'description': 'Unquantified', 'qty': Decimal('5'),
            'units': 'each', 'price': Decimal('10.00'),
        }
        with self.assertRaises(Exception) as ctx:
            EstimateWizardService.add_atoms_to_new_line_item(
                self.estimate, atoms, overrides=overrides, per_unit=True)
        self.assertIn(
            '"Setup" has no estimated quantity', str(ctx.exception))

        # Atomicity: nothing was created — no line item, no stamp on the
        # task, no claim row.
        self.assertEqual(EstimateLineItem.objects.filter(estimate=self.estimate).count(), 0)
        task.refresh_from_db()
        self.assertIsNone(task.est_qty)

    def test_per_unit_bundle_est_qty_none_task_rejected_direct_service_call(self):
        """Direct service-level pin on _stamp_atom_per_unit itself, not just
        the add_atoms_to_new_line_item wrapper."""
        task = self._task(est_qty=None, est_worker_time=None)
        with self.assertRaises(Exception) as ctx:
            EstimateWizardService._stamp_atom_per_unit(task, {}, Decimal('5'))
        self.assertIn(
            '"Setup" has no estimated quantity', str(ctx.exception))

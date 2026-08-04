"""
TDD tests for task-owned-money Phase 3 Task 3: invoice compose stamps the
configured fallback accounting category onto a line whenever the source
atoms' shared category resolves to null because a contributing atom (a
task with no AC of its own) has none. Atoms themselves are never touched
— only the created/copied LINE gets the stamp, which is why re-releasing
and re-adding an atom re-triggers the stamp (the atom's own AC stays null).

Covers:
- BaseWizardService.add_atoms_to_new_line_item (InvoiceWizardService):
  single null-AC atom, all-null bundle, mixed null+real bundle, untouched
  real-AC atoms (fee/material), the no-fallback-configured error, and the
  unrelated "two different real categories" case staying None (unchanged
  pre-existing behavior — no null atom involved, no fallback consulted).
- InvoiceService.copy_from_estimate: same stamping, same no-fallback error.
- InvoiceLineItemSerializer.used_fallback_ac.
- Release (delete the line) + re-add regenerates the stamp/flag.
- EstimateWizardService (BaseWizardService, no override): compose stays
  unstamped even with a fallback configured — Phase 3 is invoice-only.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, AppState, Configuration, User
from apps.estimates.models import Estimate, EstimateLineItem
from apps.estimates.services import EstimateWizardService
from apps.inventory.models import Material
from apps.invoicing.models import Invoice, InvoiceLineItem
from apps.invoicing.services import InvoiceService, InvoiceWizardService
from apps.jobs.models import Fee, Job, RateScheme, Task
from apps.api.invoicing.serializers import InvoiceLineItemSerializer


def _seq_config():
    Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
    AppState.objects.create(key='invoice_counter', value='0')
    Configuration.objects.update_or_create(key='job_number_sequence', defaults={'value': 'JOB-{year}-{counter:04d}'})
    AppState.objects.update_or_create(key='job_counter', defaults={'value': '0'})


class FallbackStampingBaseSetup(TestCase):
    """Shared fixture: a job with a real-AC scheme, a fallback AC configured,
    and helpers to mint null-AC tasks."""

    def setUp(self):
        _seq_config()
        self.cat_labor = AccountingCategory.objects.create(code='LBR-FB', name='Labor')
        self.cat_materials = AccountingCategory.objects.create(code='MAT-FB', name='Materials')
        self.fallback_cat = AccountingCategory.objects.create(
            code='UNC-FB', name='Uncategorized income',
        )
        Configuration.objects.create(
            key='fallback_accounting_category', value=str(self.fallback_cat.pk),
        )
        self.contact = Contact.objects.create(
            first_name='Jane', last_name='Doe',
            email='jane-fb@example.com', mobile_number='555-0000',
        )
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_APPROVED, job_number='JOB-FB-0001',
        )
        self.scheme = RateScheme.objects.create(
            name='Hourly-fb', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('25.00'), unit_label='hour',
            accounting_category=self.cat_labor,
        )
        self.invoice = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)

    def _make_task(self, name, accounting_category, qty=Decimal('2.00')):
        """A COMPLETE, ENTERED_QTY task — no bleps required — with the
        given AC (possibly None)."""
        task = Task(
            job=self.job, name=name,
            qty_source=Task.QTY_ENTERED, rate=Decimal('25.00'),
            unit_label='hour', actual_qty=qty,
            accounting_category=accounting_category,
        )
        task.save()
        task.status = Task.STATUS_COMPLETE
        task.save()
        return task


class AddAtomsToNewLineItemFallbackTest(FallbackStampingBaseSetup):
    def test_single_null_ac_task_stamps_fallback(self):
        task = self._make_task('Flat work', None)
        line_item = InvoiceWizardService.add_atoms_to_new_line_item(
            self.invoice, [{'type': 'task', 'id': task.pk}],
        )
        self.assertEqual(line_item.accounting_category_id, self.fallback_cat.pk)
        data = InvoiceLineItemSerializer(line_item).data
        self.assertTrue(data['used_fallback_ac'])

    def test_real_ac_task_untouched(self):
        task = self._make_task('Real AC work', self.cat_labor)
        line_item = InvoiceWizardService.add_atoms_to_new_line_item(
            self.invoice, [{'type': 'task', 'id': task.pk}],
        )
        self.assertEqual(line_item.accounting_category_id, self.cat_labor.pk)
        data = InvoiceLineItemSerializer(line_item).data
        self.assertFalse(data['used_fallback_ac'])

    def test_fee_with_ac_untouched(self):
        # Fee.accounting_category is a required (non-nullable) FK, so a fee
        # atom is never a source of null AC — verify it never gets stamped.
        fee = Fee.objects.create(
            job=self.job, description='Rush fee',
            quantity=Decimal('1'), unit_rate=Decimal('50.00'),
            accounting_category=self.cat_labor,
        )
        line_item = InvoiceWizardService.add_atoms_to_new_line_item(
            self.invoice, [{'type': 'fee', 'id': fee.pk}],
        )
        self.assertEqual(line_item.accounting_category_id, self.cat_labor.pk)
        data = InvoiceLineItemSerializer(line_item).data
        self.assertFalse(data['used_fallback_ac'])

    def test_material_untouched(self):
        # Material.accounting_category is required (non-nullable) too.
        material = Material.objects.create(
            job=self.job, description='Plywood',
            quantity=Decimal('1.00'), sell_price=Decimal('25.00'),
            accounting_category=self.cat_materials,
        )
        material.consumption_state = Material.CONSUMPTION_STATE_CONSUMED
        material.save(update_fields=['consumption_state'])
        line_item = InvoiceWizardService.add_atoms_to_new_line_item(
            self.invoice, [{'type': 'material', 'id': material.pk}],
        )
        self.assertEqual(line_item.accounting_category_id, self.cat_materials.pk)
        data = InvoiceLineItemSerializer(line_item).data
        self.assertFalse(data['used_fallback_ac'])

    def test_bundle_all_null_stamps_fallback(self):
        t1 = self._make_task('Flat 1', None)
        t2 = self._make_task('Flat 2', None)
        line_item = InvoiceWizardService.add_atoms_to_new_line_item(
            self.invoice,
            [{'type': 'task', 'id': t1.pk}, {'type': 'task', 'id': t2.pk}],
        )
        self.assertEqual(line_item.accounting_category_id, self.fallback_cat.pk)

    def test_bundle_mixed_real_and_null_stamps_fallback(self):
        # Decision: the pre-existing "only if all atoms share one category"
        # rule already resolves a mixed bundle to None (categories =
        # {cat_labor, None}, two distinct values). Because a null atom is
        # part of that mix, the null-derived None gets the fallback
        # substituted rather than staying bare None.
        t_real = self._make_task('Real', self.cat_labor)
        t_null = self._make_task('Null', None)
        line_item = InvoiceWizardService.add_atoms_to_new_line_item(
            self.invoice,
            [{'type': 'task', 'id': t_real.pk}, {'type': 'task', 'id': t_null.pk}],
        )
        self.assertEqual(line_item.accounting_category_id, self.fallback_cat.pk)

    def test_bundle_two_different_real_categories_stays_none(self):
        # No null atom involved at all — the pre-existing "pick manually"
        # behavior is unchanged: category stays bare None, fallback never
        # consulted (no error, no stamp).
        task = self._make_task('Labor', self.cat_labor)
        material = Material.objects.create(
            job=self.job, description='Plywood',
            quantity=Decimal('1.00'), sell_price=Decimal('25.00'),
            accounting_category=self.cat_materials,
        )
        material.consumption_state = Material.CONSUMPTION_STATE_CONSUMED
        material.save(update_fields=['consumption_state'])
        line_item = InvoiceWizardService.add_atoms_to_new_line_item(
            self.invoice,
            [{'type': 'task', 'id': task.pk}, {'type': 'material', 'id': material.pk}],
        )
        self.assertIsNone(line_item.accounting_category_id)


class NoFallbackConfiguredTest(FallbackStampingBaseSetup):
    def setUp(self):
        super().setUp()
        # Un-configure the fallback for this test class.
        Configuration.objects.filter(key='fallback_accounting_category').delete()

    def test_null_ac_atom_raises_naming_the_settings_key(self):
        task = self._make_task('Flat work', None)
        with self.assertRaises(ValidationError) as ctx:
            InvoiceWizardService.add_atoms_to_new_line_item(
                self.invoice, [{'type': 'task', 'id': task.pk}],
            )
        msg = str(ctx.exception)
        self.assertIn('fallback_accounting_category', msg)
        # Operation error, not a field-keyed one.
        self.assertFalse(hasattr(ctx.exception, 'message_dict'))

    def test_no_line_item_persisted_when_fallback_missing(self):
        task = self._make_task('Flat work', None)
        before = InvoiceLineItem.objects.filter(invoice=self.invoice).count()
        try:
            InvoiceWizardService.add_atoms_to_new_line_item(
                self.invoice, [{'type': 'task', 'id': task.pk}],
            )
        except ValidationError:
            pass
        self.assertEqual(
            InvoiceLineItem.objects.filter(invoice=self.invoice).count(), before,
        )

    def test_real_ac_atom_unaffected_by_missing_fallback(self):
        task = self._make_task('Real AC work', self.cat_labor)
        line_item = InvoiceWizardService.add_atoms_to_new_line_item(
            self.invoice, [{'type': 'task', 'id': task.pk}],
        )
        self.assertEqual(line_item.accounting_category_id, self.cat_labor.pk)

    def test_bundle_two_different_real_categories_no_error(self):
        # No null atom present -> the fallback is never consulted, so its
        # absence must not raise here either.
        task = self._make_task('Labor', self.cat_labor)
        material = Material.objects.create(
            job=self.job, description='Plywood',
            quantity=Decimal('1.00'), sell_price=Decimal('25.00'),
            accounting_category=self.cat_materials,
        )
        material.consumption_state = Material.CONSUMPTION_STATE_CONSUMED
        material.save(update_fields=['consumption_state'])
        line_item = InvoiceWizardService.add_atoms_to_new_line_item(
            self.invoice,
            [{'type': 'task', 'id': task.pk}, {'type': 'material', 'id': material.pk}],
        )
        self.assertIsNone(line_item.accounting_category_id)


class ReleaseAndReAddRegeneratesFlagTest(FallbackStampingBaseSetup):
    def test_delete_then_readd_restamps_and_reflags(self):
        task = self._make_task('Flat work', None)
        line_item = InvoiceWizardService.add_atoms_to_new_line_item(
            self.invoice, [{'type': 'task', 'id': task.pk}],
        )
        self.assertEqual(line_item.accounting_category_id, self.fallback_cat.pk)
        self.assertTrue(InvoiceLineItemSerializer(line_item).data['used_fallback_ac'])

        # Release: delete the line via the proper service (renumbering
        # path) — the atom's own AC is never touched, so the task itself
        # is still null.
        InvoiceService.delete_line_item(line_item.pk)
        task.refresh_from_db()
        self.assertIsNone(task.accounting_category_id)
        pool = InvoiceWizardService.get_source_pool(self.invoice)
        flat = next(t for t in pool['tasks'] if t['name'] == 'Flat work')
        atom = next(a for a in flat['atoms'] if a['type'] == 'task')
        self.assertEqual(atom['state'], 'available')

        # Re-add: a fresh line is created and re-stamped/re-flagged.
        new_line = InvoiceWizardService.add_atoms_to_new_line_item(
            self.invoice, [{'type': 'task', 'id': task.pk}],
        )
        self.assertNotEqual(new_line.pk, line_item.pk)
        self.assertEqual(new_line.accounting_category_id, self.fallback_cat.pk)
        self.assertTrue(InvoiceLineItemSerializer(new_line).data['used_fallback_ac'])


class CopyFromEstimateFallbackTest(TestCase):
    def setUp(self):
        _seq_config()
        self.cat = AccountingCategory.objects.create(code='LAB-CFB', name='Labor-CFB')
        self.fallback_cat = AccountingCategory.objects.create(
            code='UNC-CFB', name='Uncategorized income',
        )
        self.contact = Contact.objects.create(
            first_name='Copy', last_name='FB', email='copy-fb@test.com',
        )
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_APPROVED,
            job_number='JOB-CFB-0001',
        )
        self.est = Estimate.objects.create(
            job=self.job, estimate_number='EST-CFB-1', version=1,
            status=Estimate.STATUS_ACCEPTED,
        )
        # A null-AC line — the estimate-side atom-backed exemption
        # (task-owned-money Phase 2/3) legally allows this.
        self.null_line = EstimateLineItem.objects.create(
            estimate=self.est, line_number=1, qty=Decimal('1'),
            units='ea', description='Flat work', price=Decimal('40.00'),
            accounting_category=None,
        )
        self.real_line = EstimateLineItem.objects.create(
            estimate=self.est, line_number=2, qty=Decimal('2'),
            units='hr', description='Labor hours', price=Decimal('50.00'),
            accounting_category=self.cat,
        )
        self.invoice = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)

    def test_null_ac_line_stamped_at_copy_time(self):
        Configuration.objects.create(
            key='fallback_accounting_category', value=str(self.fallback_cat.pk),
        )
        InvoiceService.copy_from_estimate(self.invoice)
        lines = {
            li.description: li
            for li in InvoiceLineItem.objects.filter(invoice=self.invoice)
        }
        self.assertEqual(
            lines['Flat work'].accounting_category_id, self.fallback_cat.pk,
        )
        self.assertEqual(
            lines['Labor hours'].accounting_category_id, self.cat.pk,
        )

    def test_null_ac_line_raises_without_fallback_configured(self):
        with self.assertRaises(ValidationError) as ctx:
            InvoiceService.copy_from_estimate(self.invoice)
        self.assertIn('fallback_accounting_category', str(ctx.exception))
        # Nothing partially committed.
        self.assertEqual(
            InvoiceLineItem.objects.filter(invoice=self.invoice).count(), 0,
        )

    def test_all_real_ac_lines_never_consult_fallback(self):
        # No fallback configured, but the copy has no null-AC line, so it
        # must succeed without ever needing one.
        EstimateLineItem.objects.filter(pk=self.null_line.pk).delete()
        created = InvoiceService.copy_from_estimate(self.invoice)
        self.assertEqual(created, 1)


class UsedFallbackAcSerializerTest(TestCase):
    def setUp(self):
        _seq_config()
        self.cat = AccountingCategory.objects.create(code='LAB-SER', name='Labor-SER')
        self.fallback_cat = AccountingCategory.objects.create(
            code='UNC-SER', name='Uncategorized income',
        )
        self.contact = Contact.objects.create(
            first_name='Ser', last_name='FB', email='ser-fb@test.com',
        )
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_APPROVED,
            job_number='JOB-SFB-0001',
        )
        self.invoice = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)

    def test_true_when_matches_configured_fallback(self):
        Configuration.objects.create(
            key='fallback_accounting_category', value=str(self.fallback_cat.pk),
        )
        li = InvoiceLineItem.objects.create(
            invoice=self.invoice, description='x', qty=Decimal('1'),
            price=Decimal('10.00'), accounting_category=self.fallback_cat,
        )
        self.assertTrue(InvoiceLineItemSerializer(li).data['used_fallback_ac'])

    def test_false_when_real_category(self):
        Configuration.objects.create(
            key='fallback_accounting_category', value=str(self.fallback_cat.pk),
        )
        li = InvoiceLineItem.objects.create(
            invoice=self.invoice, description='x', qty=Decimal('1'),
            price=Decimal('10.00'), accounting_category=self.cat,
        )
        self.assertFalse(InvoiceLineItemSerializer(li).data['used_fallback_ac'])

    def test_false_when_no_category(self):
        li = InvoiceLineItem.objects.create(
            invoice=self.invoice, description='x', qty=Decimal('1'),
            price=Decimal('10.00'), accounting_category=None,
        )
        self.assertFalse(InvoiceLineItemSerializer(li).data['used_fallback_ac'])

    def test_false_when_fallback_not_currently_configured(self):
        # A line that HAPPENS to carry the same id as the (now-unset)
        # fallback config must not be flagged — the check is against the
        # CURRENTLY configured fallback, not a remembered stamp.
        li = InvoiceLineItem.objects.create(
            invoice=self.invoice, description='x', qty=Decimal('1'),
            price=Decimal('10.00'), accounting_category=self.fallback_cat,
        )
        self.assertFalse(InvoiceLineItemSerializer(li).data['used_fallback_ac'])


class EstimateSideNotStampedTest(TestCase):
    """Requirement 5: estimate-side compose is NOT stamped, even with a
    fallback configured — task-owned-money Phase 3 is invoice-only."""

    def setUp(self):
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.update_or_create(key='job_number_sequence', defaults={'value': 'JOB-{year}-{counter:04d}'})
        AppState.objects.update_or_create(key='job_counter', defaults={'value': '0'})
        self.fallback_cat = AccountingCategory.objects.create(
            code='UNC-EST', name='Uncategorized income',
        )
        Configuration.objects.create(
            key='fallback_accounting_category', value=str(self.fallback_cat.pk),
        )
        self.contact = Contact.objects.create(
            first_name='Est', last_name='NoStamp', email='est-nostamp@test.com',
        )
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-ENS-0001',
        )
        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number=self.job.job_number, version=1,
            status=Estimate.STATUS_DRAFT,
        )
        self.task = Task(
            job=self.job, name='Flat estimate work',
            qty_source=Task.QTY_ENTERED, rate=Decimal('25.00'),
            unit_label='hour', actual_qty=Decimal('1.00'),
            accounting_category=None,
        )
        self.task.save()

    def test_null_ac_atom_stays_null_on_estimate_line(self):
        line = EstimateWizardService.add_atoms_to_new_line_item(
            self.estimate, [{'type': 'task', 'id': self.task.pk}],
        )
        self.assertIsNone(line.accounting_category_id)


class InvoiceWizardApiFallbackTest(TestCase):
    """API-level smoke test: the no-fallback error renders in the
    contract's operation-error shape, and used_fallback_ac rides along on
    the JSON payload."""

    def setUp(self):
        _seq_config()
        self.cat = AccountingCategory.objects.create(code='LAB-API-FB', name='Labor-API-FB')
        self.fallback_cat = AccountingCategory.objects.create(
            code='UNC-API-FB', name='Uncategorized income',
        )
        self.contact = Contact.objects.create(
            first_name='Api', last_name='FB', email='api-fb@test.com',
        )
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_APPROVED,
            job_number='JOB-AFB-0001',
        )
        self.task = Task(
            job=self.job, name='Flat api work',
            qty_source=Task.QTY_ENTERED, rate=Decimal('25.00'),
            unit_label='hour', actual_qty=Decimal('1.00'),
            accounting_category=None,
        )
        self.task.save()
        self.task.status = Task.STATUS_COMPLETE
        self.task.save()
        self.invoice = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)

        self.user = User.objects.create_user(username='fb-api', password='pw')
        self.user.user_permissions.add(
            Permission.objects.get(codename='can_manage_financials')
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_error_shape_when_no_fallback_configured(self):
        resp = self.client.post(
            f'/api/invoices/{self.invoice.pk}/line-items-from-atoms/',
            {'atoms': [{'type': 'task', 'id': self.task.pk}]},
            format='json',
        )
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertIn('detail', resp.data)
        self.assertIn('fallback_accounting_category', resp.data['detail'])

    def test_used_fallback_ac_on_response_payload(self):
        Configuration.objects.create(
            key='fallback_accounting_category', value=str(self.fallback_cat.pk),
        )
        resp = self.client.post(
            f'/api/invoices/{self.invoice.pk}/line-items-from-atoms/',
            {'atoms': [{'type': 'task', 'id': self.task.pk}]},
            format='json',
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertTrue(resp.data['used_fallback_ac'])
        self.assertEqual(resp.data['accounting_category'], self.fallback_cat.pk)

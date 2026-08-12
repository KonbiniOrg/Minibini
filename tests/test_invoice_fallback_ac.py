"""Tests for Phase 3 Task 5: invoice authoring stamps the configured
fallback AccountingCategory onto lines derived from a null-AC atom (or a
mixed-category bundle, which the wizard's own bundling logic already
collapses to `category = None`), and the read-only `used_fallback_ac`
serializer flag that reports it.

Only a Task's own `accounting_category` can be null among the atom types
the invoice wizard consumes (Material/Expense/deposit-credit AC are all
non-nullable model fields — see Phase 3 Task 4's audit) — so every
null-AC scenario below routes through a Task atom.

Mirrors `_resolve_deposit_category`'s shape for the fallback lookup
(`InvoiceService.resolve_line_category`) and
`AccountingCategorySerializer.get_is_fallback`'s context-memoization
shape (commit de071827) for `used_fallback_ac`.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.api.invoicing.serializers import InvoiceLineItemSerializer
from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, AppState, Configuration, User
from apps.estimates.models import Estimate, EstimateLineItem
from apps.estimates.services import EstimateService, EstimateWizardService
from apps.inventory.models import Material
from apps.invoicing.models import Invoice, InvoiceLineItem
from apps.invoicing.services import (
    InvoiceEmailService, InvoiceService, InvoiceWizardService,
)
from apps.jobs.models import Blep, Job, RateScheme, Task


class FallbackACTestBase(TestCase):
    """Shared fixture: a job, an ELAPSED_TIME RateScheme (cat_labor), and
    helpers to mint billable Task atoms (optionally with a cleared AC) and
    to configure the fallback_accounting_category Configuration key."""

    def setUp(self):
        Configuration.objects.create(
            key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        AppState.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(
            key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.update_or_create(
            key='job_number_sequence',
            defaults={'value': 'JOB-{year}-{counter:04d}'})
        AppState.objects.update_or_create(
            key='job_counter', defaults={'value': '0'})

        self.user = User.objects.create_user(username='fac_user', password='pw')
        self.cat_labor = AccountingCategory.objects.create(
            code='FAC-LBR', name='Labor', is_active=True)
        self.cat_fallback = AccountingCategory.objects.create(
            code='FAC-FALL', name='Fallback', is_active=True)
        self.contact = Contact.objects.create(
            first_name='Fal', last_name='Back',
            email='fallback@example.com', mobile_number='555-0001',
        )
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_APPROVED,
            job_number='JOB-FAC-0001',
        )
        self.scheme = RateScheme.objects.create(
            name='Hourly-fac', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('25.00'), unit_label='hour',
            accounting_category=self.cat_labor,
        )
        self._task_counter = 0

    def _configure_fallback(self, category=None):
        cat = category or self.cat_fallback
        Configuration.objects.update_or_create(
            key='fallback_accounting_category',
            defaults={'value': str(cat.pk)},
        )
        return cat

    def _make_task(self, name, *, clear_category=False):
        # A distinct, non-overlapping window per task so multiple tasks in
        # one test never collide on Blep uniqueness.
        self._task_counter += 1
        start = (timezone.now()
                 - timezone.timedelta(hours=self._task_counter * 3))
        task = Task(job=self.job, name=name)
        task.stamp_from_scheme(self.scheme)
        task.save()
        if clear_category:
            task.accounting_category = None
            task.save()
        Blep.objects.create(
            task=task, user=self.user, start_time=start,
            end_time=start + timezone.timedelta(hours=1),
        )
        task.status = Task.STATUS_COMPLETE
        task.save()
        return task

    def _draft_invoice(self):
        return Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)


class SingleNullCategoryTaskAtomTest(FallbackACTestBase):
    def test_line_stamped_with_fallback_and_flag_true(self):
        self._configure_fallback()
        task = self._make_task('Labor', clear_category=True)
        invoice = self._draft_invoice()

        li = InvoiceWizardService.add_atoms_to_new_line_item(
            invoice, [{'type': 'task', 'id': task.pk}])

        self.assertEqual(li.accounting_category, self.cat_fallback)
        data = InvoiceLineItemSerializer(li).data
        self.assertTrue(data['used_fallback_ac'])


class MixedCategoryBundleTest(FallbackACTestBase):
    def test_mixed_bundle_stamps_fallback(self):
        self._configure_fallback()
        task = self._make_task('Labor')  # cat_labor
        cat_materials = AccountingCategory.objects.create(
            code='FAC-MAT', name='Materials', is_active=True)
        material = Material.objects.create(
            job=self.job, task=task, description='Wood',
            quantity=Decimal('1'), sell_price=Decimal('10.00'),
            accounting_category=cat_materials,
        )
        material.consumption_state = Material.CONSUMPTION_STATE_CONSUMED
        material.save(update_fields=['consumption_state'])
        invoice = self._draft_invoice()

        li = InvoiceWizardService.add_atoms_to_new_line_item(
            invoice,
            [{'type': 'task', 'id': task.pk},
             {'type': 'material', 'id': material.pk}],
        )

        self.assertEqual(li.accounting_category, self.cat_fallback)
        data = InvoiceLineItemSerializer(li).data
        self.assertTrue(data['used_fallback_ac'])


class UniformCategoryBundleTest(FallbackACTestBase):
    def test_uniform_bundle_keeps_real_category_flag_false(self):
        self._configure_fallback()
        task1 = self._make_task('Labor 1')
        task2 = self._make_task('Labor 2')
        invoice = self._draft_invoice()

        li = InvoiceWizardService.add_atoms_to_new_line_item(
            invoice,
            [{'type': 'task', 'id': task1.pk},
             {'type': 'task', 'id': task2.pk}],
        )

        self.assertEqual(li.accounting_category, self.cat_labor)
        data = InvoiceLineItemSerializer(li).data
        self.assertFalse(data['used_fallback_ac'])


class EstimateLineStaysNullTest(FallbackACTestBase):
    def test_estimate_wizard_leaves_null_ac_atom_null(self):
        # Deliberately no fallback configured — proves the estimate wizard
        # path never even consults the setting; _resolve_line_category is
        # identity there (BaseWizardService's own implementation).
        task = self._make_task('Labor', clear_category=True)
        estimate = Estimate.objects.create(
            job=self.job, estimate_number=self.job.job_number, version=1,
            status=Estimate.STATUS_DRAFT,
        )

        li = EstimateWizardService.add_atoms_to_new_line_item(
            estimate, [{'type': 'task', 'id': task.pk}])

        self.assertIsNone(li.accounting_category)


class SeedAndRestoreAgreementNullAcTest(FallbackACTestBase):
    def setUp(self):
        super().setUp()
        self._configure_fallback()
        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number=self.job.job_number, version=1,
            status=Estimate.STATUS_ACCEPTED,
        )
        # A bare hand line with no accounting_category — legal at the model
        # level (nullable FK); compose_agreement reads accounting_category_id
        # straight off this row (apps/estimates/agreement.py).
        self.null_line = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=1, qty=Decimal('1'),
            units='ea', description='Uncategorized hand line',
            price=Decimal('50.00'), accounting_category=None,
        )

    def test_seed_from_agreement_stamps_fallback(self):
        invoice = self._draft_invoice()
        created = InvoiceService.seed_from_agreement(invoice)
        self.assertEqual(created, 1)
        li = InvoiceLineItem.objects.get(invoice=invoice)
        self.assertEqual(li.accounting_category, self.cat_fallback)

    def test_restore_agreement_line_stamps_fallback(self):
        invoice = self._draft_invoice()
        li = InvoiceService.restore_agreement_line(
            invoice, estimate_line_id=self.null_line.pk)
        self.assertEqual(li.accounting_category, self.cat_fallback)

    def test_copy_from_estimate_stamps_fallback(self):
        # A third construction site reading the same compose_agreement
        # line dict (apps.invoicing.services.InvoiceService.copy_from_estimate)
        # — audited during Task 5 and routed through the same helper.
        invoice = self._draft_invoice()
        created = InvoiceService.copy_from_estimate(invoice)
        self.assertEqual(created, 1)
        li = InvoiceLineItem.objects.get(invoice=invoice)
        self.assertEqual(li.accounting_category, self.cat_fallback)


class AdjustmentLineCarriesRealAcTest(FallbackACTestBase):
    """Final-review fix (Critical): an agreement adjustment line built
    through the real production path — EstimateService.add_adjustment_line,
    which stamps the PERCENTAGE RateScheme's own accounting_category (a
    required, non-nullable field) — always carries a real AC.
    `_agreement_category_id` must pass that AC through unmodified: never
    null it out (the original Task 5 fix's bug — it unconditionally
    returned None for any is_adjustment line, discarding a real AC and
    leaving the seeded/restored/copied line blocked at send with no way
    to fix it), and never substitute the fallback for it either (an
    adjustment targets *other* lines' categories, so the fallback must
    never override its own display AC).

    Deliberately does NOT configure fallback_accounting_category in this
    class — proves resolve_line_category is never even consulted for a
    real-AC adjustment line (if it were, and none configured, these tests
    would raise ValidationError instead of passing)."""

    def setUp(self):
        super().setUp()
        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number=self.job.job_number, version=1,
            status=Estimate.STATUS_DRAFT,
        )
        self.base_line = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=1, qty=Decimal('2'),
            units='hour', description='Labor', price=Decimal('50.00'),
            accounting_category=self.cat_labor,
        )
        self.rush_svc = RateScheme.objects.create(
            name='Rush-fac', algorithm=RateScheme.PERCENTAGE,
            rate=Decimal('10.00'), unit_label='%',
            accounting_category=self.cat_labor,
        )
        # The real production path (NOT raw ORM) — stamps
        # svc.accounting_category, exactly like the invoice-side
        # InvoiceService.add_adjustment_line does.
        self.adj_line = EstimateService.add_adjustment_line(
            self.estimate, adjustment_service_id=self.rush_svc.pk,
            target_category_ids=[self.cat_labor.pk],
        )
        # Estimate.clean() only allows draft -> open -> accepted, not a
        # direct draft -> accepted jump.
        self.estimate.status = Estimate.STATUS_OPEN
        self.estimate.save()
        self.estimate.status = Estimate.STATUS_ACCEPTED
        self.estimate.save()

    def test_seed_from_agreement_carries_real_adjustment_ac(self):
        invoice = self._draft_invoice()
        InvoiceService.seed_from_agreement(invoice)
        adj = InvoiceLineItem.objects.get(
            invoice=invoice, adjustment_service_id=self.rush_svc.pk)
        self.assertEqual(adj.accounting_category, self.cat_labor)
        # Must not block send on the seeded adjustment line's category.
        InvoiceEmailService._assert_all_lines_categorized(invoice)

    def test_restore_agreement_line_carries_real_adjustment_ac(self):
        invoice = self._draft_invoice()
        li = InvoiceService.restore_agreement_line(
            invoice, estimate_line_id=self.adj_line.pk)
        self.assertEqual(li.accounting_category, self.cat_labor)

    def test_copy_from_estimate_carries_real_adjustment_ac(self):
        invoice = self._draft_invoice()
        InvoiceService.copy_from_estimate(invoice)
        adj = InvoiceLineItem.objects.get(
            invoice=invoice, adjustment_service_id=self.rush_svc.pk)
        self.assertEqual(adj.accounting_category, self.cat_labor)


class NoFallbackConfiguredTest(FallbackACTestBase):
    def test_no_fallback_configured_raises_naming_key(self):
        task = self._make_task('Labor', clear_category=True)
        invoice = self._draft_invoice()

        with self.assertRaises(ValidationError) as ctx:
            InvoiceWizardService.add_atoms_to_new_line_item(
                invoice, [{'type': 'task', 'id': task.pk}])
        self.assertIn('fallback_accounting_category', str(ctx.exception))

    def test_deactivated_fallback_id_raises_same_error(self):
        stale = AccountingCategory.objects.create(
            code='FAC-STALE', name='Stale', is_active=True)
        Configuration.objects.create(
            key='fallback_accounting_category', value=str(stale.pk))
        stale.is_active = False
        stale.save()
        task = self._make_task('Labor', clear_category=True)
        invoice = self._draft_invoice()

        with self.assertRaises(ValidationError) as ctx:
            InvoiceWizardService.add_atoms_to_new_line_item(
                invoice, [{'type': 'task', 'id': task.pk}])
        self.assertIn('fallback_accounting_category', str(ctx.exception))

    def test_deleted_fallback_id_raises_same_error(self):
        ephemeral = AccountingCategory.objects.create(
            code='FAC-EPH', name='Ephemeral', is_active=True)
        Configuration.objects.create(
            key='fallback_accounting_category', value=str(ephemeral.pk))
        ephemeral.delete()
        task = self._make_task('Labor', clear_category=True)
        invoice = self._draft_invoice()

        with self.assertRaises(ValidationError) as ctx:
            InvoiceWizardService.add_atoms_to_new_line_item(
                invoice, [{'type': 'task', 'id': task.pk}])
        self.assertIn('fallback_accounting_category', str(ctx.exception))

    def test_seeding_with_no_fallback_configured_also_raises(self):
        # Same coaching error out of seed_from_agreement's construction
        # path, not just the atom wizard's.
        estimate = Estimate.objects.create(
            job=self.job, estimate_number=self.job.job_number, version=1,
            status=Estimate.STATUS_ACCEPTED,
        )
        EstimateLineItem.objects.create(
            estimate=estimate, line_number=1, qty=Decimal('1'),
            units='ea', description='Uncategorized hand line',
            price=Decimal('50.00'), accounting_category=None,
        )
        invoice = self._draft_invoice()

        with self.assertRaises(ValidationError) as ctx:
            InvoiceService.seed_from_agreement(invoice)
        self.assertIn('fallback_accounting_category', str(ctx.exception))


class CorrectingAcAfterwardTest(FallbackACTestBase):
    def test_updating_ac_clears_used_fallback_flag(self):
        self._configure_fallback()
        task = self._make_task('Labor', clear_category=True)
        invoice = self._draft_invoice()
        li = InvoiceWizardService.add_atoms_to_new_line_item(
            invoice, [{'type': 'task', 'id': task.pk}])
        self.assertTrue(InvoiceLineItemSerializer(li).data['used_fallback_ac'])

        real_cat = AccountingCategory.objects.create(
            code='FAC-REAL', name='Real', is_active=True)
        li = InvoiceService.update_line_item(
            li.pk, accounting_category=real_cat)

        self.assertEqual(li.accounting_category, real_cat)
        self.assertFalse(InvoiceLineItemSerializer(li).data['used_fallback_ac'])


class ResolveLineCategoryHelperTest(FallbackACTestBase):
    """Direct unit coverage of InvoiceService.resolve_line_category — the
    shared lookup both the wizard hook and the agreement-seeding paths
    call through."""

    def test_returns_configured_active_category(self):
        self._configure_fallback()
        self.assertEqual(
            InvoiceService.resolve_line_category(), self.cat_fallback)

    def test_blank_configuration_value_raises(self):
        Configuration.objects.create(key='fallback_accounting_category', value='')
        with self.assertRaises(ValidationError) as ctx:
            InvoiceService.resolve_line_category()
        self.assertIn('fallback_accounting_category', str(ctx.exception))

    def test_no_configuration_row_raises(self):
        with self.assertRaises(ValidationError) as ctx:
            InvoiceService.resolve_line_category()
        self.assertIn('fallback_accounting_category', str(ctx.exception))

    def test_deposit_flagged_fallback_id_raises(self):
        # Final-review fix (Minor): a later edit to the DESIGNATED
        # category flipping is_deposit=True must not silently start
        # stamping a deposit-collection category onto ordinary lines —
        # symmetric with the designation-time PATCH validation
        # (apps/api/templates_config/views.py already rejects
        # is_deposit=True at configure time).
        self._configure_fallback()
        self.cat_fallback.is_deposit = True
        self.cat_fallback.taxable = False  # AccountingCategory.clean(): deposit implies non-taxable
        self.cat_fallback.save()
        with self.assertRaises(ValidationError) as ctx:
            InvoiceService.resolve_line_category()
        self.assertIn('fallback_accounting_category', str(ctx.exception))

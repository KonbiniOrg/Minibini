from decimal import Decimal
from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, Configuration, AppState
from apps.estimates.models import Estimate, EstimateLineItem, ServiceItem
from apps.jobs.models import Job, RateScheme


class DeferredServiceBase(TestCase):
    def setUp(self):
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.update_or_create(key='job_number_sequence', defaults={'value': 'JOB-{year}-{counter:04d}'})
        AppState.objects.update_or_create(key='job_counter', defaults={'value': '0'})

        self.cat = AccountingCategory.objects.create(name='Labor', is_active=True, code='LAB')
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555-0',
        )
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_APPROVED, job_number='JOB-2026-0001',
        )
        self.scheme = RateScheme.objects.create(
            name='Hourly', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('40'), unit_label='hour', accounting_category=self.cat,
        )
        self.service_item = ServiceItem.objects.create(
            template_name='CAM coding', description='tmpl desc',
            rate_scheme=self.scheme, default_active_modifiers=[],
        )
        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-2026-0001', status=Estimate.STATUS_DRAFT,
        )


from apps.estimates.services import EstimateService
from apps.core.services import NotFoundError
from django.core.exceptions import ValidationError


class AddLineFromServiceTest(DeferredServiceBase):
    def test_snapshots_priced_values_and_creates_no_task(self):
        from apps.jobs.models import Task
        # base 40 + 10% modifier -> 44.00 effective unit rate.
        # RateScheme forbids editing a referenced scheme; create a fresh one
        # with modifiers pre-set and point the service_item at it.
        scheme_rush = RateScheme.objects.create(
            name='Hourly Rush', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('40'), unit_label='hour',
            modifiers=[{'key': 'rush', 'percent': 10}],
            accounting_category=self.cat,
        )
        self.service_item.rate_scheme = scheme_rush
        self.service_item.default_active_modifiers = ['rush']
        self.service_item.save()

        line = EstimateService.add_line_item_from_service(
            self.estimate.pk, self.service_item.pk, Decimal('2'),
        )
        line.refresh_from_db()
        self.assertEqual(line.service_item_id, self.service_item.pk)
        self.assertEqual(line.price, Decimal('44.00'))          # effective_rate snapshot
        self.assertEqual(line.qty, Decimal('2'))
        self.assertEqual(line.accounting_category_id, self.cat.pk)
        self.assertEqual(line.units, 'hour')
        self.assertEqual(line.description, 'CAM coding')         # from template_name, editable
        # No Task minted on the job — deferral, not immediate atom.
        self.assertFalse(Task.objects.filter(job=self.job).exists())
        # No source row yet (crystallizes at acceptance).
        self.assertFalse(line.sources.exists())

    def test_rejects_non_draft_estimate(self):
        # Force non-draft status via DB update to bypass the "needs a line item"
        # model validation — this is test-setup-only state forcing, not production code.
        Estimate.objects.filter(pk=self.estimate.pk).update(status=Estimate.STATUS_OPEN)
        with self.assertRaises(ValidationError):
            EstimateService.add_line_item_from_service(
                self.estimate.pk, self.service_item.pk, Decimal('1'),
            )

    def test_missing_service_item_raises_not_found(self):
        with self.assertRaises(NotFoundError):
            EstimateService.add_line_item_from_service(
                self.estimate.pk, 999999, Decimal('1'),
            )

    def test_float_qty_normalized_via_str(self):
        # A raw JSON float (2.2) must not expand to its binary value and trip
        # the 2-decimal-places validator — the money-input float class bug.
        line = EstimateService.add_line_item_from_service(
            self.estimate.pk, self.service_item.pk, 2.2,
        )
        line.refresh_from_db()
        self.assertEqual(line.qty, Decimal('2.2'))

    def test_garbage_qty_rejected(self):
        with self.assertRaises(ValidationError):
            EstimateService.add_line_item_from_service(
                self.estimate.pk, self.service_item.pk, 'lots',
            )


class ServiceItemFieldTest(DeferredServiceBase):
    def test_line_can_carry_service_item_and_defaults_null(self):
        bare = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=1, description='x',
            qty=Decimal('1'), price=Decimal('0'), accounting_category=self.cat,
        )
        self.assertIsNone(bare.service_item)
        line = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=2, description='CAM coding',
            qty=Decimal('1'), price=Decimal('40'), accounting_category=self.cat,
            service_item=self.service_item,
        )
        line.refresh_from_db()
        self.assertEqual(line.service_item_id, self.service_item.pk)


from apps.jobs.models import SchemeInactiveError


class GenerateTaskInactiveSchemeTest(DeferredServiceBase):
    """Task 3 moved the creation-time gate from RateScheme supersession
    (``replaced_by``) to ``is_active``; Task 4 deletes supersession
    entirely, so ``is_active`` is now the sole retirement signal.
    """

    def _retire(self):
        # Direct assign+save (not .update()): editing/retiring a referenced
        # scheme is freely allowed post-Task-4, and this also keeps
        # self.service_item's cached rate_scheme FK in sync (same in-memory
        # instance as self.scheme).
        self.scheme.is_active = False
        self.scheme.save()

    def test_inactive_scheme_aborts_by_default(self):
        self._retire()
        with self.assertRaises(SchemeInactiveError):
            self.service_item.generate_task(self.job, est_qty=Decimal('1'))

    def test_allow_inactive_scheme_bypasses_and_builds_task(self):
        self._retire()
        task = self.service_item.generate_task(
            self.job, est_qty=Decimal('1'),
            description='desc from line', allow_inactive_scheme=True,
        )
        self.assertEqual(task.name, 'CAM coding')          # from template_name
        self.assertEqual(task.description, 'desc from line')
        self.assertEqual(task.source_scheme_id, self.scheme.pk)


from rest_framework.test import APIClient
from apps.core.models import User


class LineItemsFromServiceApiTest(DeferredServiceBase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(
            username='mgr', password='pw', email='mgr@x.com',
        )
        # can_manage_jobs atom so CanManageJobOrPM passes for a non-PM job.
        from django.contrib.auth.models import Permission
        perm = Permission.objects.get(codename='can_manage_jobs')
        self.user.user_permissions.add(perm)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_posts_a_deferred_service_line(self):
        from apps.jobs.models import Task
        resp = self.client.post(
            f'/api/estimates/{self.estimate.pk}/line-items-from-service/',
            {'service_item': self.service_item.pk, 'qty': '3'}, format='json',
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data['service_item'], self.service_item.pk)
        self.assertEqual(resp.data['description'], 'CAM coding')
        self.assertEqual(Decimal(resp.data['price']), Decimal('40.00'))
        self.assertEqual(Decimal(resp.data['qty']), Decimal('3'))
        # Still deferred: no Task minted.
        self.assertFalse(Task.objects.filter(job=self.job).exists())

    def test_missing_service_item_is_404(self):
        resp = self.client.post(
            f'/api/estimates/{self.estimate.pk}/line-items-from-service/',
            {'service_item': 999999, 'qty': '1'}, format='json',
        )
        self.assertEqual(resp.status_code, 404)


from apps.api.estimates.serializers import EstimateLineItemSerializer


class ServiceLineSerializerTest(DeferredServiceBase):
    def test_exposes_service_item_and_detail_and_price(self):
        line = EstimateService.add_line_item_from_service(
            self.estimate.pk, self.service_item.pk, Decimal('2'),
        )
        data = EstimateLineItemSerializer(line).data
        self.assertEqual(data['service_item'], self.service_item.pk)
        self.assertEqual(data['service_item_detail']['name'], 'CAM coding')
        self.assertEqual(Decimal(data['price']), Decimal('40.00'))
        self.assertEqual(Decimal(data['qty']), Decimal('2'))
        # Amount is qty x price (self-contained snapshot): 2 x 40 = 80.
        self.assertEqual(
            Decimal(data['qty']) * Decimal(data['price']), Decimal('80.00'),
        )


from apps.deliverables.models import Deliverable
from apps.estimates.acceptance import EstimateAcceptanceService
from apps.estimates.models import EstimateLineItemSource


class OnAcceptCrystallizesServiceTest(DeferredServiceBase):
    # Note: we do NOT change estimate.status in setUp — Estimate.save() blocks
    # DRAFT→OPEN without line items, and on_accept does not require any particular
    # status; it is driven by signals in production but callable directly in tests.

    def test_service_line_becomes_a_task_and_source_links(self):
        from apps.jobs.models import Task, Fee
        line = EstimateService.add_line_item_from_service(
            self.estimate.pk, self.service_item.pk, Decimal('2'),
        )
        # Edit the description as a user would; it becomes the Task description.
        line.description = 'CAM coding for panel A'
        line.save()

        result = EstimateAcceptanceService.on_accept(self.estimate)

        task = Task.objects.get(job=self.job)
        self.assertEqual(task.name, 'CAM coding')                  # ServiceItem name
        self.assertEqual(task.description, 'CAM coding for panel A')  # line description
        self.assertEqual(task.source_scheme_id, self.scheme.pk)
        self.assertEqual(task.est_qty, Decimal('2'))
        self.assertEqual(result['tasks_created'], 1)
        # It did NOT become a Fee.
        self.assertFalse(Fee.objects.filter(job=self.job).exists())
        # Source-linked to the Task.
        src = EstimateLineItemSource.objects.get(estimate_line_item=line)
        self.assertEqual(src.source_type, EstimateLineItemSource.SOURCE_TASK)
        self.assertEqual(src.source_pk, task.pk)

    def test_service_line_crystallizes_a_schedulable_task(self):
        """Task 8: the ServiceItem's scheme is unit_label='hour' (setUp) and
        the line only carries qty — generate_task's pair-fill must derive
        est_worker_time so acceptance produces a schedulable task."""
        from datetime import timedelta
        from apps.jobs.models import Task
        EstimateService.add_line_item_from_service(
            self.estimate.pk, self.service_item.pk, Decimal('3'),
        )
        EstimateAcceptanceService.on_accept(self.estimate)
        task = Task.objects.get(job=self.job)
        self.assertEqual(task.est_qty, Decimal('3'))
        self.assertEqual(task.est_worker_time, timedelta(hours=3))

    def test_edited_scheme_does_not_abort_acceptance(self):
        """Editing the preset after the line was added (freely allowed,
        Task 4 — no frozen fields) does not touch the already-queued
        acceptance; only is_active=False raises SchemeInactiveError."""
        from apps.jobs.models import Task
        line = EstimateService.add_line_item_from_service(
            self.estimate.pk, self.service_item.pk, Decimal('1'),
        )
        self.scheme.rate = Decimal('45')
        self.scheme.save()

        # Does NOT raise SchemeInactiveError.
        EstimateAcceptanceService.on_accept(self.estimate)
        self.assertTrue(Task.objects.filter(job=self.job).exists())


class ServiceLineSendGateTest(DeferredServiceBase):
    def test_draft_with_only_a_service_line_can_be_marked_open(self):
        EstimateService.add_line_item_from_service(
            self.estimate.pk, self.service_item.pk, Decimal('1'),
        )
        Deliverable.objects.create(
            job=self.job, description='widget', qty_ordered=Decimal('1'), units='each',
        )

        estimate = EstimateService.mark_open(self.estimate.pk)
        self.assertEqual(estimate.status, Estimate.STATUS_OPEN)

    def test_assert_all_hand_lines_have_ac_passes_for_service_line(self):
        EstimateService.add_line_item_from_service(
            self.estimate.pk, self.service_item.pk, Decimal('1'),
        )
        # Snapshot populated the AC → no ValidationError raised.
        EstimateService.assert_all_hand_lines_have_ac(self.estimate)


class ReviseEstimateCarriesDescriptorFieldsTest(DeferredServiceBase):
    """revise_estimate must copy service_item and is_material onto the new revision's lines."""

    def setUp(self):
        super().setUp()
        # Add a deferred service line (requires DRAFT estimate).
        self.service_line = EstimateService.add_line_item_from_service(
            self.estimate.pk, self.service_item.pk, Decimal('2'),
        )
        # Add a bare is_material=True line (requires DRAFT; supply AC explicitly).
        self.material_line = EstimateService.add_line_item(
            self.estimate.pk,
            description='Raw stock',
            qty=Decimal('5'),
            price=Decimal('10'),
            units='ft',
            accounting_category=self.cat.pk,
            is_material=True,
        )
        # revise_estimate requires a non-draft parent. Force OPEN bypassing
        # model validation (the estimate has no deliverable, but that guard is
        # only on the model's save transition — .update() skips it).
        Estimate.objects.filter(pk=self.estimate.pk).update(status=Estimate.STATUS_OPEN)
        self.estimate.refresh_from_db()

    def test_service_item_fk_preserved_on_revision(self):
        revision = EstimateService.revise_estimate(self.estimate.pk)
        lines = list(EstimateLineItem.objects.filter(estimate=revision).order_by('line_number'))
        service_lines = [li for li in lines if li.service_item_id is not None]
        self.assertEqual(len(service_lines), 1)
        self.assertEqual(service_lines[0].service_item_id, self.service_item.pk)

    def test_is_material_preserved_on_revision(self):
        revision = EstimateService.revise_estimate(self.estimate.pk)
        lines = list(EstimateLineItem.objects.filter(estimate=revision).order_by('line_number'))
        material_lines = [li for li in lines if li.is_material]
        self.assertEqual(len(material_lines), 1)
        self.assertEqual(material_lines[0].description, 'Raw stock')

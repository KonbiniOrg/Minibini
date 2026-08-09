from decimal import Decimal

from django.core.exceptions import ValidationError
from tests.base import FixtureTestCase
from apps.estimates.models import Estimate, EstimateLineItem, ChangeOrder, ChangeOrderLineItem, ServiceItem
from apps.inventory.models import InventoryItem, Material
from apps.jobs.models import Job, RateScheme, Task


def _add_line(co):
    return ChangeOrderLineItem.objects.create(
        change_order=co, action=ChangeOrderLineItem.ACTION_ADD,
        description='Added scope', qty=1, price=100, line_number=1,
        # A bare add line needs an AC to pass the send guard (the category
        # rides the line onto the agreement and its invoice copy).
        # 901 = 'SVC' in unit_test_data.json.
        accounting_category_id=901,
    )


class ChangeOrderModelTests(FixtureTestCase):
    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        self.est = Estimate.objects.create(
            job=self.job, estimate_number='EST-CO-1', version=1,
            status=Estimate.STATUS_ACCEPTED,
        )

    def test_create_defaults_to_draft(self):
        co = ChangeOrder.objects.create(job=self.job, estimate=self.est)
        self.assertEqual(co.status, ChangeOrder.STATUS_DRAFT)
        self.assertEqual(co.version, 1)

    def test_number_derives_from_estimate_with_co_ordinal(self):
        co1 = ChangeOrder.objects.create(job=self.job, estimate=self.est)
        co2 = ChangeOrder.objects.create(job=self.job, estimate=self.est)
        self.assertEqual(co1.change_order_number, 'EST-CO-1-CO1')
        self.assertEqual(co2.change_order_number, 'EST-CO-1-CO2')

    def test_draft_to_open_requires_line_item(self):
        co = ChangeOrder.objects.create(job=self.job, estimate=self.est)
        co.status = ChangeOrder.STATUS_OPEN
        with self.assertRaises(ValidationError):
            co.save()

    def test_open_sets_sent_and_expiration(self):
        co = ChangeOrder.objects.create(job=self.job, estimate=self.est)
        _add_line(co)
        co.status = ChangeOrder.STATUS_OPEN
        co.save()
        self.assertIsNotNone(co.sent_date)
        self.assertIsNotNone(co.expiration_date)

    def test_rejected_is_terminal(self):
        co = ChangeOrder.objects.create(job=self.job, estimate=self.est)
        _add_line(co)
        co.status = ChangeOrder.STATUS_OPEN; co.save()
        co.status = ChangeOrder.STATUS_REJECTED; co.save()
        co.status = ChangeOrder.STATUS_DRAFT
        with self.assertRaises(ValidationError):
            co.save()

    def test_public_token_minted_on_create(self):
        co = ChangeOrder.objects.create(job=self.job, estimate=self.est)
        self.assertTrue(co.public_token)
        self.assertGreaterEqual(len(co.public_token), 20)

    def test_public_token_stable_across_saves(self):
        co = ChangeOrder.objects.create(job=self.job, estimate=self.est)
        token = co.public_token
        _add_line(co)
        co.status = ChangeOrder.STATUS_OPEN
        co.save()
        co.refresh_from_db()
        self.assertEqual(co.public_token, token)

    def test_public_token_unique_per_change_order(self):
        co1 = ChangeOrder.objects.create(job=self.job, estimate=self.est)
        co2 = ChangeOrder.objects.create(job=self.job, estimate=self.est)
        self.assertNotEqual(co1.public_token, co2.public_token)


class ChangeOrderLineItemTests(FixtureTestCase):
    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        self.est = Estimate.objects.create(
            job=self.job, estimate_number='EST-CO-2', version=1, status=Estimate.STATUS_ACCEPTED,
        )
        self.co = ChangeOrder.objects.create(job=self.job, estimate=self.est)
        self.target = EstimateLineItem.objects.create(
            estimate=self.est, description='orig', qty=1, price=50, line_number=1,
        )

    def test_remove_requires_target(self):
        li = ChangeOrderLineItem(change_order=self.co, action=ChangeOrderLineItem.ACTION_REMOVE,
                                 description='', qty=1, price=0, line_number=1)
        with self.assertRaises(ValidationError):
            li.full_clean()

    def test_add_rejects_target(self):
        li = ChangeOrderLineItem(change_order=self.co, action=ChangeOrderLineItem.ACTION_ADD,
                                 target_line_item=self.target, description='x', qty=1, price=1, line_number=1)
        with self.assertRaises(ValidationError):
            li.full_clean()

    def test_replace_with_target_ok(self):
        li = ChangeOrderLineItem(change_order=self.co, action=ChangeOrderLineItem.ACTION_REPLACE,
                                 target_line_item=self.target, description='new', qty=2, price=75, line_number=1)
        li.full_clean()  # should not raise


class ChangeOrderLineItemReplaceIsCommercialOnlyTests(FixtureTestCase):
    """action="replace" amends the commercial line only — it can no longer
    carry a crystallization descriptor (service_item/inventory_item/
    is_material). Use remove + add to change the work."""

    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        self.est = Estimate.objects.create(
            job=self.job, estimate_number='EST-CO-3', version=1,
            status=Estimate.STATUS_ACCEPTED,
        )
        self.co = ChangeOrder.objects.create(job=self.job, estimate=self.est)
        self.target = EstimateLineItem.objects.create(
            estimate=self.est, description='orig', qty=1, price=50, line_number=1,
        )
        self.scheme = RateScheme.objects.create(
            name='Hourly-CO3', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('100'), unit_label='hour', accounting_category_id=901,
        )
        self.service_item = ServiceItem.objects.create(
            template_name='CNC cutting CO3', rate_scheme=self.scheme,
        )
        self.pli = InventoryItem.objects.create(
            code='PLY-CO3', accounting_category_id=901,
            qty_on_hand=Decimal('10'), purchase_price=Decimal('5'),
            selling_price=Decimal('10'), units='ea',
        )

    def test_replace_rejects_service_item(self):
        li = ChangeOrderLineItem(
            change_order=self.co, action=ChangeOrderLineItem.ACTION_REPLACE,
            target_line_item=self.target, service_item=self.service_item,
            description='new', qty=2, price=75, line_number=1,
        )
        with self.assertRaises(ValidationError):
            li.full_clean()

    def test_replace_rejects_inventory_item(self):
        li = ChangeOrderLineItem(
            change_order=self.co, action=ChangeOrderLineItem.ACTION_REPLACE,
            target_line_item=self.target, inventory_item=self.pli,
            description='new', qty=2, price=75, line_number=1,
        )
        with self.assertRaises(ValidationError):
            li.full_clean()

    def test_replace_rejects_is_material(self):
        li = ChangeOrderLineItem(
            change_order=self.co, action=ChangeOrderLineItem.ACTION_REPLACE,
            target_line_item=self.target, is_material=True,
            description='new', qty=2, price=75, line_number=1,
        )
        with self.assertRaises(ValidationError):
            li.full_clean()

    def test_replace_bare_commercial_only_ok(self):
        li = ChangeOrderLineItem(
            change_order=self.co, action=ChangeOrderLineItem.ACTION_REPLACE,
            target_line_item=self.target,
            description='new price', qty=2, price=75, line_number=1,
        )
        li.full_clean()  # should not raise


class ChangeOrderLineItemAdjustmentFieldTests(FixtureTestCase):
    """adjustment_service/adjustment_percent are only valid on a replace
    line whose target is itself an adjustment line."""

    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        self.est = Estimate.objects.create(
            job=self.job, estimate_number='EST-CO-4', version=1,
            status=Estimate.STATUS_ACCEPTED,
        )
        self.co = ChangeOrder.objects.create(job=self.job, estimate=self.est)
        self.adj_scheme = RateScheme.objects.create(
            name='Rush-CO4', algorithm=RateScheme.PERCENTAGE,
            rate=Decimal('10'), unit_label='none', accounting_category_id=901,
        )
        self.plain_target = EstimateLineItem.objects.create(
            estimate=self.est, description='orig', qty=1, price=50, line_number=1,
        )
        self.adjustment_target = EstimateLineItem.objects.create(
            estimate=self.est, description='Rush surcharge', qty=1, price=50,
            line_number=2, adjustment_service=self.adj_scheme,
            adjustment_percent=Decimal('10'),
        )

    def test_adjustment_percent_on_add_line_invalid(self):
        li = ChangeOrderLineItem(
            change_order=self.co, action=ChangeOrderLineItem.ACTION_ADD,
            description='Rush', qty=1, price=5,
            adjustment_percent=Decimal('10'), line_number=1,
        )
        with self.assertRaises(ValidationError):
            li.full_clean()

    def test_adjustment_percent_on_replace_of_non_adjustment_line_invalid(self):
        li = ChangeOrderLineItem(
            change_order=self.co, action=ChangeOrderLineItem.ACTION_REPLACE,
            target_line_item=self.plain_target,
            description='Rush', qty=1, price=5,
            adjustment_percent=Decimal('10'), line_number=1,
        )
        with self.assertRaises(ValidationError):
            li.full_clean()

    def test_adjustment_percent_on_replace_of_adjustment_line_valid(self):
        li = ChangeOrderLineItem(
            change_order=self.co, action=ChangeOrderLineItem.ACTION_REPLACE,
            target_line_item=self.adjustment_target,
            description='Rush (bigger)', qty=1, price=8,
            adjustment_service=self.adj_scheme,
            adjustment_percent=Decimal('16'), line_number=1,
        )
        li.full_clean()  # should not raise


class DescopedByTests(FixtureTestCase):
    """Task.descoped_by / Material.descoped_by: stamped at CO acceptance,
    SET_NULL when the CO is deleted."""

    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        self.est = Estimate.objects.create(
            job=self.job, estimate_number='EST-CO-5', version=1,
            status=Estimate.STATUS_ACCEPTED,
        )
        self.co = ChangeOrder.objects.create(job=self.job, estimate=self.est)

    def test_task_descoped_by_settable_and_set_null_on_co_delete(self):
        task = Task.objects.create(job=self.job, name='Cutting', descoped_by=self.co)
        task.refresh_from_db()
        self.assertEqual(task.descoped_by_id, self.co.pk)

        self.co.delete()
        task.refresh_from_db()
        self.assertIsNone(task.descoped_by_id)

    def test_material_descoped_by_settable_and_set_null_on_co_delete(self):
        material = Material.objects.create(
            job=self.job, accounting_category_id=901, descoped_by=self.co,
        )
        material.refresh_from_db()
        self.assertEqual(material.descoped_by_id, self.co.pk)

        self.co.delete()
        material.refresh_from_db()
        self.assertIsNone(material.descoped_by_id)

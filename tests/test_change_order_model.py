from django.core.exceptions import ValidationError
from tests.base import FixtureTestCase
from apps.estimates.models import Estimate, EstimateLineItem, ChangeOrder, ChangeOrderLineItem
from apps.jobs.models import Job


def _add_line(co):
    return ChangeOrderLineItem.objects.create(
        change_order=co, action=ChangeOrderLineItem.ACTION_ADD,
        description='Added scope', qty=1, price=100, line_number=1,
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

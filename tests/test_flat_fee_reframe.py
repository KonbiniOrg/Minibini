from decimal import Decimal
from django.test import TestCase
from apps.core.models import AccountingCategory
from apps.jobs.models import ServiceItem, Task, PlanTask
from apps.estimates.models import TaskTemplate
from apps.jobs.flat_fee_reframe import reframe_flat_fee_prices


class FlatFeeReframeTest(TestCase):
    def setUp(self):
        self.ac = AccountingCategory.objects.create(name='Svc', code='SVC')
        self.shared = ServiceItem.objects.create(
            name='Flat Fee', algorithm=ServiceItem.FLAT_FEE,
            rate=Decimal('0.00'), unit_label='each', accounting_category=self.ac,
        )

    def _template(self, price):
        return TaskTemplate.objects.create(
            template_name='t', service_item=self.shared,
            default_active_modifiers={'flat_fee_price': str(price)},
            default_billable_qty=Decimal('1'),
        )

    def test_mints_per_price_service_and_repoints(self):
        t1 = self._template('1.00')
        t2 = self._template('30.00')
        t3 = self._template('1.00')  # same price as t1 -> shares minted service
        worklist = reframe_flat_fee_prices(ServiceItem, Task, PlanTask, TaskTemplate)
        t1.refresh_from_db(); t2.refresh_from_db(); t3.refresh_from_db()
        self.assertEqual(t1.service_item.rate, Decimal('1.00'))
        self.assertEqual(t2.service_item.rate, Decimal('30.00'))
        self.assertEqual(t1.service_item_id, t3.service_item_id)
        self.assertNotEqual(t1.service_item_id, t2.service_item_id)
        self.assertEqual(t1.default_active_modifiers, [])
        self.assertEqual(worklist, [])

    def test_logs_unresolved_zero_price(self):
        bad = self._template('0')
        worklist = reframe_flat_fee_prices(ServiceItem, Task, PlanTask, TaskTemplate)
        self.assertTrue(any(r[0] == 'TaskTemplate' and r[1] == bad.pk for r in worklist))

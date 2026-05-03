# tests/test_units_model_defaults.py
from decimal import Decimal
from tests.base import BaseTestCase
from apps.core.models import AccountingCategory
from apps.jobs.models import Task, Job, RateScheme
from apps.estimates.models import TaskTemplate
from apps.inventory.models import PriceListItem
from apps.invoicing.models import InvoiceLineItem


class UnitsDefaultTest(BaseTestCase):

    def test_task_defaults_to_none(self):
        job = Job.objects.first()
        task = Task.objects.create(
            name='Test Task',
            job=job,
        )
        self.assertEqual(task.units, 'none')

    def test_task_template_defaults_to_none(self):
        scheme = RateScheme.objects.get(pk=1)  # from fixture
        tt = TaskTemplate.objects.create(
            template_name='Test Template',
            rate_scheme=scheme,
            default_billable_qty=Decimal('1.00'),
        )
        self.assertEqual(tt.units, 'none')

    def test_price_list_item_defaults_to_none(self):
        category = AccountingCategory.objects.get_or_create(code='SVC', defaults={'name': 'Service', 'taxable': False})[0]
        pli = PriceListItem.objects.create(code='TEST-UNIT-PLI', accounting_category=category)
        self.assertEqual(pli.units, 'none')

    def test_line_item_defaults_to_none(self):
        """BaseLineItem default via InvoiceLineItem as a concrete subclass."""
        from apps.invoicing.models import Invoice
        job = Job.objects.first()
        if job:
            invoice = Invoice.objects.create(job=job)
            li = InvoiceLineItem.objects.create(invoice=invoice)
            self.assertEqual(li.units, 'none')

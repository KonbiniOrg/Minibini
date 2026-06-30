"""Tests for sort_order pass-through on Tasks generated from templates."""
from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from apps.jobs.models import Job, RateScheme
from apps.estimates.models import WorkTemplate, ServiceItem, TemplateTaskAssociation
from apps.contacts.models import Contact
from apps.core.models import User, AccountingCategory


class GenerateTaskSortOrderTest(TestCase):
    """generate_tasks_for_job should pass association sort_order through."""

    def setUp(self):
        self.contact = Contact.objects.create(first_name='Test', last_name='User')
        self.job = Job.objects.create(job_number='J001', contact=self.contact)
        self.lit_labor, _ = AccountingCategory.objects.get_or_create(
            code='LBR', defaults={'name': 'Labor'}
        )
        self.scheme = RateScheme.objects.create(
            name='S-gtso', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('1'), unit_label='ea', accounting_category=self.lit_labor,
        )

    def test_generated_tasks_get_association_sort_order(self):
        """Tasks should get the association's sort_order."""
        wot = WorkTemplate.objects.create(template_name='Test Template')
        tt1 = ServiceItem.objects.create(
            template_name='Sand',
            rate_scheme=self.scheme,
        )
        tt2 = ServiceItem.objects.create(
            template_name='Clean',
            rate_scheme=self.scheme,
        )
        # Use non-sequential sort_orders to verify they pass through
        TemplateTaskAssociation.objects.create(
            work_template=wot, service_item=tt1,
            est_qty=1, sort_order=5
        )
        TemplateTaskAssociation.objects.create(
            work_template=wot, service_item=tt2,
            est_qty=1, sort_order=10
        )

        # generate_tasks_for_job returns [(association, instance, Task), ...]
        # tuples. Extract the Task from each entry.
        tasks = [t for (_, _, t) in wot.generate_tasks_for_job(self.job)]

        sand = next(t for t in tasks if t.name == 'Sand')
        clean = next(t for t in tasks if t.name == 'Clean')
        self.assertEqual(sand.sort_order, 5)
        self.assertEqual(clean.sort_order, 10)

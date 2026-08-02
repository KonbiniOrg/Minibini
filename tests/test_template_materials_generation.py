from decimal import Decimal
from django.test import TestCase
from apps.core.models import AccountingCategory, Configuration
from apps.contacts.models import Contact
from apps.inventory.models import (
    Material, InventoryItem, TemplateMaterialAssociation,
)
from apps.estimates.models import (
    WorkTemplate, ServiceItem, TemplateTaskAssociation,
)
from apps.jobs.models import Job, RateScheme, Task


class _Setup(TestCase):
    @classmethod
    def setUpTestData(cls):
        Configuration.objects.update_or_create(key='units_list', defaults={'value': '["none","sheet","ea"]'})
        cls.cat = AccountingCategory.objects.create(code='MAT', name='Materials')
        cls.contact = Contact.objects.create(first_name='J', last_name='D', email='j@d.com')
        cls.scheme = RateScheme.objects.create(
            name='Hourly', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('100'), unit_label='hour',
            accounting_category=cls.cat,
        )
        cls.pli = InventoryItem.objects.create(
            code='PLI-1', units='sheet', description='Steel Sheet',
            purchase_price=Decimal('40.00'), selling_price=Decimal('60.00'),
            accounting_category=cls.cat,
        )
        cls.job = Job.objects.create(
            name='J', job_number='J-1', status=Job.STATUS_DRAFT, contact=cls.contact,
        )
        cls.wt = WorkTemplate.objects.create(template_name='T')
        cls.tt = ServiceItem.objects.create(
            template_name='Cut', rate_scheme=cls.scheme,
        )
        cls.tta = TemplateTaskAssociation.objects.create(
            work_template=cls.wt, service_item=cls.tt,
            est_qty=Decimal('20'), sort_order=0,
        )


class JobGenerationTests(_Setup):
    def test_task_less_association_generates_task_less_material(self):
        TemplateMaterialAssociation.objects.create(
            work_template=self.wt, inventory_item=self.pli,
            quantity=Decimal('5'),
        )
        # Tasks first, then materials
        self.wt.generate_tasks_for_job(self.job)
        self.wt.generate_materials_for_job(self.job)

        ms = list(Material.objects.filter(job=self.job, task__isnull=True))
        self.assertEqual(len(ms), 1)
        self.assertEqual(ms[0].inventory_item_id, self.pli.pk)
        self.assertEqual(ms[0].units, 'sheet')

    def test_task_paired_association_attaches_to_matching_task(self):
        TemplateMaterialAssociation.objects.create(
            work_template=self.wt, inventory_item=self.pli,
            template_task_association=self.tta,
            quantity=Decimal('2'),
        )
        task_pairing = self.wt.generate_tasks_for_job(self.job)
        self.wt.generate_materials_for_job(self.job, task_pairing=task_pairing)

        t = Task.objects.get(job=self.job)
        m = Material.objects.get(job=self.job)
        self.assertEqual(m.task_id, t.pk)

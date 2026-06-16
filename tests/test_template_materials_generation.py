from decimal import Decimal
from django.test import TestCase
from apps.core.models import AccountingCategory, Configuration
from apps.contacts.models import Contact
from apps.inventory.models import (
    Material, PlanMaterial, InventoryItem, TemplateMaterialAssociation,
)
from apps.estimates.models import (
    EstWorksheet, WorkTemplate, TaskTemplate, TemplateTaskAssociation,
)
from apps.jobs.models import Job, PlanTask, RateScheme, Task


class _Setup(TestCase):
    @classmethod
    def setUpTestData(cls):
        Configuration.objects.create(key='units_list', value='["none","sheets","ea"]')
        cls.cat = AccountingCategory.objects.create(code='MAT', name='Materials')
        cls.contact = Contact.objects.create(first_name='J', last_name='D', email='j@d.com')
        cls.scheme = RateScheme.objects.create(
            name='Hourly', rate=Decimal('100'), unit_label='hour',
            accounting_category=cls.cat,
        )
        cls.pli = InventoryItem.objects.create(
            code='PLI-1', units='sheets', description='Steel Sheet',
            purchase_price=Decimal('40.00'), selling_price=Decimal('60.00'),
            accounting_category=cls.cat,
        )
        cls.job = Job.objects.create(
            name='J', job_number='J-1', status=Job.STATUS_DRAFT, contact=cls.contact,
        )
        cls.wt = WorkTemplate.objects.create(template_name='T')
        cls.tt = TaskTemplate.objects.create(
            template_name='Cut', rate_scheme=cls.scheme,
            default_billable_qty=Decimal('20'),
        )
        cls.tta = TemplateTaskAssociation.objects.create(
            work_template=cls.wt, task_template=cls.tt,
            est_qty=Decimal('20'), sort_order=0,
        )


class WorksheetGenerationTests(_Setup):
    def test_task_less_association_generates_task_less_plan_material(self):
        TemplateMaterialAssociation.objects.create(
            work_template=self.wt, inventory_item=self.pli,
            quantity=Decimal('5'),
        )
        ws = EstWorksheet.objects.create(job=self.job)
        self.wt.generate_tasks_for_worksheet(ws)
        self.wt.generate_materials_for_worksheet(ws)

        pms = list(PlanMaterial.objects.filter(est_worksheet=ws, plan_task__isnull=True))
        self.assertEqual(len(pms), 1)
        self.assertEqual(pms[0].quantity, Decimal('5'))
        self.assertEqual(pms[0].inventory_item_id, self.pli.pk)
        self.assertEqual(pms[0].units, 'sheets')  # via _populate_from_pli

    def test_task_paired_association_attaches_to_matching_plan_task(self):
        TemplateMaterialAssociation.objects.create(
            work_template=self.wt, inventory_item=self.pli,
            template_task_association=self.tta,
            quantity=Decimal('2'),
        )
        ws = EstWorksheet.objects.create(job=self.job)
        task_pairing = self.wt.generate_tasks_for_worksheet(ws)
        self.wt.generate_materials_for_worksheet(ws, task_pairing=task_pairing)

        pt = PlanTask.objects.get(est_worksheet=ws)
        pm = PlanMaterial.objects.get(est_worksheet=ws)
        self.assertEqual(pm.plan_task_id, pt.pk)
        self.assertEqual(pm.quantity, Decimal('2'))

    def test_pli_price_change_after_template_setup_reflected_at_generation(self):
        TemplateMaterialAssociation.objects.create(
            work_template=self.wt, inventory_item=self.pli,
            quantity=Decimal('5'),
        )
        # PLI price bumped after the template was set up
        self.pli.purchase_price = Decimal('52.00')
        self.pli.selling_price = Decimal('78.00')
        self.pli.save()

        ws = EstWorksheet.objects.create(job=self.job)
        self.wt.generate_tasks_for_worksheet(ws)
        self.wt.generate_materials_for_worksheet(ws)

        pm = PlanMaterial.objects.get(est_worksheet=ws)
        self.assertEqual(pm.unit_cost, Decimal('52.00'))
        self.assertEqual(pm.sell_price, Decimal('78.00'))

    def test_multi_instance_replicates_per_instance_with_pairing(self):
        TemplateMaterialAssociation.objects.create(
            work_template=self.wt, inventory_item=self.pli,
            template_task_association=self.tta,
            quantity=Decimal('2'),
        )
        ws = EstWorksheet.objects.create(job=self.job)
        task_pairing = self.wt.generate_tasks_for_worksheet(ws, quantity=3)
        self.wt.generate_materials_for_worksheet(ws, quantity=3, task_pairing=task_pairing)

        # 3 PlanTasks, 3 PlanMaterials, each PlanMaterial paired with a unique PlanTask
        pts = list(PlanTask.objects.filter(est_worksheet=ws).order_by('plan_task_id'))
        pms = list(PlanMaterial.objects.filter(est_worksheet=ws).order_by('plan_material_id'))
        self.assertEqual(len(pts), 3)
        self.assertEqual(len(pms), 3)
        # Each PlanMaterial's plan_task is one of the generated tasks, and they pair 1:1.
        paired_task_ids = sorted(pm.plan_task_id for pm in pms)
        self.assertEqual(paired_task_ids, sorted(pt.pk for pt in pts))


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
        self.assertEqual(ms[0].units, 'sheets')

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
